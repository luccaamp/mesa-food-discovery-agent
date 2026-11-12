package main

import (
	"crypto/subtle"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// TelegramGateway receives Telegram Bot API webhooks. Telegram authenticates
// each delivery with the secret_token chosen in setWebhook, sent back in the
// X-Telegram-Bot-Api-Secret-Token header.
type TelegramGateway struct {
	Secret  string
	Bus     Bus
	Metrics *Metrics
	Log     *slog.Logger
}

type telegramUpdate struct {
	UpdateID int64 `json:"update_id"`
	Message  *struct {
		Date int64  `json:"date"`
		Text string `json:"text"`
		Chat struct {
			ID   int64  `json:"id"`
			Type string `json:"type"`
		} `json:"chat"`
	} `json:"message"`
}

// ParseTelegram extracts a private-chat text message from an update.
// Group chats, edits, stickers and other update types are ignored.
func ParseTelegram(body []byte) (*Inbound, error) {
	var update telegramUpdate
	if err := json.Unmarshal(body, &update); err != nil {
		return nil, err
	}
	if update.Message == nil || update.Message.Chat.Type != "private" {
		return nil, nil
	}
	text := strings.TrimSpace(update.Message.Text)
	if text == "" {
		return nil, nil
	}
	if len(text) > 500 {
		text = text[:500]
	}
	return &Inbound{
		Channel:   "telegram",
		MessageID: "tg:" + strconv.FormatInt(update.UpdateID, 10),
		From:      strconv.FormatInt(update.Message.Chat.ID, 10),
		Text:      text,
		Timestamp: strconv.FormatInt(update.Message.Date, 10),
	}, nil
}

func (g *TelegramGateway) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "POST")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	started := time.Now()
	if g.Secret == "" || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-Telegram-Bot-Api-Secret-Token")), []byte(g.Secret)) != 1 {
		g.Metrics.Inc("telegram_secret_rejected")
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, MaxBody+1))
	if err != nil || len(body) > MaxBody {
		g.Metrics.Inc("body_rejected")
		http.Error(w, "payload too large", http.StatusRequestEntityTooLarge)
		return
	}
	message, err := ParseTelegram(body)
	if err != nil {
		g.Metrics.Inc("payload_rejected")
		http.Error(w, "invalid payload", http.StatusBadRequest)
		return
	}
	if message != nil {
		fresh, err := g.Bus.FirstSeen(r.Context(), message.MessageID)
		if err != nil {
			g.Metrics.Inc("bus_errors")
			g.Log.Error("dedupe_failed", "error", err.Error())
			http.Error(w, "temporarily unavailable", http.StatusServiceUnavailable) // Telegram retries
			return
		}
		if !fresh {
			g.Metrics.Inc("duplicates")
		} else if err := g.Bus.Publish(r.Context(), *message); err != nil {
			g.Metrics.Inc("bus_errors")
			g.Log.Error("publish_failed", "error", err.Error())
			http.Error(w, "temporarily unavailable", http.StatusServiceUnavailable)
			return
		} else {
			g.Metrics.Inc("telegram_published")
		}
	}
	g.Metrics.Inc("telegram_accepted")
	g.Metrics.Observe(time.Since(started))
	w.WriteHeader(http.StatusOK)
}
