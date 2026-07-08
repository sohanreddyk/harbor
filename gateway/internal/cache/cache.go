// Package cache implements Harbor's semantic response cache.
//
// Design (Week 2a): entries live in-process for fast lookup and are
// write-through persisted to Redis for durability across restarts. Similarity
// search is brute-force cosine over the in-memory slice, filtered by namespace
// (model | context-hash | prompt-version). At the cache sizes that matter for a
// single-tenant deployment this beats a network round-trip to a vector index;
// the multi-replica story (shared vector search) is deferred to the Kubernetes
// buffer week and noted in the design doc.
package cache

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"log/slog"
	"math"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	redisIndexKey = "harbor:cache:ids"
	redisEntryPfx = "harbor:cache:entry:"
)

// Entry is a single cached completion.
type Entry struct {
	ID        string    `json:"id"`
	Namespace string    `json:"namespace"`
	Embedding []float32 `json:"embedding,omitempty"` // nil for exact-match entries
	ExactKey  string    `json:"exact_key,omitempty"` // hash of messages when no embedding
	Response  string    `json:"response"`
	Model     string    `json:"model"`
	CreatedAt int64     `json:"created_at"`
	HitCount  int       `json:"hit_count"`
}

// Cache is a namespaced semantic cache with Redis persistence.
type Cache struct {
	mu         sync.RWMutex
	entries    []*Entry
	maxEntries int
	rdb        *redis.Client
	log        *slog.Logger
}

func New(rdb *redis.Client, maxEntries int, log *slog.Logger) *Cache {
	return &Cache{maxEntries: maxEntries, rdb: rdb, log: log}
}

// Load hydrates the in-memory cache from Redis on startup.
func (c *Cache) Load(ctx context.Context) error {
	if c.rdb == nil {
		return nil
	}
	ids, err := c.rdb.SMembers(ctx, redisIndexKey).Result()
	if err != nil || len(ids) == 0 {
		return err
	}
	keys := make([]string, len(ids))
	for i, id := range ids {
		keys[i] = redisEntryPfx + id
	}
	vals, err := c.rdb.MGet(ctx, keys...).Result()
	if err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, v := range vals {
		s, ok := v.(string)
		if !ok {
			continue
		}
		var e Entry
		if json.Unmarshal([]byte(s), &e) == nil {
			c.entries = append(c.entries, &e)
		}
	}
	c.log.Info("cache loaded from redis", "entries", len(c.entries))
	return nil
}

// LookupSemantic returns the best entry in the namespace whose cosine
// similarity to emb is >= threshold, along with that similarity.
func (c *Cache) LookupSemantic(namespace string, emb []float32, threshold float64) (*Entry, float64) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	var best *Entry
	bestSim := threshold
	for _, e := range c.entries {
		if e.Namespace != namespace || len(e.Embedding) == 0 {
			continue
		}
		sim := cosine(emb, e.Embedding)
		if sim >= bestSim {
			bestSim = sim
			best = e
		}
	}
	if best == nil {
		return nil, 0
	}
	return best, bestSim
}

// LookupExact returns an entry matching the exact message hash in a namespace.
func (c *Cache) LookupExact(namespace, exactKey string) *Entry {
	c.mu.RLock()
	defer c.mu.RUnlock()
	for _, e := range c.entries {
		if e.Namespace == namespace && e.ExactKey == exactKey {
			return e
		}
	}
	return nil
}

// Store adds an entry, persists it write-through, and enforces the size cap.
func (c *Cache) Store(ctx context.Context, e *Entry) {
	e.CreatedAt = time.Now().Unix()
	c.mu.Lock()
	c.entries = append(c.entries, e)
	var evicted *Entry
	if len(c.entries) > c.maxEntries {
		evicted = c.entries[0]
		c.entries = c.entries[1:]
	}
	c.mu.Unlock()

	if c.rdb != nil {
		if b, err := json.Marshal(e); err == nil {
			pipe := c.rdb.Pipeline()
			pipe.Set(ctx, redisEntryPfx+e.ID, b, 0)
			pipe.SAdd(ctx, redisIndexKey, e.ID)
			if evicted != nil {
				pipe.Del(ctx, redisEntryPfx+evicted.ID)
				pipe.SRem(ctx, redisIndexKey, evicted.ID)
			}
			if _, err := pipe.Exec(ctx); err != nil {
				c.log.Warn("cache persist failed", "err", err)
			}
		}
	}
}

// Stats returns a snapshot for the /v1/cache/stats endpoint.
func (c *Cache) Stats() map[string]any {
	c.mu.RLock()
	defer c.mu.RUnlock()
	hits := 0
	for _, e := range c.entries {
		hits += e.HitCount
	}
	return map[string]any{"entries": len(c.entries), "total_hits": hits}
}

// TouchHit increments an entry's in-memory hit counter (best-effort).
func (c *Cache) TouchHit(e *Entry) {
	c.mu.Lock()
	e.HitCount++
	c.mu.Unlock()
}

// HashMessages produces a stable key for the exact-match fallback path.
func HashMessages(model string, parts ...string) string {
	h := sha256.New()
	h.Write([]byte(model))
	for _, p := range parts {
		h.Write([]byte{0})
		h.Write([]byte(p))
	}
	return hex.EncodeToString(h.Sum(nil))
}

func cosine(a, b []float32) float64 {
	if len(a) != len(b) || len(a) == 0 {
		return -1
	}
	var dot, na, nb float64
	for i := range a {
		dot += float64(a[i]) * float64(b[i])
		na += float64(a[i]) * float64(a[i])
		nb += float64(b[i]) * float64(b[i])
	}
	if na == 0 || nb == 0 {
		return -1
	}
	return dot / (math.Sqrt(na) * math.Sqrt(nb))
}
