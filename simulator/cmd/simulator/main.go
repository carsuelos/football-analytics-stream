// Command simulator broadcasts StatsBomb matches as a live feed.
//
//	simulator [-addr :8080] [-data data/statsbomb] [-jitter 3s] [-seed 1] [-kafka-topic events]
//
// See package server for the HTTP and WebSocket API. If KAFKA_BOOTSTRAP_SERVERS
// is set, the broadcast also goes to a Kafka topic; see package kafka.
// LOG_FORMAT=json logs JSON, and OTEL_EXPORTER_OTLP_ENDPOINT turns tracing on;
// see package telemetry.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/broadcast"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/jitter"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/kafka"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/library"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/server"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/statsbomb"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/telemetry"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
)

const shutdownTimeout = 5 * time.Second

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "simulator:", err)
		os.Exit(1)
	}
}

// run holds the real main so that deferred cleanups run before os.Exit.
func run(args []string) error {
	flags := flag.NewFlagSet("simulator", flag.ExitOnError)
	addr := flags.String("addr", ":8080", "listen address")
	dataDir := flags.String("data", "data/statsbomb", "StatsBomb open-data directory (see make fetch-data)")
	maxDelay := flags.Duration("jitter", 0, "deliver events up to this much match time late, e.g. 3s (0 = off)")
	seed := flags.Uint64("seed", 1, "random seed for -jitter")
	downloads := flags.Bool("library", true, "let the dashboard download more matches into -data (GET and POST /library)")
	topic := flags.String("kafka-topic", "events", "Kafka topic to publish the broadcast to, if KAFKA_BOOTSTRAP_SERVERS is set")
	flags.Parse(args) // ExitOnError: -h exits 0, a bad flag exits 2
	if *maxDelay < 0 {
		return errors.New("-jitter must not be negative")
	}

	log := telemetry.Logger(os.Stderr, os.Getenv("LOG_FORMAT"), slog.LevelInfo)
	shutdownTracing, err := telemetry.Setup(context.Background(), "simulator")
	if err != nil {
		return fmt.Errorf("tracing: %w", err)
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
		defer cancel()
		if err := shutdownTracing(ctx); err != nil {
			log.Warn("flushing traces", "err", err)
		}
	}()

	var catalog match.Catalog = statsbomb.NewCatalog(*dataDir)
	infos, err := catalog.List()
	if err != nil {
		return err
	}
	if len(infos) == 0 {
		log.Warn("no matches found; run make fetch-data", "data", *dataDir)
	}
	if *maxDelay > 0 {
		catalog = jitter.Catalog{Inner: catalog, MaxDelay: maxDelay.Seconds(), Seed: *seed}
		log.Info("jitter on", "max_delay", *maxDelay, "seed", *seed)
	}

	// ctx is cancelled on Ctrl-C or SIGTERM (sent by Docker and Azure on stop).
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	broadcaster := broadcast.New(catalog)
	go broadcaster.Run(ctx)

	// Nil unless publishing to Kafka; receiving from it then blocks forever.
	var publishErr chan error
	if config, ok := kafka.ConfigFromEnv(os.Environ()); ok {
		producer, err := kafka.NewProducer(config, *topic, log)
		if err != nil {
			return err
		}
		publishErr = make(chan error, 1)
		published := make(chan struct{})
		defer func() {
			// Stop Publish and let it finish writing before delivering
			// what is queued and closing.
			stop()
			<-published
			producer.Close()
		}()
		// Subscribed before serving, so no match can be loaded before it.
		feed := broadcaster.Subscribe(0)
		go func() {
			defer close(published)
			if err := kafka.Publish(ctx, feed, producer); err != nil {
				publishErr <- err
			}
		}()
		log.Info("publishing to kafka", "bootstrap_servers", config["bootstrap.servers"], "topic", *topic)
	}

	// Listen before serving so a busy port fails here, before we log success.
	ln, err := net.Listen("tcp", *addr)
	if err != nil {
		return err
	}
	api := server.New(broadcaster, catalog, log)
	if *downloads {
		api.Library = library.New(*dataDir, log)
	}
	srv := &http.Server{
		Handler:           traced(api.Handler()),
		ReadHeaderTimeout: 10 * time.Second,
		// Every request context derives from ctx. Shutdown does not wait for
		// WebSocket connections, so this is how open feeds learn to close.
		BaseContext: func(net.Listener) context.Context { return ctx },
	}
	serveErr := make(chan error, 1)
	go func() { serveErr <- srv.Serve(ln) }()
	log.Info("simulator listening", "addr", ln.Addr().String(), "matches", len(infos), "tracing", telemetry.Enabled())

	select {
	case err := <-serveErr:
		return err
	case err := <-publishErr:
		return fmt.Errorf("publishing to kafka: %w", err)
	case <-ctx.Done():
	}
	stop() // a second Ctrl-C now exits immediately
	log.Info("shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	// Shutdown stops accepting connections and waits for plain HTTP requests;
	// open feeds are closed by ctx above, and WaitFeeds lets them finish
	// saying goodbye before the process exits.
	return errors.Join(srv.Shutdown(shutdownCtx), api.WaitFeeds(shutdownCtx))
}

// traced wraps h in a span per request, except for health checks and the
// WebSocket feed, which lasts as long as the connection.
func traced(h http.Handler) http.Handler {
	return otelhttp.NewHandler(h, "simulator",
		otelhttp.WithFilter(func(r *http.Request) bool {
			return r.URL.Path != "/feed" && r.URL.Path != "/healthz"
		}),
		otelhttp.WithSpanNameFormatter(func(_ string, r *http.Request) string {
			return r.Method + " " + r.URL.Path
		}),
	)
}
