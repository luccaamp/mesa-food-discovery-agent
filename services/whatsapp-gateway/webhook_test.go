package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

const secret = "test-app-secret"

func sign(body []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}

func fixture(t *testing.T, name string) []byte {
	t.Helper()
	body, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	return body
}

func newGateway() (*Gateway, *MemoryBus) {
	bus := NewMemoryBus()
	return &Gateway{VerifyToken: "verify-me", AppSecret: []byte(secret), Bus: bus, Metrics: NewMetrics(),
		Log: slog.New(slog.NewTextHandler(io.Discard, nil))}, bus
}

func post(g *Gateway, body []byte, signature string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(http.MethodPost, "/webhook", strings.NewReader(string(body)))
	if signature != "" {
		request.Header.Set("X-Hub-Signature-256", signature)
	}
	recorder := httptest.NewRecorder()
	g.ServeHTTP(recorder, request)
	return recorder
}

func TestVerificationHandshake(t *testing.T) {
	g, _ := newGateway()
	cases := []struct {
		query string
		code  int
		body  string
	}{
		{"hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=1158201444", 200, "1158201444"},
		{"hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=1", 403, ""},
		{"hub.mode=unsubscribe&hub.verify_token=verify-me&hub.challenge=1", 403, ""},
	}
	for _, c := range cases {
		recorder := httptest.NewRecorder()
		g.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/webhook?"+c.query, nil))
		if recorder.Code != c.code || (c.body != "" && recorder.Body.String() != c.body) {
			t.Fatalf("%s: got %d %q", c.query, recorder.Code, recorder.Body.String())
		}
	}
	empty := &Gateway{Metrics: NewMetrics()}
	recorder := httptest.NewRecorder()
	empty.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/webhook?hub.mode=subscribe&hub.verify_token=&hub.challenge=1", nil))
	if recorder.Code != 403 {
		t.Fatal("an unset verify token must never match an empty token")
	}
}

func TestSignedTextMessageIsQueuedOnce(t *testing.T) {
	g, bus := newGateway()
	body := fixture(t, "text_message.json")
	for i := 0; i < 2; i++ { // Meta retries deliveries: the second one is a duplicate
		if recorder := post(g, body, sign(body)); recorder.Code != 200 {
			t.Fatalf("attempt %d: status %d", i, recorder.Code)
		}
	}
	if len(bus.Published) != 1 {
		t.Fatalf("published %d, want 1", len(bus.Published))
	}
	got := bus.Published[0]
	if got.Text != "Quero arroz com frango" || got.From != "16505551234" || !strings.HasPrefix(got.MessageID, "wamid.") {
		t.Fatalf("unexpected message %+v", got)
	}
	if g.Metrics.Get("duplicates") != 1 || g.Metrics.Get("published") != 1 {
		t.Fatal("metrics must count the duplicate and the publication")
	}
}

func TestInvalidOrMissingSignatureIsRejectedBeforeParsing(t *testing.T) {
	g, bus := newGateway()
	body := fixture(t, "text_message.json")
	tampered := []byte(strings.Replace(string(body), "frango", "peixe", 1))
	signatures := []string{"", "sha256=00", "sha1=" + strings.TrimPrefix(sign(body), "sha256="), sign(body)}
	for _, signature := range signatures {
		if recorder := post(g, tampered, signature); recorder.Code != http.StatusUnauthorized {
			t.Fatalf("signature %q: status %d", signature, recorder.Code)
		}
	}
	if len(bus.Published) != 0 || g.Metrics.Get("signature_rejected") != 4 {
		t.Fatal("rejected webhooks must not reach the queue")
	}
}

func TestStatusUpdatesAndMediaAreAcknowledgedButNotQueued(t *testing.T) {
	g, bus := newGateway()
	status := fixture(t, "status_update.json")
	if post(g, status, sign(status)).Code != 200 || len(bus.Published) != 0 {
		t.Fatal("delivery statuses carry no user text")
	}
	interactive := fixture(t, "interactive_reply.json")
	if post(g, interactive, sign(interactive)).Code != 200 {
		t.Fatal("interactive payload must be accepted")
	}
	if len(bus.Published) != 1 || bus.Published[0].Text != "Ver mais opções" {
		t.Fatalf("button reply queued as text, image skipped: %+v", bus.Published)
	}
}

func TestOversizedAndForeignPayloads(t *testing.T) {
	g, _ := newGateway()
	big := []byte(strings.Repeat("x", MaxBody+1))
	if post(g, big, sign(big)).Code != http.StatusRequestEntityTooLarge {
		t.Fatal("oversized body must be rejected")
	}
	foreign := []byte(`{"object":"page","entry":[]}`)
	if post(g, foreign, sign(foreign)).Code != http.StatusBadRequest {
		t.Fatal("non-WhatsApp objects must be rejected")
	}
}

func TestQueueFailureAsksMetaToRetry(t *testing.T) {
	g, bus := newGateway()
	bus.Fail = errors.New("redis down")
	body := fixture(t, "text_message.json")
	if post(g, body, sign(body)).Code != http.StatusServiceUnavailable {
		t.Fatal("a queue outage must return 503 so Meta retries the delivery")
	}
}

func TestLongTextIsBounded(t *testing.T) {
	text := strings.Replace(string(fixture(t, "text_message.json")), "Quero arroz com frango", strings.Repeat("a", 900), 1)
	messages, err := ParseMessages([]byte(text))
	if err != nil || len(messages) != 1 || len(messages[0].Text) != 500 {
		t.Fatalf("got %v %v", err, messages)
	}
}

func TestMetricsExposition(t *testing.T) {
	g, _ := newGateway()
	body := fixture(t, "text_message.json")
	post(g, body, sign(body))
	recorder := httptest.NewRecorder()
	g.Metrics.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	text := recorder.Body.String()
	for _, want := range []string{`mesa_gateway_events_total{event="published"} 1`, "mesa_gateway_webhook_seconds_count 1"} {
		if !strings.Contains(text, want) {
			t.Fatalf("missing %q in\n%s", want, text)
		}
	}
}
