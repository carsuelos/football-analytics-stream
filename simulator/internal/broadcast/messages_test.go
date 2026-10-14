package broadcast

import (
	"testing"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/match"
)

func TestMessagesIsTheWholeBroadcastFromKickOff(t *testing.T) {
	m := newMatch(1, at(1, 0), at(1, 10), at(2, 2700))
	var got []string
	for _, msg := range Messages(m) {
		roundTrip(t, &msg)
		got = append(got, describe(msg))
	}
	want := []string{
		"match_start m1 0 (1, 0) head 0", // head 0: everything after it is live
		"event m1-e0",
		"event m1-e1",
		"event m1-e2",
		"match_end m1 3 (2, 2700)",
	}
	if len(got) != len(want) {
		t.Fatalf("got %q, want %q", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("message %d: got %q, want %q", i, got[i], want[i])
		}
	}
}

func TestMessagesOfAnEmptyMatch(t *testing.T) {
	m := &match.Match{Info: newMatch(2).Info}
	var got []string
	for _, msg := range Messages(m) {
		got = append(got, describe(msg))
	}
	if len(got) != 2 || got[0] != "match_start m2 0 (1, 0) head 0" || got[1] != "match_end m2 0 (1, 0)" {
		t.Errorf("got %q", got)
	}
}
