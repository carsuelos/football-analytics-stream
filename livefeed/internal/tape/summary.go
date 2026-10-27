package tape

import (
	"encoding/json"
	"sort"
	"time"
)

// Summary is what a tape holds, for a quick look.
type Summary struct {
	FixtureID      int64
	Name           string
	Lines          int
	Keyframes      int
	First, Last    time.Time
	LongestGap     time.Duration // between two lines, a sign of an outage
	FinalState     json.RawMessage
	Lists          map[string]int // elements in each list at the end (events, ball coordinates...)
	EventTypes     map[int]int    // the final events by type_id
	RemovedEvents  int            // events that disappeared along the way (e.g. ruled out by VAR)
	ScoreChanges   int            // lines that changed the scores
	FieldsReceived []string       // every field the fixture had at some point
}

// Summarize reads a tape.
func Summarize(path string) (Summary, error) {
	s := Summary{Lists: map[string]int{}, EventTypes: map[int]int{}}
	fields := map[string]bool{}
	var last map[string]json.RawMessage
	err := Read(path, func(snap Snapshot) error {
		s.FixtureID = snap.FixtureID
		if s.Lines == 0 {
			s.First = snap.ReceivedAt
		} else if gap := snap.ReceivedAt.Sub(s.Last); gap > s.LongestGap {
			s.LongestGap = gap
		}
		s.Last = snap.ReceivedAt
		s.Lines++
		if snap.Line.Keyframe != nil {
			s.Keyframes++
		}
		if _, ok := snap.Line.Set["scores"]; ok {
			s.ScoreChanges++
		} else if _, ok := snap.Line.Upsert["scores"]; ok {
			s.ScoreChanges++
		}
		s.RemovedEvents += len(snap.Line.Remove["events"])
		last = nil
		if err := json.Unmarshal(snap.Fixture, &last); err != nil {
			return err
		}
		for k := range last {
			fields[k] = true
		}
		return nil
	})
	if err != nil {
		return s, err
	}
	_ = json.Unmarshal(last["name"], &s.Name)
	s.FinalState = last["state_id"]
	for k, v := range last {
		var elems []json.RawMessage
		if json.Unmarshal(v, &elems) == nil {
			s.Lists[k] = len(elems)
		}
	}
	var events []struct {
		TypeID int `json:"type_id"`
	}
	_ = json.Unmarshal(last["events"], &events)
	for _, e := range events {
		s.EventTypes[e.TypeID]++
	}
	for k := range fields {
		s.FieldsReceived = append(s.FieldsReceived, k)
	}
	sort.Strings(s.FieldsReceived)
	return s, nil
}
