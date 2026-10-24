// Command markets serves the prediction markets' prices for our leagues' games
// (see package board): which games Kalshi, Polymarket US and Novig list, their
// prices for the same contracts, and the cheapest all-in.
//
//	markets [-addr :8090] [-interval 10s] [-idle-interval 2m]
//
// It reads only the venues' public market data, so it needs no keys.
// LOG_FORMAT=json logs JSON, and OTEL_EXPORTER_OTLP_ENDPOINT turns tracing on
// (package telemetry), including a span per venue request.
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

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

	"github.com/carsuelos/football-analytics-stream/markets/internal/board"
	"github.com/carsuelos/football-analytics-stream/markets/internal/kalshi"
	"github.com/carsuelos/football-analytics-stream/markets/internal/novig"
	"github.com/carsuelos/football-analytics-stream/markets/internal/polymarket"
	"github.com/carsuelos/football-analytics-stream/markets/internal/server"
	"github.com/carsuelos/football-analytics-stream/markets/internal/telemetry"
	"github.com/carsuelos/football-analytics-stream/markets/internal/venue"
)

const shutdownTimeout = 5 * time.Second

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "markets:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	flags := flag.NewFlagSet("markets", flag.ExitOnError)
	addr := flags.String("addr", ":8090", "listen address")
	interval := flags.Duration("interval", 10*time.Second, "how often to poll the venues for a league someone is looking at")
	idle := flags.Duration("idle-interval", 2*time.Minute, "how often to poll them for the other leagues")
	flags.Parse(args)
	if *interval <= 0 || *idle <= 0 {
		return errors.New("-interval and -idle-interval must be positive")
	}

	log := telemetry.Logger(os.Stderr, os.Getenv("LOG_FORMAT"), slog.LevelInfo)
	shutdownTracing, err := telemetry.Setup(context.Background(), "markets")
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

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	client := &http.Client{Timeout: 10 * time.Second, Transport: otelhttp.NewTransport(http.DefaultTransport)}
	b := board.New([]venue.Source{kalshi.New(client), polymarket.New(client), novig.New(client)}, log)
	b.Interval, b.IdleInterval = *interval, *idle
	go b.Run(ctx)

	ln, err := net.Listen("tcp", *addr)
	if err != nil {
		return err
	}
	srv := &http.Server{
		Handler: otelhttp.NewHandler(server.New(b, log), "markets",
			otelhttp.WithFilter(func(r *http.Request) bool { return r.URL.Path != "/healthz" }),
			otelhttp.WithSpanNameFormatter(func(_ string, r *http.Request) string { return r.Method + " " + r.URL.Path }),
		),
		ReadHeaderTimeout: 10 * time.Second,
	}
	serveErr := make(chan error, 1)
	go func() { serveErr <- srv.Serve(ln) }()
	log.Info("markets listening", "addr", ln.Addr().String(), "interval", *interval, "tracing", telemetry.Enabled())

	select {
	case err := <-serveErr:
		return err
	case <-ctx.Done():
	}
	stop()
	log.Info("shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	return srv.Shutdown(shutdownCtx)
}
