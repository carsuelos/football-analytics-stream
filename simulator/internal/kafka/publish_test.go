package kafka

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"testing"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// feed returns its messages, then blocks until ctx is done.
type feed struct{ msgs []schema.FeedMessage }

func (f *feed) Next(ctx context.Context) (schema.FeedMessage, error) {
	if len(f.msgs) == 0 {
		<-ctx.Done()
		return schema.FeedMessage{}, ctx.Err()
	}
	msg := f.msgs[0]
	f.msgs = f.msgs[1:]
	return msg, nil
}

type record struct{ key, value string }

// writer records each write; once it has want of them, it calls done.
type writer struct {
	records []record
	want    int
	done    func()
	err     error
}

func (w *writer) Write(_ context.Context, key, value []byte) error {
	if w.err != nil {
		return w.err
	}
	w.records = append(w.records, record{string(key), string(value)})
	if len(w.records) == w.want {
		w.done()
	}
	return nil
}

func marker(kind schema.FeedMessageKind, matchID, offset int, head *int) schema.FeedMessage {
	m := &schema.FeedMarker{MatchID: schema.MatchID(matchID), Offset: schema.Offset(offset), Period: 1}
	if head != nil {
		h := schema.Offset(*head)
		m.Head = &h
	}
	return schema.FeedMessage{SchemaVersion: 1, Kind: kind, Marker: m}
}

func event(matchID, offset int) schema.FeedMessage {
	ev := &schema.MatchEvent{
		SchemaVersion: 1,
		ID:            fmt.Sprintf("m%d-e%d", matchID, offset),
		MatchID:       schema.MatchID(matchID),
		Offset:        schema.Offset(offset),
		Period:        1,
		Type:          schema.MatchEventTypeOther,
		Team:          schema.Team{ID: 1, Name: "Home FC"},
	}
	return schema.FeedMessage{SchemaVersion: 1, Kind: schema.FeedMessageKindEvent, Event: ev}
}

func decode(t *testing.T, value string) schema.FeedMessage {
	t.Helper()
	var msg schema.FeedMessage
	if err := json.Unmarshal([]byte(value), &msg); err != nil {
		t.Fatal(err)
	}
	return msg
}

func TestPublishesEveryMessageKeyedByMatch(t *testing.T) {
	head := 5
	start := marker(schema.FeedMessageKindMatchStart, 7, 0, &head)
	msgs := []schema.FeedMessage{
		start,
		event(7, 0),
		event(7, 1),
		marker(schema.FeedMessageKindMatchEnd, 7, 2, nil),
		marker(schema.FeedMessageKindMatchStart, 12, 0, nil),
	}
	ctx, cancel := context.WithCancel(t.Context())
	w := &writer{want: len(msgs), done: cancel}

	if err := Publish(ctx, &feed{msgs: msgs}, w); err != nil {
		t.Fatalf("Publish: %v", err)
	}

	keys := []string{}
	for _, r := range w.records {
		keys = append(keys, r.key)
	}
	if want := []string{"7", "7", "7", "7", "12"}; !reflect.DeepEqual(keys, want) {
		t.Errorf("keys = %v, want %v", keys, want)
	}
	got := decode(t, w.records[0].value)
	if got.Kind != schema.FeedMessageKindMatchStart || got.Marker.Head != nil {
		t.Errorf("match_start = %+v, want it without its head", got.Marker)
	}
	if *start.Marker.Head != 5 {
		t.Error("the feed's own message was modified")
	}
	if got := decode(t, w.records[2].value); got.Event == nil || got.Event.Offset != 1 {
		t.Errorf("third message = %+v, want event 1", got)
	}
}

func TestPublishFailsWhenAWriteFails(t *testing.T) {
	boom := errors.New("message too large")
	w := &writer{err: boom}
	err := Publish(t.Context(), &feed{msgs: []schema.FeedMessage{event(7, 0)}}, w)
	if !errors.Is(err, boom) {
		t.Fatalf("Publish = %v, want %v", err, boom)
	}
}

func TestPublishRejectsAnEmptyMessage(t *testing.T) {
	w := &writer{}
	empty := schema.FeedMessage{SchemaVersion: 1, Kind: schema.FeedMessageKindEvent}
	if err := Publish(t.Context(), &feed{msgs: []schema.FeedMessage{empty}}, w); err == nil {
		t.Fatal("Publish = nil, want an error")
	}
}

func TestConfigFromEnv(t *testing.T) {
	config, ok := ConfigFromEnv([]string{
		"HOME=/root",
		"KAFKA_BOOTSTRAP_SERVERS=ns.servicebus.windows.net:9093",
		"KAFKA_SECURITY_PROTOCOL=SASL_SSL",
		"KAFKA_SASL_USERNAME=$ConnectionString",
		"KAFKA_SASL_PASSWORD=Endpoint=sb://ns/;SharedAccessKey=k=",
		"KAFKA_=ignored",
	})
	want := map[string]string{
		"bootstrap.servers": "ns.servicebus.windows.net:9093",
		"security.protocol": "SASL_SSL",
		"sasl.username":     "$ConnectionString",
		"sasl.password":     "Endpoint=sb://ns/;SharedAccessKey=k=",
	}
	if !ok || !reflect.DeepEqual(config, want) {
		t.Errorf("ConfigFromEnv = %v, %v; want %v, true", config, ok, want)
	}
	if _, ok := ConfigFromEnv([]string{"KAFKA_CLIENT_ID=x"}); ok {
		t.Error("ConfigFromEnv without bootstrap servers = true, want false")
	}
}
