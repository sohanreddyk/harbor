// Package ratelimit implements a distributed token-bucket limiter backed by
// Redis. The refill-and-consume operation must be atomic across concurrent
// gateway workers (and replicas), so it runs as a single Lua script inside
// Redis — one round trip, no read-modify-write races.
package ratelimit

import (
	"context"

	"github.com/redis/go-redis/v9"
)

// tokenBucket refills `rate` tokens/sec up to `burst`, then tries to consume
// `requested`. State (tokens, last-refill timestamp in ms) lives in a hash and
// is given a TTL so idle buckets are reclaimed. Returns 1 if allowed, else 0.
var tokenBucket = redis.NewScript(`
local key       = KEYS[1]
local rate      = tonumber(ARGV[1])
local burst     = tonumber(ARGV[2])
local now_ms    = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local state = redis.call("HMGET", key, "tokens", "ts")
local tokens = tonumber(state[1])
local ts     = tonumber(state[2])
if tokens == nil then
  tokens = burst
  ts = now_ms
end

local elapsed = math.max(0, now_ms - ts) / 1000.0
tokens = math.min(burst, tokens + elapsed * rate)

local allowed = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
end

redis.call("HSET", key, "tokens", tokens, "ts", now_ms)
-- reclaim idle buckets: time to fully refill, min 60s
local ttl = math.max(60, math.ceil(burst / rate))
redis.call("EXPIRE", key, ttl)
return allowed
`)

// Limiter enforces a token-bucket policy per key.
type Limiter struct {
	rdb   *redis.Client
	rate  float64
	burst float64
}

func New(rdb *redis.Client, rate, burst float64) *Limiter {
	return &Limiter{rdb: rdb, rate: rate, burst: burst}
}

// Allow reports whether a single request for `key` may proceed. Fails open: if
// Redis is unavailable the request is allowed rather than dropped, since the
// limiter must never be a single point of failure for the data plane.
func (l *Limiter) Allow(ctx context.Context, key string, nowMillis int64) bool {
	if l.rdb == nil {
		return true
	}
	res, err := tokenBucket.Run(ctx, l.rdb,
		[]string{"harbor:rl:" + key},
		l.rate, l.burst, nowMillis, 1,
	).Int()
	if err != nil {
		return true // fail open
	}
	return res == 1
}
