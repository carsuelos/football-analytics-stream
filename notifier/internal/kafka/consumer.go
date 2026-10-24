// Package kafka reads the alerts topic as a consumer group, for package notify.
package kafka

import (
	"context"
	"log/slog"
	"strings"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"

	"github.com/carsuelos/football-analytics-stream/notifier/internal/notify"
)

const (
	// EnvPrefix marks the environment variables that configure the client.
	EnvPrefix = "KAFKA_"

	pollMs = 100
)

// ConfigFromEnv builds the client configuration from the environment: each
// KAFKA_* variable sets the librdkafka property named by the rest of it,
// lowercased, with dots for underscores (KAFKA_BOOTSTRAP_SERVERS sets
// bootstrap.servers). It is the same convention as the simulator's and the
// engine's, so one set of variables configures all three.
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

// Consumer is a notify.Source over a topic, as a member of a consumer group.
//
// Offsets are committed in the background, but only up to messages marked
// Done: a message the notifier was still delivering when it stopped is read
// again by the next member to get its partition. Create it with NewConsumer
// and Close it.
type Consumer struct {
	c     *kafka.Consumer
	topic string
	log   *slog.Logger
}

// NewConsumer joins the group (default "notifier", or KAFKA_GROUP_ID) to read
// topic. A new group starts at the oldest message: nothing published before
// it joined is missed, and notify.Notifier's MaxAge drops what is too old.
func NewConsumer(config map[string]string, topic string, log *slog.Logger) (*Consumer, error) {
	cm := kafka.ConfigMap{
		"client.id":                "notifier",
		"group.id":                 "notifier",
		"auto.offset.reset":        "earliest",
		"enable.auto.commit":       true,
		"enable.auto.offset.store": false,
	}
	for k, v := range config {
		cm[k] = v
	}
	c, err := kafka.NewConsumer(&cm)
	if err != nil {
		return nil, err
	}
	if err := c.Subscribe(topic, nil); err != nil {
		c.Close()
		return nil, err
	}
	return &Consumer{c: c, topic: topic, log: log}, nil
}

// Next implements notify.Source.
func (c *Consumer) Next(ctx context.Context) (notify.Message, error) {
	for ctx.Err() == nil {
		switch e := c.c.Poll(pollMs).(type) {
		case *kafka.Message:
			if e.TopicPartition.Error != nil {
				c.log.Warn("kafka: bad message", "error", e.TopicPartition.Error)
				continue
			}
			headers := make(map[string]string, len(e.Headers))
			for _, h := range e.Headers {
				headers[h.Key] = string(h.Value)
			}
			return notify.Message{
				Value:     e.Value,
				Timestamp: e.Timestamp,
				Partition: e.TopicPartition.Partition,
				Offset:    int64(e.TopicPartition.Offset),
				Headers:   headers,
			}, nil
		case kafka.Error:
			if e.IsFatal() {
				return notify.Message{}, e
			}
			// librdkafka recovers from the rest (a broker down, a rebalance) by itself.
			c.log.Warn("kafka", "error", e)
		}
	}
	return notify.Message{}, ctx.Err()
}

// Done implements notify.Source: the group's offset may move past msg.
func (c *Consumer) Done(msg notify.Message) error {
	_, err := c.c.StoreOffsets([]kafka.TopicPartition{{
		Topic:     &c.topic,
		Partition: msg.Partition,
		Offset:    kafka.Offset(msg.Offset + 1),
	}})
	return err
}

// Close commits what is done and leaves the group.
func (c *Consumer) Close() error {
	return c.c.Close()
}
