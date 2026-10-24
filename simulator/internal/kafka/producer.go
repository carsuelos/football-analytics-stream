package kafka

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/codes"
	semconv "go.opentelemetry.io/otel/semconv/v1.40.0"
	"go.opentelemetry.io/otel/trace"
)

const (
	// EnvPrefix marks the environment variables that configure the client.
	EnvPrefix = "KAFKA_"

	queueFullRetry = 50 * time.Millisecond
	flushTimeout   = 5 * time.Second
)

// ConfigFromEnv builds the client configuration from the environment: each
// KAFKA_* variable sets the librdkafka property named by the rest of it,
// lowercased, with dots for underscores. KAFKA_BOOTSTRAP_SERVERS=redpanda:9092
// sets bootstrap.servers, and Azure Event Hubs needs only
// KAFKA_SECURITY_PROTOCOL=SASL_SSL, KAFKA_SASL_MECHANISM=PLAIN,
// KAFKA_SASL_USERNAME='$ConnectionString' and KAFKA_SASL_PASSWORD on top.
//
// It returns false if KAFKA_BOOTSTRAP_SERVERS is not set.
func ConfigFromEnv(environ []string) (map[string]string, bool) {
	config := map[string]string{}
	for _, kv := range environ {
		name, value, _ := strings.Cut(kv, "=")
		if prop, ok := strings.CutPrefix(name, EnvPrefix); ok && prop != "" {
			config[strings.ReplaceAll(strings.ToLower(prop), "_", ".")] = value
		}
	}
	_, ok := config["bootstrap.servers"]
	return config, ok
}

// Producer writes to one topic. Create it with NewProducer and Close it.
type Producer struct {
	p     *kafka.Producer
	topic string
	done  chan struct{}
}

// NewProducer connects to the cluster in config, to write to topic.
//
// The producer is idempotent: the broker drops the duplicates its retries
// would cause, and messages stay in order. Failed deliveries are logged.
func NewProducer(config map[string]string, topic string, log *slog.Logger) (*Producer, error) {
	cm := kafka.ConfigMap{
		"client.id":          "simulator",
		"enable.idempotence": true,
		"linger.ms":          5,
	}
	for k, v := range config {
		cm[k] = v
	}
	p, err := kafka.NewProducer(&cm)
	if err != nil {
		return nil, fmt.Errorf("kafka producer: %w", err)
	}
	pr := &Producer{p: p, topic: topic, done: make(chan struct{})}
	go pr.report(log)
	return pr, nil
}

// report logs failed deliveries and client errors until the producer closes.
func (pr *Producer) report(log *slog.Logger) {
	defer close(pr.done)
	for e := range pr.p.Events() {
		switch ev := e.(type) {
		case *kafka.Message:
			if ev.TopicPartition.Error != nil {
				log.Error("kafka delivery failed", "topic", pr.topic, "err", ev.TopicPartition.Error)
			}
		case kafka.Error:
			// librdkafka reconnects by itself; most errors are transient.
			level := slog.LevelWarn
			if ev.IsFatal() {
				level = slog.LevelError
			}
			log.Log(context.Background(), level, "kafka", "err", ev)
		}
	}
}

// Write queues a message, in a "send" span whose trace context goes with it in
// the message's headers, so a consumer's work continues the same trace.
func (pr *Producer) Write(ctx context.Context, key, value []byte) (err error) {
	ctx, span := otel.Tracer(tracerName).Start(ctx, "send "+pr.topic,
		trace.WithSpanKind(trace.SpanKindProducer),
		trace.WithAttributes(
			semconv.MessagingSystemKafka,
			semconv.MessagingOperationTypeSend,
			semconv.MessagingDestinationName(pr.topic),
			semconv.MessagingKafkaMessageKey(string(key)),
		),
	)
	defer func() {
		if err != nil {
			span.SetStatus(codes.Error, err.Error())
		}
		span.End()
	}()
	msg := &kafka.Message{
		TopicPartition: kafka.TopicPartition{Topic: &pr.topic, Partition: kafka.PartitionAny},
		Key:            key,
		Value:          value,
	}
	otel.GetTextMapPropagator().Inject(ctx, Headers{&msg.Headers})
	for {
		err := pr.p.Produce(msg, nil)
		var kerr kafka.Error
		if !errors.As(err, &kerr) || kerr.Code() != kafka.ErrQueueFull {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(queueFullRetry):
		}
	}
}

const tracerName = "github.com/carsuelos/football-analytics-stream/simulator/internal/kafka"

// Headers carries trace context in a Kafka message's headers: it is a
// propagation.TextMapCarrier.
type Headers struct{ H *[]kafka.Header }

func (c Headers) Get(key string) string {
	for _, h := range *c.H {
		if h.Key == key {
			return string(h.Value)
		}
	}
	return ""
}

func (c Headers) Set(key, value string) {
	for i, h := range *c.H {
		if h.Key == key {
			(*c.H)[i].Value = []byte(value)
			return
		}
	}
	*c.H = append(*c.H, kafka.Header{Key: key, Value: []byte(value)})
}

func (c Headers) Keys() []string {
	keys := make([]string, len(*c.H))
	for i, h := range *c.H {
		keys[i] = h.Key
	}
	return keys
}

// Close waits up to 5 seconds for queued messages to be delivered, then closes
// the connection.
func (pr *Producer) Close() {
	pr.p.Flush(int(flushTimeout.Milliseconds()))
	pr.p.Close()
	<-pr.done
}
