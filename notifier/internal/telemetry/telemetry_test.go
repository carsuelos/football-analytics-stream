package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"

	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

func TestJSONLogsCarryTheSpan(t *testing.T) {
	var buf bytes.Buffer
	log := Logger(&buf, "json", slog.LevelInfo).With("app", "notifier")
	ctx, span := sdktrace.NewTracerProvider().Tracer("test").Start(context.Background(), "work")
	log.InfoContext(ctx, "in a span", "n", 1)
	span.End()
	log.Debug("below the level")
	log.Info("outside")

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("got %d lines: %s", len(lines), buf.String())
	}
	var first, second map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &first); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal([]byte(lines[1]), &second); err != nil {
		t.Fatal(err)
	}
	sc := span.SpanContext()
	if first["msg"] != "in a span" || first["app"] != "notifier" || first["trace_id"] != sc.TraceID().String() || first["span_id"] != sc.SpanID().String() {
		t.Errorf("first line = %v", first)
	}
	if _, ok := second["trace_id"]; ok {
		t.Errorf("a line outside any span has a trace_id: %v", second)
	}
}

func TestTextLogsByDefault(t *testing.T) {
	var buf bytes.Buffer
	Logger(&buf, "", slog.LevelInfo).Info("hello", "k", "v")
	if got := buf.String(); !strings.Contains(got, "msg=hello k=v") {
		t.Errorf("got %q", got)
	}
}

func TestTracingIsOffWithoutAnEndpoint(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
	if Enabled() {
		t.Fatal("Enabled with no endpoint")
	}
	shutdown, err := Setup(context.Background(), "notifier")
	if err != nil {
		t.Fatal(err)
	}
	if err := shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
}
