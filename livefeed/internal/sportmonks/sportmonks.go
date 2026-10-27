// Package sportmonks reads Sportmonks' Football API v3.
//
// The token goes in the Authorization header, never in the URL, so it can't
// end up in an error message or a log line.
package sportmonks

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
)

// DefaultBaseURL is the API's root.
const DefaultBaseURL = "https://api.sportmonks.com/v3"

// Client reads the API. Set BaseURL, Token and HTTP.
type Client struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

// New returns a client for the real API.
func New(token string, httpClient *http.Client) *Client {
	return &Client{BaseURL: DefaultBaseURL, Token: token, HTTP: httpClient}
}

// RateLimit is what's left of the hour's calls for the entity a request used.
type RateLimit struct {
	ResetsInSeconds int    `json:"resets_in_seconds"`
	Remaining       int    `json:"remaining"`
	RequestedEntity string `json:"requested_entity"`
}

// Error is an error reply from the API.
type Error struct {
	Status  int
	Message string
}

func (e *Error) Error() string {
	return fmt.Sprintf("sportmonks: HTTP %d: %s", e.Status, e.Message)
}

// RateLimited reports whether err is the API saying the hour's calls are used up.
func RateLimited(err error) bool {
	var e *Error
	return errors.As(err, &e) && e.Status == http.StatusTooManyRequests
}

// Livescores returns every fixture from 15 minutes before kick-off to 15
// minutes after full time, as the API sent each one, with includes (e.g.
// "participants;events"). The endpoint isn't paginated: one call has them all.
func (c *Client) Livescores(ctx context.Context, includes string) ([]json.RawMessage, *RateLimit, error) {
	q := url.Values{}
	if includes != "" {
		q.Set("include", includes)
	}
	var reply struct {
		Data      []json.RawMessage `json:"data"`
		RateLimit *RateLimit        `json:"rate_limit"`
	}
	if err := c.get(ctx, "/football/livescores", q, &reply); err != nil {
		return nil, nil, err
	}
	return reply.Data, reply.RateLimit, nil
}

// FixturesBetween returns every fixture on the plan that kicks off from one
// date to another (YYYY-MM-DD, at most 100 days apart), with includes, every page.
func (c *Client) FixturesBetween(ctx context.Context, from, to, includes string) ([]json.RawMessage, error) {
	var all []json.RawMessage
	for page := 1; page <= 100; page++ {
		var reply struct {
			Data       []json.RawMessage `json:"data"`
			Pagination struct {
				HasMore bool `json:"has_more"`
			} `json:"pagination"`
		}
		q := url.Values{"page": {strconv.Itoa(page)}, "per_page": {"50"}}
		if includes != "" {
			q.Set("include", includes)
		}
		if err := c.get(ctx, "/football/fixtures/between/"+url.PathEscape(from)+"/"+url.PathEscape(to), q, &reply); err != nil {
			return nil, err
		}
		all = append(all, reply.Data...)
		if !reply.Pagination.HasMore {
			return all, nil
		}
	}
	return nil, errors.New("sportmonks: fixtures: more than 100 pages")
}

// Types returns the whole type catalogue (what each type_id means), every page.
func (c *Client) Types(ctx context.Context) ([]json.RawMessage, error) {
	var all []json.RawMessage
	for page := 1; page <= 100; page++ {
		var reply struct {
			Data       []json.RawMessage `json:"data"`
			Pagination struct {
				HasMore bool `json:"has_more"`
			} `json:"pagination"`
		}
		q := url.Values{"page": {strconv.Itoa(page)}, "per_page": {"50"}}
		if err := c.get(ctx, "/core/types", q, &reply); err != nil {
			return nil, err
		}
		all = append(all, reply.Data...)
		if !reply.Pagination.HasMore {
			return all, nil
		}
	}
	return nil, errors.New("sportmonks: types: more than 100 pages")
}

func (c *Client) get(ctx context.Context, path string, q url.Values, into any) error {
	u := c.BaseURL + path
	if len(q) > 0 {
		u += "?" + q.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return fmt.Errorf("sportmonks: %w", err)
	}
	req.Header.Set("Authorization", c.Token)
	req.Header.Set("Accept", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("sportmonks: %s: %w", path, unwrapURL(err))
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if err != nil {
		return fmt.Errorf("sportmonks: %s: reading the reply: %w", path, err)
	}
	if resp.StatusCode != http.StatusOK {
		var e struct {
			Message string `json:"message"`
		}
		if json.Unmarshal(body, &e) != nil || e.Message == "" {
			e.Message = http.StatusText(resp.StatusCode)
		}
		return &Error{Status: resp.StatusCode, Message: e.Message}
	}
	if err := json.Unmarshal(body, into); err != nil {
		return fmt.Errorf("sportmonks: %s: %w", path, err)
	}
	return nil
}

// unwrapURL drops the URL that *url.Error puts in its message.
func unwrapURL(err error) error {
	var ue *url.Error
	if errors.As(err, &ue) {
		return ue.Err
	}
	return err
}
