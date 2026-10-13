// Package kafka publishes the broadcast to a Kafka topic, as a second transport
// beside the WebSocket feed.
//
// Every feed message goes to the topic as JSON, in feed order, keyed by
// match_id: a match_start when a match is loaded, its events as they are
// broadcast, and a match_end. The topic is a log of every match broadcast, so a
// consumer finds the current match by its latest match_start and reads it from
// there.
//
// The client is confluent-kafka-go (librdkafka). It uses only the plain Kafka
// protocol, so the same code works against Redpanda locally and Azure Event Hubs
// in the cloud; only the configuration differs (see ConfigFromEnv).
package kafka

import (
	"context"
	"encoding/json"
	"errors"
	"strconv"

	"github.com/carsuelos/football-analytics-stream/simulator/internal/schema"
)

// Feed is a stream of feed messages, such as a broadcast.Subscription.
type Feed interface {
	Next(ctx context.Context) (schema.FeedMessage, error)
}

// Writer queues a message for the topic. It blocks while its queue is full.
type Writer interface {
	Write(ctx context.Context, key, value []byte) error
}

// Publish writes every message from feed to w until ctx is done, when it
// returns nil. Subscribe the feed from offset 0, so every match is published
// from its start.
func Publish(ctx context.Context, feed Feed, w Writer) error {
	for {
		msg, err := feed.Next(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		key, value, err := encode(msg)
		if err != nil {
			return err
		}
		if err := w.Write(ctx, key, value); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
	}
}

// encode returns msg as a Kafka key (its match_id) and value (its JSON).
//
// A match_start's head is dropped. On the WebSocket feed it tells one
// subscriber how much it missed before it connected; on the topic every
// consumer reads from its own position, and works out its own catch-up.
func encode(msg schema.FeedMessage) (key, value []byte, err error) {
	var matchID int
	switch {
	case msg.Event != nil:
		matchID = int(msg.Event.MatchID)
	case msg.Marker != nil:
		marker := *msg.Marker
		marker.Head = nil
		msg.Marker = &marker
		matchID = int(marker.MatchID)
	default:
		return nil, nil, errors.New("feed message with neither an event nor a marker")
	}
	value, err = json.Marshal(msg)
	if err != nil {
		return nil, nil, err
	}
	return []byte(strconv.Itoa(matchID)), value, nil
}
