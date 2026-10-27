// Package tape records what the live feed sent, so a match can be replayed
// offline exactly as it was received: for tests, for tuning, and for training.
//
// A tape is a JSON Lines file per fixture. Its first line is a keyframe (the
// whole fixture as the API sent it) and each later line holds only what
// changed since the line before, which keeps a match's tape small even though
// every poll returns hundreds of ball positions:
//
//   - set: fields whose value changed (or appeared), as sent;
//   - unset: fields that disappeared;
//   - upsert: for a list of objects with ids (events, ball coordinates,
//     statistics...), the elements that are new or changed;
//   - remove: the ids of a list's elements that disappeared (a goal ruled out).
//
// A keyframe is written every KeyframeEvery too, so a tape can be read from
// any keyframe. Replaying a tape gives back each fixture as received, except
// that a list's new elements come after the ones already there.
package tape

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// DefaultKeyframeEvery is how often a whole fixture is written again.
const DefaultKeyframeEvery = 5 * time.Minute

// Line is one line of a tape.
type Line struct {
	ReceivedAt time.Time                    `json:"received_at"`
	FixtureID  int64                        `json:"fixture_id"`
	Keyframe   map[string]json.RawMessage   `json:"keyframe,omitempty"`
	Set        map[string]json.RawMessage   `json:"set,omitempty"`
	Unset      []string                     `json:"unset,omitempty"`
	Upsert     map[string][]json.RawMessage `json:"upsert,omitempty"`
	Remove     map[string][]json.RawMessage `json:"remove,omitempty"`
}

func (l Line) empty() bool {
	return l.Keyframe == nil && len(l.Set) == 0 && len(l.Unset) == 0 && len(l.Upsert) == 0 && len(l.Remove) == 0
}

// fixture is a fixture's state: its plain fields, and its lists of objects
// with ids, kept in order.
type fixture struct {
	fields map[string]json.RawMessage
	lists  map[string]*list
}

type list struct {
	ids   []string // each element's id, as JSON, in order
	items map[string]json.RawMessage
}

// parse splits a fixture into its fields and its lists of objects with ids.
func parse(raw json.RawMessage) (*fixture, int64, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return nil, 0, fmt.Errorf("tape: fixture: %w", err)
	}
	var id int64
	if err := json.Unmarshal(fields["id"], &id); err != nil || id == 0 {
		return nil, 0, errors.New("tape: fixture without an id")
	}
	f := &fixture{fields: map[string]json.RawMessage{}, lists: map[string]*list{}}
	for k, v := range fields {
		if l, ok := asList(v); ok {
			f.lists[k] = l
		} else {
			f.fields[k] = v
		}
	}
	return f, id, nil
}

// asList reads v as a non-empty list of objects that each have an id.
func asList(v json.RawMessage) (*list, bool) {
	if len(v) == 0 || v[0] != '[' {
		return nil, false
	}
	var elems []json.RawMessage
	if json.Unmarshal(v, &elems) != nil || len(elems) == 0 {
		return nil, false
	}
	l := &list{items: map[string]json.RawMessage{}}
	for _, e := range elems {
		id, ok := idOf(e)
		if !ok {
			return nil, false
		}
		if _, dup := l.items[id]; !dup {
			l.ids = append(l.ids, id)
		}
		l.items[id] = e
	}
	return l, true
}

func idOf(e json.RawMessage) (string, bool) {
	var obj struct {
		ID json.RawMessage `json:"id"`
	}
	if json.Unmarshal(e, &obj) != nil || len(obj.ID) == 0 || string(obj.ID) == "null" {
		return "", false
	}
	return string(obj.ID), true
}

func (l *list) raw() json.RawMessage {
	elems := make([]json.RawMessage, len(l.ids))
	for i, id := range l.ids {
		elems[i] = l.items[id]
	}
	b, _ := json.Marshal(elems)
	return b
}

func (f *fixture) raw() json.RawMessage {
	b, _ := json.Marshal(f.all())
	return b
}

func (f *fixture) all() map[string]json.RawMessage {
	out := make(map[string]json.RawMessage, len(f.fields)+len(f.lists))
	for k, v := range f.fields {
		out[k] = v
	}
	for k, l := range f.lists {
		out[k] = l.raw()
	}
	return out
}

// diff is what changed from prev to cur, as a line without its time and id.
func diff(prev, cur *fixture) Line {
	var l Line
	set := func(k string, v json.RawMessage) {
		if l.Set == nil {
			l.Set = map[string]json.RawMessage{}
		}
		l.Set[k] = v
	}
	for k := range prev.fields {
		if _, ok := cur.fields[k]; !ok {
			if _, nowList := cur.lists[k]; !nowList {
				l.Unset = append(l.Unset, k)
			}
		}
	}
	for k := range prev.lists {
		if _, ok := cur.lists[k]; !ok {
			if _, nowField := cur.fields[k]; !nowField {
				l.Unset = append(l.Unset, k)
			}
		}
	}
	for k, v := range cur.fields {
		if old, ok := prev.fields[k]; !ok || !bytes.Equal(old, v) {
			set(k, v)
		}
	}
	for k, cl := range cur.lists {
		pl, ok := prev.lists[k]
		if !ok {
			// A new list, or a field that became one: send it whole.
			set(k, cl.raw())
			continue
		}
		for _, id := range cl.ids {
			if old, ok := pl.items[id]; !ok || !bytes.Equal(old, cl.items[id]) {
				if l.Upsert == nil {
					l.Upsert = map[string][]json.RawMessage{}
				}
				l.Upsert[k] = append(l.Upsert[k], cl.items[id])
			}
		}
		for _, id := range pl.ids {
			if _, ok := cl.items[id]; !ok {
				if l.Remove == nil {
					l.Remove = map[string][]json.RawMessage{}
				}
				l.Remove[k] = append(l.Remove[k], json.RawMessage(id))
			}
		}
	}
	return l
}

// apply changes f by a line that isn't a keyframe.
func (f *fixture) apply(l Line) error {
	for _, k := range l.Unset {
		delete(f.fields, k)
		delete(f.lists, k)
	}
	for k, v := range l.Set {
		delete(f.fields, k)
		delete(f.lists, k)
		if nl, ok := asList(v); ok {
			f.lists[k] = nl
		} else {
			f.fields[k] = v
		}
	}
	for k, elems := range l.Upsert {
		lst, ok := f.lists[k]
		if !ok {
			return fmt.Errorf("tape: upsert into %q, which isn't a list", k)
		}
		for _, e := range elems {
			id, ok := idOf(e)
			if !ok {
				return fmt.Errorf("tape: upsert into %q without an id", k)
			}
			if _, had := lst.items[id]; !had {
				lst.ids = append(lst.ids, id)
			}
			lst.items[id] = e
		}
	}
	for k, ids := range l.Remove {
		lst, ok := f.lists[k]
		if !ok {
			return fmt.Errorf("tape: remove from %q, which isn't a list", k)
		}
		for _, raw := range ids {
			id := string(raw)
			delete(lst.items, id)
			for i, x := range lst.ids {
				if x == id {
					lst.ids = append(lst.ids[:i], lst.ids[i+1:]...)
					break
				}
			}
		}
	}
	return nil
}

// Writer records polls to tapes in Dir: <Dir>/<UTC date>/<fixture id>.jsonl,
// the date being the day it first saw the fixture.
type Writer struct {
	Dir           string
	KeyframeEvery time.Duration
	tapes         map[int64]*recording
}

type recording struct {
	file     *os.File
	state    *fixture
	keyframe time.Time
}

// NewWriter returns a writer to dir.
func NewWriter(dir string) *Writer {
	return &Writer{Dir: dir, KeyframeEvery: DefaultKeyframeEvery, tapes: map[int64]*recording{}}
}

// Record writes what changed in each fixture of a poll received at at, and
// returns how many lines it wrote. A fixture that's no longer in the poll has
// left the livescores; its tape is closed, and if it comes back, its next line
// is a keyframe.
func (w *Writer) Record(at time.Time, fixtures []json.RawMessage) (int, error) {
	seen := map[int64]bool{}
	written := 0
	var errs []error
	for _, raw := range fixtures {
		cur, id, err := parse(raw)
		if err != nil {
			errs = append(errs, err)
			continue
		}
		seen[id] = true
		r, err := w.open(id, at)
		if err != nil {
			errs = append(errs, err)
			continue
		}
		line := Line{ReceivedAt: at.UTC(), FixtureID: id}
		if r.state == nil || at.Sub(r.keyframe) >= w.KeyframeEvery {
			line.Keyframe = cur.all()
			r.keyframe = at
		} else {
			d := diff(r.state, cur)
			if d.empty() {
				continue
			}
			line.Set, line.Unset, line.Upsert, line.Remove = d.Set, d.Unset, d.Upsert, d.Remove
		}
		b, err := json.Marshal(line)
		if err != nil {
			errs = append(errs, err)
			continue
		}
		if _, err := r.file.Write(append(b, '\n')); err != nil {
			errs = append(errs, fmt.Errorf("tape: %w", err))
			continue
		}
		r.state = cur
		written++
	}
	for id, r := range w.tapes {
		if !seen[id] {
			errs = append(errs, r.file.Close())
			delete(w.tapes, id)
		}
	}
	return written, errors.Join(errs...)
}

func (w *Writer) open(id int64, at time.Time) (*recording, error) {
	if r, ok := w.tapes[id]; ok {
		return r, nil
	}
	dir := filepath.Join(w.Dir, at.UTC().Format(time.DateOnly))
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("tape: %w", err)
	}
	f, err := os.OpenFile(filepath.Join(dir, fmt.Sprintf("%d.jsonl", id)), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, fmt.Errorf("tape: %w", err)
	}
	r := &recording{file: f}
	w.tapes[id] = r
	return r, nil
}

// Close closes every open tape.
func (w *Writer) Close() error {
	var errs []error
	for id, r := range w.tapes {
		errs = append(errs, r.file.Close())
		delete(w.tapes, id)
	}
	return errors.Join(errs...)
}

// Snapshot is a fixture as it was received at a moment.
type Snapshot struct {
	ReceivedAt time.Time
	FixtureID  int64
	Line       Line            // the line that brought it
	Fixture    json.RawMessage // the whole fixture
}

// Read replays a tape, calling fn with the fixture after each line. Lines
// before the first keyframe are skipped (a tape always starts with one, but
// a damaged tape may not).
func Read(path string, fn func(Snapshot) error) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("tape: %w", err)
	}
	var f *fixture
	for n, b := range bytes.Split(data, []byte("\n")) {
		if len(bytes.TrimSpace(b)) == 0 {
			continue
		}
		var l Line
		if err := json.Unmarshal(b, &l); err != nil {
			return fmt.Errorf("tape: %s line %d: %w", path, n+1, err)
		}
		switch {
		case l.Keyframe != nil:
			raw, _ := json.Marshal(l.Keyframe)
			if f, _, err = parse(raw); err != nil {
				return fmt.Errorf("tape: %s line %d: %w", path, n+1, err)
			}
		case f == nil:
			continue
		default:
			if err := f.apply(l); err != nil {
				return fmt.Errorf("%w (%s line %d)", err, path, n+1)
			}
		}
		if err := fn(Snapshot{ReceivedAt: l.ReceivedAt, FixtureID: l.FixtureID, Line: l, Fixture: f.raw()}); err != nil {
			return err
		}
	}
	return nil
}
