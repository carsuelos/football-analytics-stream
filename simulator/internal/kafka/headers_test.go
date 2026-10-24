package kafka

import (
	"context"
	"testing"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

func TestHeadersCarryTraceContext(t *testing.T) {
	tp := sdktrace.NewTracerProvider()
	ctx, span := tp.Tracer("test").Start(context.Background(), "send events")
	defer span.End()

	var hs []kafka.Header
	carrier := Headers{&hs}
	carrier.Set("other", "kept")
	propagation.TraceContext{}.Inject(ctx, carrier)
	propagation.TraceContext{}.Inject(ctx, carrier) // replaces, doesn't append

	if len(hs) != 2 {
		t.Fatalf("headers = %v, want other and traceparent", hs)
	}
	got := propagation.TraceContext{}.Extract(context.Background(), Headers{&hs})
	sc, ext := span.SpanContext(), traceSpanContext(got)
	if ext.TraceID() != sc.TraceID() || ext.SpanID() != sc.SpanID() || !ext.IsRemote() {
		t.Errorf("extracted %v, want %v from afar", ext, sc)
	}
	if carrier.Get("other") != "kept" || carrier.Get("missing") != "" {
		t.Errorf("Get: other=%q missing=%q", carrier.Get("other"), carrier.Get("missing"))
	}
	if keys := carrier.Keys(); len(keys) != 2 || keys[0] != "other" || keys[1] != "traceparent" {
		t.Errorf("Keys = %v", keys)
	}
}

func traceSpanContext(ctx context.Context) trace.SpanContext {
	return trace.SpanContextFromContext(ctx)
}
