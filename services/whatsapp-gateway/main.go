// Command whatsapp-gateway receives WhatsApp Cloud API webhooks, verifies
// them, de-duplicates them and queues them for the Mesa agent worker.
//
// It answers Meta in milliseconds and never calls the language model itself:
// the slow work happens asynchronously behind a Redis Stream.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	port := envOr("PORT", "8090")
	metrics := NewMetrics()

	var bus Bus
	if url := os.Getenv("REDIS_URL"); url != "" {
		options, err := redis.ParseURL(url)
		if err != nil {
			log.Error("invalid_redis_url")
			os.Exit(1)
		}
		bus = &RedisBus{Client: redis.NewClient(options)}
	} else {
		log.Warn("redis_not_configured_using_memory_bus")
		bus = NewMemoryBus()
	}

	gateway := &Gateway{
		VerifyToken: os.Getenv("WHATSAPP_VERIFY_TOKEN"),
		AppSecret:   []byte(os.Getenv("WHATSAPP_APP_SECRET")),
		Bus:         bus,
		Metrics:     metrics,
		Log:         log,
	}
	if gateway.VerifyToken == "" || len(gateway.AppSecret) == 0 {
		log.Warn("whatsapp_secrets_missing_webhooks_will_be_rejected")
	}

	mux := http.NewServeMux()
	mux.Handle("/webhook", gateway)
	mux.Handle("/metrics", metrics)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})

	server := &http.Server{
		Addr:              ":" + port,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		log.Info("listening", "port", port)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("server_failed", "error", err.Error())
			stop()
		}
	}()
	<-ctx.Done()
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdown)
	log.Info("stopped")
}

func envOr(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
