// Command simulator replays StatsBomb matches as a live feed.
//
//	simulator [-addr :8080] [-data data/statsbomb] [-jitter 3s] [-seed 1]
//
// See package server for the HTTP and WebSocket API.
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

	"github.com/carsuelos/football-analytics-stream/simulator/internal/jitter"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/playback"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/server"
	"github.com/carsuelos/football-analytics-stream/simulator/internal/statsbomb"
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
	flags.Parse(args) // ExitOnError: -h exits 0, a bad flag exits 2
	if *maxDelay < 0 {
		return errors.New("-jitter must not be negative")
	}

	log := slog.New(slog.NewTextHandler(os.Stderr, nil))

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

	player := playback.New(catalog)
	go player.Run(ctx)

	// Listen before serving so a busy port fails here, before we log success.
	ln, err := net.Listen("tcp", *addr)
	if err != nil {
		return err
	}
	api := server.New(player, catalog, log)
	srv := &http.Server{
		Handler:           api.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		// Every request context derives from ctx. Shutdown does not wait for
		// WebSocket connections, so this is how open feeds learn to close.
		BaseContext: func(net.Listener) context.Context { return ctx },
	}
	serveErr := make(chan error, 1)
	go func() { serveErr <- srv.Serve(ln) }()
	log.Info("simulator listening", "addr", ln.Addr().String(), "matches", len(infos))

	select {
	case err := <-serveErr:
		return err
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
