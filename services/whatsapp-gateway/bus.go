package main

import (
	"context"
	"encoding/json"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	StreamKey  = "mesa:inbound"
	DedupeTTL  = 24 * time.Hour
	StreamMax  = 1000 // bounded retention: processed entries are also deleted by the worker
	dedupeKeyF = "mesa:seen:"
)

// RedisBus uses SET NX for idempotency and a Redis Stream as the queue.
type RedisBus struct {
	Client *redis.Client
}

func (b *RedisBus) FirstSeen(ctx context.Context, messageID string) (bool, error) {
	return b.Client.SetNX(ctx, dedupeKeyF+messageID, 1, DedupeTTL).Result()
}

func (b *RedisBus) Publish(ctx context.Context, message Inbound) error {
	payload, err := json.Marshal(message)
	if err != nil {
		return err
	}
	return b.Client.XAdd(ctx, &redis.XAddArgs{
		Stream: StreamKey,
		MaxLen: StreamMax,
		Approx: true,
		Values: map[string]any{"payload": payload},
	}).Err()
}

// MemoryBus is used in tests and for running the gateway without Redis.
type MemoryBus struct {
	mu        sync.Mutex
	seen      map[string]time.Time
	Published []Inbound
	Fail      error
}

func NewMemoryBus() *MemoryBus {
	return &MemoryBus{seen: map[string]time.Time{}}
}

func (b *MemoryBus) FirstSeen(_ context.Context, messageID string) (bool, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.Fail != nil {
		return false, b.Fail
	}
	now := time.Now()
	for id, at := range b.seen {
		if now.Sub(at) > DedupeTTL {
			delete(b.seen, id)
		}
	}
	if _, ok := b.seen[messageID]; ok {
		return false, nil
	}
	b.seen[messageID] = now
	return true, nil
}

func (b *MemoryBus) Publish(_ context.Context, message Inbound) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.Fail != nil {
		return b.Fail
	}
	b.Published = append(b.Published, message)
	return nil
}
