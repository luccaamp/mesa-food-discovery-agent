package main

import (
	"context"
	"net/http"
	"sync"
	"time"
)

// WakingBus publishes like the bus it wraps and then pings the agent worker.
//
// On hosts that put idle services to sleep (Render's free plan), the agent worker
// runs inside a web service that stops after a quiet period. The gateway is woken
// by the incoming webhook, but nothing would wake the worker, so queued messages
// would wait until someone opened the site. A GET on the worker's health URL
// starts it; it then drains the stream. The ping is asynchronous, debounced and
// best-effort: the webhook is still acknowledged in milliseconds.
type WakingBus struct {
	Bus
	URL      string
	Client   *http.Client
	Interval time.Duration // minimum time between pings
	Metrics  *Metrics

	mu   sync.Mutex
	last time.Time
	wg   sync.WaitGroup
}

func NewWakingBus(inner Bus, url string, metrics *Metrics) *WakingBus {
	// A cold start on the free plan takes up to about a minute.
	return &WakingBus{Bus: inner, URL: url, Client: &http.Client{Timeout: 90 * time.Second},
		Interval: 30 * time.Second, Metrics: metrics}
}

func (b *WakingBus) Publish(ctx context.Context, message Inbound) error {
	if err := b.Bus.Publish(ctx, message); err != nil {
		return err
	}
	b.mu.Lock()
	due := time.Since(b.last) >= b.Interval
	if due {
		b.last = time.Now()
	}
	b.mu.Unlock()
	if due {
		b.wg.Add(1)
		go b.ping()
	}
	return nil
}

func (b *WakingBus) ping() {
	defer b.wg.Done()
	response, err := b.Client.Get(b.URL)
	if err != nil {
		b.Metrics.Inc("agent_wake_failed")
		return
	}
	_ = response.Body.Close()
	if response.StatusCode >= 400 {
		b.Metrics.Inc("agent_wake_failed")
		return
	}
	b.Metrics.Inc("agent_wake_sent")
}

// Wait blocks until in-flight pings finish (tests and shutdown).
func (b *WakingBus) Wait() { b.wg.Wait() }
