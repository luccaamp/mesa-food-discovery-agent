package main

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const telegramUpdateJSON = `{"update_id": 902345611, "message": {"message_id": 17, "date": 1794441000,
  "from": {"id": 5551234, "is_bot": false, "first_name": "Ana"},
  "chat": {"id": 5551234, "type": "private"}, "text": "Quero arroz com frango"}}`

func newTelegram() (*TelegramGateway, *MemoryBus) {
	bus := NewMemoryBus()
	return &TelegramGateway{Secret: "tg-secret", Bus: bus, Metrics: NewMetrics(),
		Log: slog.New(slog.NewTextHandler(io.Discard, nil))}, bus
}

func postTelegram(g *TelegramGateway, body, secret string) int {
	request := httptest.NewRequest(http.MethodPost, "/telegram", strings.NewReader(body))
	if secret != "" {
		request.Header.Set("X-Telegram-Bot-Api-Secret-Token", secret)
	}
	recorder := httptest.NewRecorder()
	g.ServeHTTP(recorder, request)
	return recorder.Code
}

func TestTelegramUpdateIsQueuedOnceWithChannel(t *testing.T) {
	g, bus := newTelegram()
	for i := 0; i < 2; i++ {
		if code := postTelegram(g, telegramUpdateJSON, "tg-secret"); code != 200 {
			t.Fatalf("status %d", code)
		}
	}
	if len(bus.Published) != 1 {
		t.Fatalf("published %d, want 1 (retries are de-duplicated by update_id)", len(bus.Published))
	}
	got := bus.Published[0]
	if got.Channel != "telegram" || got.From != "5551234" || got.MessageID != "tg:902345611" || got.Text != "Quero arroz com frango" {
		t.Fatalf("unexpected message %+v", got)
	}
}

func TestTelegramSecretIsRequired(t *testing.T) {
	g, bus := newTelegram()
	for _, secret := range []string{"", "wrong"} {
		if postTelegram(g, telegramUpdateJSON, secret) != http.StatusUnauthorized {
			t.Fatalf("secret %q must be rejected", secret)
		}
	}
	unset := &TelegramGateway{Bus: bus, Metrics: NewMetrics(), Log: g.Log}
	if postTelegram(unset, telegramUpdateJSON, "") != http.StatusUnauthorized {
		t.Fatal("an unset secret must never accept requests")
	}
	if len(bus.Published) != 0 {
		t.Fatal("rejected updates must not reach the queue")
	}
}

func TestTelegramIgnoresGroupsAndNonText(t *testing.T) {
	g, bus := newTelegram()
	group := strings.Replace(telegramUpdateJSON, `"private"`, `"group"`, 1)
	sticker := `{"update_id": 5, "message": {"message_id": 1, "date": 1, "chat": {"id": 1, "type": "private"}, "sticker": {}}}`
	edited := `{"update_id": 6, "edited_message": {"text": "x"}}`
	for _, body := range []string{group, sticker, edited} {
		if postTelegram(g, body, "tg-secret") != 200 {
			t.Fatal("ignored updates are still acknowledged so Telegram does not retry")
		}
	}
	if len(bus.Published) != 0 {
		t.Fatalf("nothing should be queued: %+v", bus.Published)
	}
	if postTelegram(g, "{not json", "tg-secret") != http.StatusBadRequest {
		t.Fatal("malformed JSON must be rejected")
	}
}
