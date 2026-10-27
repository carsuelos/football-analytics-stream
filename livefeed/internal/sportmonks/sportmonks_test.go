package sportmonks

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const token = "secret-token-123"

func server(t *testing.T, h http.HandlerFunc) *Client {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return &Client{BaseURL: srv.URL, Token: token, HTTP: srv.Client()}
}

func TestLivescoresSendsTheTokenInAHeaderOnly(t *testing.T) {
	c := server(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/football/livescores" || r.URL.Query().Get("include") != "participants;events" {
			t.Errorf("request %s", r.URL)
		}
		if r.Header.Get("Authorization") != token || strings.Contains(r.URL.String(), token) {
			t.Errorf("token: header %q, url %s", r.Header.Get("Authorization"), r.URL)
		}
		_, _ = w.Write([]byte(`{"data":[{"id":1,"name":"A vs B"},{"id":2}],"rate_limit":{"resets_in_seconds":3000,"remaining":2999,"requested_entity":"Fixture"}}`))
	})
	fixtures, rl, err := c.Livescores(context.Background(), "participants;events")
	if err != nil {
		t.Fatal(err)
	}
	if len(fixtures) != 2 || !json.Valid(fixtures[0]) || rl == nil || rl.Remaining != 2999 || rl.RequestedEntity != "Fixture" {
		t.Errorf("fixtures %s, rate limit %+v", fixtures, rl)
	}
}

func TestAnErrorReplyCarriesTheAPIsMessage(t *testing.T) {
	c := server(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(`{"message":"You do not have access to the pressure include."}`))
	})
	_, _, err := c.Livescores(context.Background(), "pressure")
	if err == nil || !strings.Contains(err.Error(), "403") || !strings.Contains(err.Error(), "pressure include") || RateLimited(err) {
		t.Errorf("err = %v", err)
	}
}

func TestRateLimited(t *testing.T) {
	c := server(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
	})
	_, _, err := c.Livescores(context.Background(), "")
	if !RateLimited(err) {
		t.Errorf("err = %v", err)
	}
}

func TestTheTokenIsNeverInAConnectionError(t *testing.T) {
	c := &Client{BaseURL: "http://127.0.0.1:1", Token: token, HTTP: http.DefaultClient}
	_, _, err := c.Livescores(context.Background(), "events")
	if err == nil || strings.Contains(err.Error(), token) {
		t.Errorf("err = %v", err)
	}
}

func TestTypesFollowsThePages(t *testing.T) {
	c := server(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Query().Get("page") {
		case "1":
			_, _ = w.Write([]byte(`{"data":[{"id":14,"name":"Goal"}],"pagination":{"has_more":true}}`))
		case "2":
			_, _ = w.Write([]byte(`{"data":[{"id":19,"name":"Yellowcard"}],"pagination":{"has_more":false}}`))
		default:
			t.Errorf("page %q", r.URL.Query().Get("page"))
		}
	})
	types, err := c.Types(context.Background())
	if err != nil || len(types) != 2 {
		t.Errorf("types %s, err %v", types, err)
	}
}
