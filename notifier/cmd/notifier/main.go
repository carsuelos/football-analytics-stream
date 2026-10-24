// Command notifier delivers the engine's alerts to webhooks, at least once.
//
//	notifier -webhook URL [-webhook URL...] [-topic alerts] [-max-age 5m] [-timeout 5s]
//
// Without -webhook it reads them from NOTIFIER_WEBHOOKS, separated by commas or
// spaces: a webhook URL often embeds a token, and an environment variable can
// come from a secret store where a command line can't.
//
// It reads the alerts topic as a member of a Kafka consumer group, configured
// by KAFKA_* environment variables (KAFKA_BOOTSTRAP_SERVERS is required), and
// POSTs each alert, as JSON, to every webhook. See package notify.
// LOG_FORMAT=json logs JSON, and OTEL_EXPORTER_OTLP_ENDPOINT turns tracing on;
// see package telemetry.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/carsuelos/football-analytics-stream/notifier/internal/kafka"
	"github.com/carsuelos/football-analytics-stream/notifier/internal/notify"
	"github.com/carsuelos/football-analytics-stream/notifier/internal/telemetry"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
)

func main() {
	if err := run(os.Args[1:], os.Environ()); err != nil {
		fmt.Fprintln(os.Stderr, "notifier:", err)
		os.Exit(1)
	}
}

type urls []string

func (u *urls) String() string { return strings.Join(*u, ",") }

// hosts are the webhooks without their paths, which often hold a token, for logging.
func (u urls) hosts() []string {
	hosts := make([]string, len(u))
	for i, s := range u {
		if parsed, err := url.Parse(s); err == nil {
			hosts[i] = parsed.Scheme + "://" + parsed.Host
		} else {
			hosts[i] = "(unparsable)"
		}
	}
	return hosts
}

// parseWebhooks splits s at commas and spaces into webhook URLs.
func parseWebhooks(s string) (urls, error) {
	var u urls
	for _, v := range strings.FieldsFunc(s, func(r rune) bool { return r == ',' || r == ' ' }) {
		if err := u.Set(v); err != nil {
			return nil, err
		}
	}
	return u, nil
}

func (u *urls) Set(v string) error {
	if !strings.HasPrefix(v, "http://") && !strings.HasPrefix(v, "https://") {
		return errors.New("want an http:// or https:// URL")
	}
	*u = append(*u, v)
	return nil
}

func run(args, environ []string) error {
	flags := flag.NewFlagSet("notifier", flag.ExitOnError)
	var webhooks urls
	flags.Var(&webhooks, "webhook", "URL to POST each alert to (repeatable, at least one)")
	topic := flags.String("topic", "alerts", "Kafka topic the engine publishes alerts to")
	maxAge := flags.Duration("max-age", 5*time.Minute, "drop alerts older than this instead of sending them late (0 = never)")
	timeout := flags.Duration("timeout", 5*time.Second, "timeout for each webhook request")
	verbose := flags.Bool("v", false, "also log repeats skipped")
	flags.Parse(args) // ExitOnError: -h exits 0, a bad flag exits 2
	if len(webhooks) == 0 {
		var err error
		if webhooks, err = parseWebhooks(env(environ, "NOTIFIER_WEBHOOKS")); err != nil {
			return fmt.Errorf("NOTIFIER_WEBHOOKS: %w", err)
		}
	}
	if len(webhooks) == 0 {
		return errors.New("give at least one -webhook, or set NOTIFIER_WEBHOOKS")
	}
	config, ok := kafka.ConfigFromEnv(environ)
	if !ok {
		return errors.New("set KAFKA_BOOTSTRAP_SERVERS (and any other KAFKA_* client settings)")
	}

	level := slog.LevelInfo
	if *verbose {
		level = slog.LevelDebug
	}
	log := telemetry.Logger(os.Stderr, os.Getenv("LOG_FORMAT"), level)
	shutdownTracing, err := telemetry.Setup(context.Background(), "notifier")
	if err != nil {
		return fmt.Errorf("tracing: %w", err)
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := shutdownTracing(ctx); err != nil {
			log.Warn("flushing traces", "err", err)
		}
	}()

	consumer, err := kafka.NewConsumer(config, *topic, log)
	if err != nil {
		return err
	}
	defer consumer.Close()
	log.Info("notifier delivering", "topic", *topic, "bootstrap_servers", config["bootstrap.servers"], "webhooks", webhooks.hosts(), "tracing", telemetry.Enabled())

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	n := notify.Notifier{
		Source:   consumer,
		Topic:    *topic,
		Webhooks: webhooks,
		Client:   &http.Client{Timeout: *timeout, Transport: otelhttp.NewTransport(http.DefaultTransport)},
		Backoff:  notify.Backoff{Initial: 500 * time.Millisecond, Max: 30 * time.Second},
		MaxAge:   *maxAge,
		Log:      log,
	}
	err = n.Run(ctx)
	log.Info("notifier stopped")
	return err
}

// env returns the value of name in environ, or "".
func env(environ []string, name string) string {
	for _, kv := range environ {
		if k, v, ok := strings.Cut(kv, "="); ok && k == name {
			return v
		}
	}
	return ""
}
