package main

import (
	"fmt"
	"net/http"
	"sort"
	"sync"
	"time"
)

// Metrics exposes counters and a latency histogram in Prometheus text format.
type Metrics struct {
	mu       sync.Mutex
	counters map[string]uint64
	buckets  []float64
	counts   []uint64
	sum      float64
	total    uint64
}

func NewMetrics() *Metrics {
	buckets := []float64{0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1}
	return &Metrics{counters: map[string]uint64{}, buckets: buckets, counts: make([]uint64, len(buckets))}
}

func (m *Metrics) Inc(name string) {
	m.mu.Lock()
	m.counters[name]++
	m.mu.Unlock()
}

func (m *Metrics) Get(name string) uint64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.counters[name]
}

func (m *Metrics) Observe(elapsed time.Duration) {
	seconds := elapsed.Seconds()
	m.mu.Lock()
	defer m.mu.Unlock()
	for i, bound := range m.buckets {
		if seconds <= bound {
			m.counts[i]++
		}
	}
	m.sum += seconds
	m.total++
}

func (m *Metrics) ServeHTTP(w http.ResponseWriter, _ *http.Request) {
	m.mu.Lock()
	defer m.mu.Unlock()
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	names := make([]string, 0, len(m.counters))
	for name := range m.counters {
		names = append(names, name)
	}
	sort.Strings(names)
	fmt.Fprintln(w, "# TYPE mesa_gateway_events_total counter")
	for _, name := range names {
		fmt.Fprintf(w, "mesa_gateway_events_total{event=%q} %d\n", name, m.counters[name])
	}
	fmt.Fprintln(w, "# TYPE mesa_gateway_webhook_seconds histogram")
	for i, bound := range m.buckets {
		fmt.Fprintf(w, "mesa_gateway_webhook_seconds_bucket{le=\"%g\"} %d\n", bound, m.counts[i])
	}
	fmt.Fprintf(w, "mesa_gateway_webhook_seconds_bucket{le=\"+Inf\"} %d\n", m.total)
	fmt.Fprintf(w, "mesa_gateway_webhook_seconds_sum %g\n", m.sum)
	fmt.Fprintf(w, "mesa_gateway_webhook_seconds_count %d\n", m.total)
}
