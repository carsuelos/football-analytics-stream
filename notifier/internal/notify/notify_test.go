package notify

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"
)

var now = time.Date(2026, 7, 19, 20, 0, 0, 0, time.UTC)

func alert(id string) []byte {
	return fmt.Appendf(nil, `{"schema_version":1,"id":%q,"match_id":7,"offset":12,"period":2,`+
		`"match_clock_s":4947.0,"type":"control_shift","team_id":2,"value":0.6,"threshold":0.5,`+
		`"window_s":300,"features":{"balance":0.6},"message":"France taking control"}`, id)
}

// feed is a Source over a fixed list of messages, all published at now.
// Once they run out, Next returns end if it is set, else blocks until ctx is
// done. finished is closed once every message is done.
type feed struct {
	mu       sync.Mutex
	msgs     []Message
	next     int
	done     []int64
	end      error
	finished chan struct{}
}

func newFeed(values ...[]byte) *feed {
	f := &feed{finished: make(chan struct{})}
	for i, v := range values {
		f.msgs = append(f.msgs, Message{Value: v, Timestamp: now, Partition: 0, Offset: int64(i)})
	}
	return f
}

func (f *feed) Next(ctx context.Context) (Message, error) {
	f.mu.Lock()
	if f.next < len(f.msgs) {
		defer f.mu.Unlock()
		f.next++
		return f.msgs[f.next-1], nil
	}
	f.mu.Unlock()
	if f.end != nil {
		return Message{}, f.end
	}
	<-ctx.Done()
	return Message{}, ctx.Err()
}

func (f *feed) Done(msg Message) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.done = append(f.done, msg.Offset)
	if len(f.done) == len(f.msgs) {
		close(f.finished)
	}
	return nil
}

func (f *feed) doneOffsets() []int64 {
	f.mu.Lock()
	defer f.mu.Unlock()
	return slices.Clone(f.done)
}

// hook is a webhook that answers with the given statuses in turn, then 204s,
// and records the alert ids it got (from the Idempotency-Key header).
type hook struct {
	mu      sync.Mutex
	answers []int
	got     []string
	srv     *httptest.Server
}

func newHook(t *testing.T, answers ...int) *hook {
	h := &hook{answers: answers}
	h.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		id := r.Header.Get("Idempotency-Key")
		if r.Method != http.MethodPost || r.Header.Get("Content-Type") != "application/json" ||
			!bytes.Equal(body, alert(id)) {
			t.Errorf("unexpected request: %s %v %s", r.Method, r.Header, body)
		}
		h.mu.Lock()
		defer h.mu.Unlock()
		h.got = append(h.got, id)
		status := http.StatusNoContent
		if len(h.answers) > 0 {
			status, h.answers = h.answers[0], h.answers[1:]
		}
		w.WriteHeader(status)
	}))
	t.Cleanup(h.srv.Close)
	return h
}

func (h *hook) ids() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return slices.Clone(h.got)
}

// logs is a log destination safe to read while the notifier writes to it.
type logs struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (l *logs) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.buf.Write(p)
}

func (l *logs) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.buf.String()
}

func newNotifier(src Source, hooks ...*hook) (*Notifier, *logs) {
	out := &logs{}
	n := &Notifier{
		Source:  src,
		Backoff: Backoff{Initial: time.Millisecond, Max: 4 * time.Millisecond},
		MaxAge:  time.Minute,
		Log:     slog.New(slog.NewTextHandler(out, &slog.HandlerOptions{Level: slog.LevelDebug})),
		Now:     func() time.Time { return now },
	}
	for _, h := range hooks {
		n.Webhooks = append(n.Webhooks, h.srv.URL)
	}
	return n, out
}

// runAll runs n until every message in f is done, then stops it.
func runAll(t *testing.T, n *Notifier, f *feed) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	stopped := make(chan error, 1)
	go func() { stopped <- n.Run(ctx) }()
	select {
	case <-f.finished:
	case err := <-stopped:
		t.Fatalf("Run stopped early: %v", err)
	case <-time.After(5 * time.Second):
		t.Fatalf("timed out with %v done of %d", f.doneOffsets(), len(f.msgs))
	}
	cancel()
	if err := <-stopped; err != nil {
		t.Fatalf("Run: %v", err)
	}
}

func TestDeliversEachAlertToEveryWebhookThenMarksItDone(t *testing.T) {
	a, b := newHook(t), newHook(t)
	f := newFeed(alert("7-a-1-1"), alert("7-a-1-2"))
	n, out := newNotifier(f, a, b)
	runAll(t, n, f)
	for _, h := range []*hook{a, b} {
		if got := h.ids(); !slices.Equal(got, []string{"7-a-1-1", "7-a-1-2"}) {
			t.Errorf("webhook got %v", got)
		}
	}
	if done := f.doneOffsets(); !slices.Equal(done, []int64{0, 1}) {
		t.Errorf("done %v", done)
	}
	if !strings.Contains(out.String(), "msg=delivered alert=7-a-1-1 type=control_shift match=7") {
		t.Errorf("logs:\n%s", out)
	}
}

func TestSkipsAlertsAlreadyDelivered(t *testing.T) {
	h := newHook(t)
	// A re-watch publishes alerts again; only new ones go out.
	f := newFeed(alert("x"), alert("y"), alert("x"), alert("y"), alert("z"))
	n, out := newNotifier(f, h)
	runAll(t, n, f)
	if got := h.ids(); !slices.Equal(got, []string{"x", "y", "z"}) {
		t.Errorf("webhook got %v", got)
	}
	if len(f.doneOffsets()) != 5 {
		t.Errorf("done %v", f.doneOffsets())
	}
	if !strings.Contains(out.String(), "msg=\"already delivered\" alert=x") {
		t.Errorf("logs:\n%s", out)
	}
}

func TestForgetsTheOldestIDsBeyondRemember(t *testing.T) {
	h := newHook(t)
	f := newFeed(alert("a"), alert("b"), alert("c"), alert("a"), alert("c"))
	n, _ := newNotifier(f, h)
	n.Remember = 2
	runAll(t, n, f)
	if got := h.ids(); !slices.Equal(got, []string{"a", "b", "c", "a"}) {
		t.Errorf("webhook got %v", got)
	}
}

func TestRetriesFailuresThatMayPass(t *testing.T) {
	flaky := newHook(t, 503, 429, 500)
	fine := newHook(t)
	f := newFeed(alert("x"))
	n, out := newNotifier(f, flaky, fine)
	runAll(t, n, f)
	if got := flaky.ids(); !slices.Equal(got, []string{"x", "x", "x", "x"}) {
		t.Errorf("flaky webhook got %v", got)
	}
	// The webhook that took it the first time doesn't get it again.
	if got := fine.ids(); !slices.Equal(got, []string{"x"}) {
		t.Errorf("fine webhook got %v", got)
	}
	if strings.Count(out.String(), "webhook failed, will retry") != 3 {
		t.Errorf("logs:\n%s", out)
	}
}

func TestRetriesNetworkErrors(t *testing.T) {
	h := newHook(t)
	down := httptest.NewServer(http.NotFoundHandler())
	down.Close() // nothing listens there now
	f := newFeed(alert("x"))
	n, out := newNotifier(f, h)
	n.Webhooks = append(n.Webhooks, down.URL)
	n.MaxAge = 0
	ctx, cancel := context.WithCancel(context.Background())
	stopped := make(chan error, 1)
	go func() { stopped <- n.Run(ctx) }()
	for strings.Count(out.String(), "webhook failed, will retry") < 3 {
		time.Sleep(time.Millisecond)
	}
	cancel() // stopped mid-delivery: not done, so the next notifier gets it
	if err := <-stopped; err != nil {
		t.Fatalf("Run: %v", err)
	}
	if done := f.doneOffsets(); len(done) != 0 {
		t.Errorf("done %v", done)
	}
}

func TestGivesUpOnClientErrors(t *testing.T) {
	h := newHook(t, 400)
	f := newFeed(alert("x"), alert("x"))
	n, out := newNotifier(f, h)
	runAll(t, n, f)
	if got := h.ids(); !slices.Equal(got, []string{"x"}) {
		t.Errorf("webhook got %v", got)
	}
	if !strings.Contains(out.String(), "webhook rejected the alert, giving up") {
		t.Errorf("logs:\n%s", out)
	}
}

func TestDropsStaleAlerts(t *testing.T) {
	h := newHook(t)
	f := newFeed(alert("old"), alert("new"))
	f.msgs[0].Timestamp = now.Add(-2 * time.Minute)
	n, out := newNotifier(f, h)
	runAll(t, n, f)
	if got := h.ids(); !slices.Equal(got, []string{"new"}) {
		t.Errorf("webhook got %v", got)
	}
	if !strings.Contains(out.String(), "msg=\"dropping a stale alert\" alert=old age=2m0s") {
		t.Errorf("logs:\n%s", out)
	}
}

func TestGivesUpRetryingOnceTheAlertIsStale(t *testing.T) {
	h := newHook(t, 503, 503, 503, 503, 503, 503)
	f := newFeed(alert("x"))
	n, out := newNotifier(f, h)
	var mu sync.Mutex
	clock := now
	n.Now = func() time.Time {
		mu.Lock()
		defer mu.Unlock()
		clock = clock.Add(25 * time.Second) // a minute passes in 3 attempts
		return clock
	}
	runAll(t, n, f)
	if got := len(h.ids()); got != 2 {
		t.Errorf("webhook got %d attempts", got)
	}
	if !strings.Contains(out.String(), "dropping a stale alert") {
		t.Errorf("logs:\n%s", out)
	}
}

func TestSkipsBadMessages(t *testing.T) {
	h := newHook(t)
	missingID := bytes.Replace(alert(""), []byte(`"id":"",`), nil, 1)
	f := newFeed([]byte("not json"), missingID, alert("x"))
	n, out := newNotifier(f, h)
	runAll(t, n, f)
	if got := h.ids(); !slices.Equal(got, []string{"x"}) {
		t.Errorf("webhook got %v", got)
	}
	if strings.Count(out.String(), "skipping a bad message") != 2 {
		t.Errorf("logs:\n%s", out)
	}
}

func TestStopsWhenTheSourceFails(t *testing.T) {
	f := newFeed()
	f.end = errors.New("broker gone")
	n, _ := newNotifier(f, newHook(t))
	if err := n.Run(context.Background()); err == nil || !strings.Contains(err.Error(), "broker gone") {
		t.Errorf("Run: %v", err)
	}
}
