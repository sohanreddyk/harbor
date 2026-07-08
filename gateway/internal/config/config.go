package config

import (
	"os"
	"strconv"
	"time"
)

// Config holds all runtime configuration for the Harbor gateway.
type Config struct {
	Port           string
	Provider       string // "mock" | "openai"
	OpenAIBaseURL  string
	OpenAIAPIKey   string
	PrimaryModel   string
	RequestTimeout time.Duration

	// --- Week 2a: cache + rate limiting ---
	RedisURL string

	// Semantic cache. Threshold is cosine similarity in [0,1]; a lookup is a
	// hit when the best matching entry scores >= CacheThreshold.
	CacheEnabled   bool
	CacheThreshold float64
	CacheMaxEntries int
	// ReplayPacing simulates streaming on a cache hit. 0 = flush instantly.
	CacheReplayPacing time.Duration

	// Token-bucket rate limiting (Redis + Lua). Generous defaults so normal
	// demos aren't throttled; lower them to observe 429s.
	RateLimitEnabled bool
	RateLimitRPS     float64
	RateLimitBurst   float64

	// Simulated per-token latency for the mock provider. Raise it to emulate
	// real inference latency and make the cache latency win visible in benchmarks.
	MockTokenDelay time.Duration

	// --- Week 2b: routing, fallback, circuit breaker ---
	CheapModel          string
	StrongModel         string
	RouteTokenThreshold int
	// Fraction of primary-provider calls to fail on purpose (0..1), for
	// demonstrating fallback and the circuit breaker without a real outage.
	PrimaryFaultRate float64
	BreakerThreshold int
	BreakerCooldown  time.Duration

	// Price used for estimated cost / cost-saved metrics.
	CostPer1kTokens float64
}

func FromEnv() Config {
	return Config{
		Port:              getenv("GATEWAY_PORT", "8080"),
		Provider:          getenv("PROVIDER", "mock"),
		OpenAIBaseURL:     getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
		OpenAIAPIKey:      getenv("OPENAI_API_KEY", ""),
		PrimaryModel:      getenv("PRIMARY_MODEL", "gpt-4o-mini"),
		RequestTimeout:    time.Duration(getenvInt("REQUEST_TIMEOUT_SECONDS", 60)) * time.Second,
		RedisURL:          getenv("REDIS_URL", "redis://redis:6379"),
		CacheEnabled:      getenvBool("CACHE_ENABLED", true),
		CacheThreshold:    getenvFloat("CACHE_THRESHOLD", 0.92),
		CacheMaxEntries:   getenvInt("CACHE_MAX_ENTRIES", 5000),
		CacheReplayPacing: time.Duration(getenvInt("CACHE_REPLAY_PACING_MS", 3)) * time.Millisecond,
		RateLimitEnabled:  getenvBool("RATE_LIMIT_ENABLED", true),
		RateLimitRPS:      getenvFloat("RATE_LIMIT_RPS", 1000),
		RateLimitBurst:    getenvFloat("RATE_LIMIT_BURST", 2000),
		MockTokenDelay:    time.Duration(getenvInt("MOCK_TOKEN_DELAY_MS", 12)) * time.Millisecond,
		CheapModel:          getenv("CHEAP_MODEL", "harbor-small"),
		StrongModel:         getenv("STRONG_MODEL", "harbor-large"),
		RouteTokenThreshold: getenvInt("ROUTE_TOKEN_THRESHOLD", 400),
		PrimaryFaultRate:    getenvFloat("PRIMARY_FAULT_RATE", 0),
		BreakerThreshold:    getenvInt("BREAKER_THRESHOLD", 5),
		BreakerCooldown:     time.Duration(getenvInt("BREAKER_COOLDOWN_SECONDS", 15)) * time.Second,
		CostPer1kTokens:     getenvFloat("COST_PER_1K_TOKENS", 0.15),
	}
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getenvInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}

func getenvFloat(key string, fallback float64) float64 {
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return fallback
}

func getenvBool(key string, fallback bool) bool {
	if v := os.Getenv(key); v != "" {
		if b, err := strconv.ParseBool(v); err == nil {
			return b
		}
	}
	return fallback
}
