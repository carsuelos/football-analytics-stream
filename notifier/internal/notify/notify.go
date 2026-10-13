// Package notify delivers alerts to webhooks, at least once.
//
// A Notifier reads alerts from a Source (in production, a Kafka consumer
// group on the engine's alerts topic) and POSTs each one, as it was
// published, to every webhook. Only once it is delivered (or can't be) is it
// marked done, so the group's committed offset never passes an alert that
// wasn't delivered: if the notifier stops, the next one starts there.
//
// The same alert can come twice: the engine publishes a stretch of the match
// again when its viewer re-watches it, and at-least-once delivery repeats
// whatever was in flight when a notifier stopped. Alerts already delivered
// are recognized by id and skipped, and every request carries the alert id as
// an Idempotency-Key header so a webhook can drop repeats the notifier
// doesn't remember.
package notify

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"slices"
	"time"

	"github.com/carsuelos/football-analytics-stream/notifier/internal/schema"
)

// Message is one record from the alerts topic.
type Message struct {
	Value     []byte
	Timestamp time.Time // when it was published
	Partition int32
	Offset    int64
}

// Source is where alerts come from.
type Source interface {
	// Next blocks until the next message. Once ctx is done it returns ctx.Err().
	Next(ctx context.Context) (Message, error)
	// Done marks msg handled, so it won't be read again after a restart.
	Done(msg Message) error
}

// Backoff is how long to wait between attempts: Initial, doubling up to Max.
type Backoff struct {
	Initial, Max time.Duration
}

// Notifier delivers alerts from a Source to webhooks. Set the fields, then Run.
type Notifier struct {
	Source   Source
	Webhooks []string
	Client   *http.Client
	Backoff  Backoff
	// MaxAge, if positive, is how old an alert may be and still be worth
	// sending: older ones (from a backlog after downtime, or held up by a
	// failing webhook) are dropped with a warning. A stale tactical alert is
	// noise.
	MaxAge time.Duration
	// Remember is how many delivered alert ids to remember for skipping
	// repeats (default 10000).
	Remember int
	Log      *slog.Logger
	Now      func() time.Time // default time.Now

	seen *recent
}

// Run delivers alerts until ctx is done (then it returns nil) or the source
// fails.
func (n *Notifier) Run(ctx context.Context) error {
	if n.Now == nil {
		n.Now = time.Now
	}
	if n.Client == nil {
		n.Client = http.DefaultClient
	}
	if n.seen == nil {
		size := n.Remember
		if size <= 0 {
			size = 10000
		}
		n.seen = newRecent(size)
	}
	for {
		msg, err := n.Source.Next(ctx)
		if ctx.Err() != nil {
			return nil
		}
		if err != nil {
			return fmt.Errorf("reading alerts: %w", err)
		}
		if !n.handle(ctx, msg) {
			return nil // stopped mid-delivery: the next notifier delivers it
		}
		if err := n.Source.Done(msg); err != nil {
			n.Log.Warn("could not mark an alert done", "partition", msg.Partition, "offset", msg.Offset, "error", err)
		}
	}
}

// handle delivers msg to every webhook, retrying failures that may pass. It
// returns false if ctx was done before it finished.
func (n *Notifier) handle(ctx context.Context, msg Message) bool {
	var alert schema.Alert
	if err := json.Unmarshal(msg.Value, &alert); err != nil {
		n.Log.Warn("skipping a bad message", "partition", msg.Partition, "offset", msg.Offset, "error", err)
		return true
	}
	log := n.Log.With("alert", alert.ID)
	if n.seen.has(alert.ID) {
		log.Debug("already delivered")
		return true
	}
	pending := slices.Clone(n.Webhooks)
	delay := n.Backoff.Initial
	for {
		if age := n.Now().Sub(msg.Timestamp); n.MaxAge > 0 && age > n.MaxAge {
			log.Warn("dropping a stale alert", "age", age.Round(time.Second), "undelivered", pending)
			return true
		}
		pending = slices.DeleteFunc(pending, func(url string) bool {
			return n.post(ctx, log, url, alert.ID, msg.Value)
		})
		if len(pending) == 0 {
			n.seen.add(alert.ID)
			log.Info("delivered", "type", alert.Type, "match", alert.MatchID)
			return true
		}
		select {
		case <-ctx.Done():
			return false
		case <-time.After(delay):
		}
		delay = min(delay*2, n.Backoff.Max)
	}
}

// post sends the alert to url. It returns false if that failed but may work
// on a retry: a network error, a server error, or 429 Too Many Requests. Any
// other client error won't pass on a retry, so it is logged and given up on.
func (n *Notifier) post(ctx context.Context, log *slog.Logger, url, id string, body []byte) bool {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		log.Error("bad webhook URL, giving up", "webhook", url, "error", err)
		return true
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", id)
	resp, err := n.Client.Do(req)
	if err != nil {
		if ctx.Err() == nil {
			log.Warn("webhook failed, will retry", "webhook", url, "error", err)
		}
		return false
	}
	resp.Body.Close()
	switch status := resp.StatusCode; {
	case status < 300:
		return true
	case status >= 500 || status == http.StatusTooManyRequests:
		log.Warn("webhook failed, will retry", "webhook", url, "status", status)
		return false
	default:
		log.Error("webhook rejected the alert, giving up", "webhook", url, "status", status)
		return true
	}
}

// recent remembers the last size ids added.
type recent struct {
	ids   map[string]struct{}
	order []string // a ring: next is the oldest once full
	next  int
}

func newRecent(size int) *recent {
	return &recent{ids: make(map[string]struct{}, size), order: make([]string, 0, size)}
}

func (r *recent) has(id string) bool {
	_, ok := r.ids[id]
	return ok
}

func (r *recent) add(id string) {
	if r.has(id) {
		return
	}
	if len(r.order) < cap(r.order) {
		r.order = append(r.order, id)
	} else {
		delete(r.ids, r.order[r.next])
		r.order[r.next] = id
		r.next = (r.next + 1) % len(r.order)
	}
	r.ids[id] = struct{}{}
}
