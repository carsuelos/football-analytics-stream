package main

import (
	"slices"
	"testing"
)

func TestWebhooksFromTheEnvironment(t *testing.T) {
	got, err := parseWebhooks("https://hooks.example/a/SECRET, http://webhook:9000  https://x.test/b")
	if err != nil {
		t.Fatal(err)
	}
	want := urls{"https://hooks.example/a/SECRET", "http://webhook:9000", "https://x.test/b"}
	if !slices.Equal(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
	if hosts := got.hosts(); !slices.Equal(hosts, []string{"https://hooks.example", "http://webhook:9000", "https://x.test"}) {
		t.Errorf("hosts = %v: no paths, which may hold tokens", hosts)
	}
	if _, err := parseWebhooks("ftp://nope"); err == nil {
		t.Error("an ftp:// URL was accepted")
	}
	if got, _ := parseWebhooks(""); len(got) != 0 {
		t.Errorf("empty gave %v", got)
	}
	if v := env([]string{"A=1", "NOTIFIER_WEBHOOKS=http://x=y"}, "NOTIFIER_WEBHOOKS"); v != "http://x=y" {
		t.Errorf("env = %q", v)
	}
}
