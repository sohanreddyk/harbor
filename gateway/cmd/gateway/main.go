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

	"github.com/sohanreddy/harbor/gateway/internal/breaker"
	"github.com/sohanreddy/harbor/gateway/internal/cache"
	"github.com/sohanreddy/harbor/gateway/internal/config"
	"github.com/sohanreddy/harbor/gateway/internal/dispatch"
	"github.com/sohanreddy/harbor/gateway/internal/metrics"
	"github.com/sohanreddy/harbor/gateway/internal/provider"
	"github.com/sohanreddy/harbor/gateway/internal/ratelimit"
	"github.com/sohanreddy/harbor/gateway/internal/router"
	"github.com/sohanreddy/harbor/gateway/internal/server"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	cfg := config.FromEnv()

	rdb := connectRedis(cfg.RedisURL, log)

	c := cache.New(rdb, cfg.CacheMaxEntries, log)
	if err := c.Load(context.Background()); err != nil {
		log.Warn("cache load failed (continuing empty)", "err", err)
	}
	limiter := ratelimit.New(rdb, cfg.RateLimitRPS, cfg.RateLimitBurst)

	chain := buildChain(cfg)
	rtr := router.New(cfg.CheapModel, cfg.StrongModel, cfg.RouteTokenThreshold)
	m := metrics.New()

	log.Info("starting harbor gateway",
		"port", cfg.Port, "provider", cfg.Provider, "cache_enabled", cfg.CacheEnabled,
		"cache_threshold", cfg.CacheThreshold, "rate_limit_enabled", cfg.RateLimitEnabled,
		"primary_fault_rate", cfg.PrimaryFaultRate)

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           server.New(cfg, chain, rtr, c, limiter, m, log).Routes(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("server error", "err", err)
			os.Exit(1)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	log.Info("shutting down")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}

func connectRedis(url string, log *slog.Logger) *redis.Client {
	opt, err := redis.ParseURL(url)
	if err != nil {
		log.Warn("invalid REDIS_URL; cache persistence and rate limiting disabled", "err", err)
		return nil
	}
	rdb := redis.NewClient(opt)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Warn("redis unreachable at startup (will fail open)", "err", err)
	}
	return rdb
}

// buildChain assembles the fallback chain: a primary provider (optionally wrapped
// with fault injection for demos) followed by a healthy local mock as a
// graceful-degradation fallback. Each backend gets its own circuit breaker.
func buildChain(cfg config.Config) *dispatch.Chain {
	primaryBase := buildProvider(cfg)
	var primary provider.Provider = primaryBase
	if cfg.PrimaryFaultRate > 0 {
		primary = provider.NewFaulty(primaryBase, cfg.PrimaryFaultRate)
	}
	fallback := provider.NewMock(cfg.MockTokenDelay)

	return dispatch.New([]dispatch.Backend{
		{Name: primaryBase.Name(), Prov: primary, Breaker: breaker.New(cfg.BreakerThreshold, cfg.BreakerCooldown)},
		{Name: "mock-fallback", Prov: fallback, Breaker: breaker.New(cfg.BreakerThreshold, cfg.BreakerCooldown)},
	})
}

func buildProvider(cfg config.Config) provider.Provider {
	switch cfg.Provider {
	case "openai":
		client := &http.Client{Timeout: cfg.RequestTimeout}
		return provider.NewOpenAI(cfg.OpenAIBaseURL, cfg.OpenAIAPIKey, client)
	default:
		return provider.NewMock(cfg.MockTokenDelay)
	}
}
