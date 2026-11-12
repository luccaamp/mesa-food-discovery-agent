package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"
)

// MaxBody bounds what we read from Meta before verifying the signature.
const MaxBody = 1 << 20

// Inbound is the minimal event handed to the agent worker. The phone number is
// needed to reply; it is never logged and leaves the queue once processed.
type Inbound struct {
	Channel   string `json:"channel"`
	MessageID string `json:"message_id"`
	From      string `json:"from"`
	Text      string `json:"text"`
	Timestamp string `json:"timestamp"`
}

// Bus publishes inbound messages and remembers which IDs were already accepted.
type Bus interface {
	// FirstSeen atomically records the ID and reports whether it was new.
	FirstSeen(ctx context.Context, messageID string) (bool, error)
	Publish(ctx context.Context, message Inbound) error
}

type Gateway struct {
	VerifyToken string
	AppSecret   []byte
	Bus         Bus
	Metrics     *Metrics
	Log         *slog.Logger
}

// ServeHTTP implements the WhatsApp Cloud API webhook contract.
func (g *Gateway) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		g.verify(w, r)
	case http.MethodPost:
		g.receive(w, r)
	default:
		w.Header().Set("Allow", "GET, POST")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

// verify answers Meta's subscription handshake.
func (g *Gateway) verify(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query()
	token := query.Get("hub.verify_token")
	if query.Get("hub.mode") != "subscribe" || g.VerifyToken == "" ||
		subtle.ConstantTimeCompare([]byte(token), []byte(g.VerifyToken)) != 1 {
		g.Metrics.Inc("verification_rejected")
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	g.Metrics.Inc("verification_accepted")
	w.Header().Set("Content-Type", "text/plain")
	_, _ = io.WriteString(w, query.Get("hub.challenge"))
}

func (g *Gateway) receive(w http.ResponseWriter, r *http.Request) {
	started := time.Now()
	body, err := io.ReadAll(io.LimitReader(r.Body, MaxBody+1))
	if err != nil || len(body) > MaxBody {
		g.Metrics.Inc("body_rejected")
		http.Error(w, "payload too large", http.StatusRequestEntityTooLarge)
		return
	}
	if !ValidSignature(g.AppSecret, body, r.Header.Get("X-Hub-Signature-256")) {
		g.Metrics.Inc("signature_rejected")
		http.Error(w, "invalid signature", http.StatusUnauthorized)
		return
	}
	messages, err := ParseMessages(body)
	if err != nil {
		g.Metrics.Inc("payload_rejected")
		http.Error(w, "invalid payload", http.StatusBadRequest)
		return
	}
	for _, message := range messages {
		fresh, err := g.Bus.FirstSeen(r.Context(), message.MessageID)
		if err != nil {
			// Ask Meta to retry later instead of silently dropping the message.
			g.Metrics.Inc("bus_errors")
			g.Log.Error("dedupe_failed", "error", err.Error())
			http.Error(w, "temporarily unavailable", http.StatusServiceUnavailable)
			return
		}
		if !fresh {
			g.Metrics.Inc("duplicates")
			continue
		}
		if err := g.Bus.Publish(r.Context(), message); err != nil {
			g.Metrics.Inc("bus_errors")
			g.Log.Error("publish_failed", "error", err.Error())
			http.Error(w, "temporarily unavailable", http.StatusServiceUnavailable)
			return
		}
		g.Metrics.Inc("published")
	}
	g.Metrics.Inc("webhooks_accepted")
	g.Metrics.Observe(time.Since(started))
	w.WriteHeader(http.StatusOK)
}

// ValidSignature checks Meta's X-Hub-Signature-256 (HMAC-SHA256 of the raw body
// with the app secret) in constant time.
func ValidSignature(secret, body []byte, header string) bool {
	if len(secret) == 0 || !strings.HasPrefix(header, "sha256=") {
		return false
	}
	received, err := hex.DecodeString(strings.TrimPrefix(header, "sha256="))
	if err != nil {
		return false
	}
	mac := hmac.New(sha256.New, secret)
	mac.Write(body)
	return hmac.Equal(received, mac.Sum(nil))
}

type webhookPayload struct {
	Object string `json:"object"`
	Entry  []struct {
		Changes []struct {
			Field string `json:"field"`
			Value struct {
				Messages []struct {
					ID        string `json:"id"`
					From      string `json:"from"`
					Timestamp string `json:"timestamp"`
					Type      string `json:"type"`
					Text      *struct {
						Body string `json:"body"`
					} `json:"text"`
					Interactive *struct {
						Type        string `json:"type"`
						ButtonReply *struct {
							Title string `json:"title"`
						} `json:"button_reply"`
						ListReply *struct {
							Title string `json:"title"`
						} `json:"list_reply"`
					} `json:"interactive"`
				} `json:"messages"`
			} `json:"value"`
		} `json:"changes"`
	} `json:"entry"`
}

var ErrNotWhatsApp = errors.New("not a whatsapp_business_account payload")

// ParseMessages extracts user text from a webhook. Status updates (sent,
// delivered, read) and unsupported media carry no text and are skipped.
func ParseMessages(body []byte) ([]Inbound, error) {
	var payload webhookPayload
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, err
	}
	if payload.Object != "whatsapp_business_account" {
		return nil, ErrNotWhatsApp
	}
	var out []Inbound
	for _, entry := range payload.Entry {
		for _, change := range entry.Changes {
			if change.Field != "messages" {
				continue
			}
			for _, message := range change.Value.Messages {
				text := ""
				switch {
				case message.Type == "text" && message.Text != nil:
					text = message.Text.Body
				case message.Type == "interactive" && message.Interactive != nil && message.Interactive.ButtonReply != nil:
					text = message.Interactive.ButtonReply.Title
				case message.Type == "interactive" && message.Interactive != nil && message.Interactive.ListReply != nil:
					text = message.Interactive.ListReply.Title
				}
				text = strings.TrimSpace(text)
				if message.ID == "" || message.From == "" || text == "" {
					continue
				}
				if len(text) > 500 {
					text = text[:500]
				}
				out = append(out, Inbound{Channel: "whatsapp", MessageID: message.ID, From: message.From, Text: text, Timestamp: message.Timestamp})
			}
		}
	}
	return out, nil
}
