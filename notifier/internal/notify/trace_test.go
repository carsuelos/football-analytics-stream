package notify

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"go.opentelemetry.io/otel/trace"
)

func TestDeliveryContinuesTheEnginesTrace(t *testing.T) {
	recorder := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(recorder))
	prevTP, prevProp := otel.GetTracerProvider(), otel.GetTextMapPropagator()
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.TraceContext{})
	t.Cleanup(func() {
		otel.SetTracerProvider(prevTP)
		otel.SetTextMapPropagator(prevProp)
	})

	const traceID, engineSpan = "4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7"
	var mu sync.Mutex
	var sent string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		sent = r.Header.Get("traceparent")
		mu.Unlock()
		w.WriteHeader(http.StatusNoContent)
	}))
	t.Cleanup(srv.Close)

	f := newFeed(alert("a"))
	f.msgs[0].Headers = map[string]string{"traceparent": "00-" + traceID + "-" + engineSpan + "-01"}
	n, _ := newNotifier(f)
	n.Webhooks = []string{srv.URL}
	n.Topic = "alerts"
	n.Client = &http.Client{Transport: otelhttp.NewTransport(http.DefaultTransport)}
	runAll(t, n, f)

	mu.Lock()
	defer mu.Unlock()
	if !strings.HasPrefix(sent, "00-"+traceID+"-") {
		t.Errorf("the webhook got traceparent %q, not one in trace %s", sent, traceID)
	}
	var process, post sdktrace.ReadOnlySpan
	for _, s := range recorder.Ended() {
		switch s.SpanKind() {
		case trace.SpanKindConsumer:
			process = s
		case trace.SpanKindClient:
			post = s
		}
	}
	if process == nil || post == nil {
		t.Fatalf("spans: %v", recorder.Ended())
	}
	if process.Name() != "process alerts" || process.Parent().SpanID().String() != engineSpan || process.SpanContext().TraceID().String() != traceID {
		t.Errorf("process span %q has parent %v in trace %v", process.Name(), process.Parent().SpanID(), process.SpanContext().TraceID())
	}
	if post.Parent().SpanID() != process.SpanContext().SpanID() {
		t.Errorf("the webhook request is not under the process span")
	}
}
