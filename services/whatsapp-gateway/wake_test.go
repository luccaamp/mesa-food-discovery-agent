package main

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestWakingBusPingsAgentOnceWithinInterval(t *testing.T) {
	var hits atomic.Int32
	agent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { hits.Add(1) }))
	defer agent.Close()
	inner, metrics := NewMemoryBus(), NewMetrics()
	bus := NewWakingBus(inner, agent.URL+"/ready", metrics)

	for _, id := range []string{"a", "b", "c"} {
		if err := bus.Publish(context.Background(), Inbound{MessageID: id}); err != nil {
			t.Fatal(err)
		}
	}
	bus.Wait()
	if len(inner.Published) != 3 {
		t.Fatalf("published %d, want 3", len(inner.Published))
	}
	if hits.Load() != 1 || metrics.Get("agent_wake_sent") != 1 {
		t.Fatalf("pings %d, metric %d, want 1 debounced ping", hits.Load(), metrics.Get("agent_wake_sent"))
	}

	bus.Interval = 0
	_ = bus.Publish(context.Background(), Inbound{MessageID: "d"})
	bus.Wait()
	if hits.Load() != 2 {
		t.Fatalf("pings %d after interval elapsed, want 2", hits.Load())
	}
}

func TestWakingBusDoesNotPingWhenPublishFails(t *testing.T) {
	var hits atomic.Int32
	agent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { hits.Add(1) }))
	defer agent.Close()
	inner := NewMemoryBus()
	inner.Fail = errors.New("redis down")
	bus := NewWakingBus(inner, agent.URL, NewMetrics())

	if err := bus.Publish(context.Background(), Inbound{MessageID: "a"}); err == nil {
		t.Fatal("expected the publish error to propagate")
	}
	bus.Wait()
	if hits.Load() != 0 {
		t.Fatal("must not wake the agent for a message that was not queued")
	}
}

func TestWakingBusCountsFailedPingsWithoutFailingPublish(t *testing.T) {
	agent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer agent.Close()
	metrics := NewMetrics()
	bus := NewWakingBus(NewMemoryBus(), agent.URL, metrics)
	bus.Client.Timeout = time.Second

	if err := bus.Publish(context.Background(), Inbound{MessageID: "a"}); err != nil {
		t.Fatal(err)
	}
	bus.Wait()
	if metrics.Get("agent_wake_failed") != 1 {
		t.Fatalf("agent_wake_failed = %d, want 1", metrics.Get("agent_wake_failed"))
	}
}
