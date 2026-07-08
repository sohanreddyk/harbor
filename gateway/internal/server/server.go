package server

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	"github.com/sohanreddy/harbor/gateway/internal/cache"
	"github.com/sohanreddy/harbor/gateway/internal/config"
	"github.com/sohanreddy/harbor/gateway/internal/dispatch"
	"github.com/sohanreddy/harbor/gateway/internal/ratelimit"
	"github.com/sohanreddy/harbor/gateway/internal/router"
)

// Server is the Harbor data-plane HTTP surface.
type Server struct {
	cfg     config.Config
	chain   *dispatch.Chain
	router  *router.Router
	cache   *cache.Cache
	limiter *ratelimit.Limiter
	log     *slog.Logger
}

func New(cfg config.Config, chain *dispatch.Chain, rtr *router.Router,
	c *cache.Cache, l *ratelimit.Limiter, log *slog.Logger) *Server {
	return &Server{cfg: cfg, chain: chain, router: rtr, cache: c, limiter: l, log: log}
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/chat/completions", s.handleChat)
	mux.HandleFunc("GET /v1/cache/stats", s.handleCacheStats)
	mux.HandleFunc("GET /v1/providers", s.handleProviders)
	mux.HandleFunc("GET /healthz", s.handleHealth)
	mux.HandleFunc("GET /metrics", s.handleMetrics)
	return s.withLogging(mux)
}

func (s *Server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}

func (s *Server) handleCacheStats(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(s.cache.Stats())
}

func (s *Server) handleProviders(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"providers":      s.chain.Health(),
		"fallback_count": s.chain.FallbackCount(),
	})
}

// handleMetrics is a placeholder until Prometheus wiring in Week 4.
func (s *Server) handleMetrics(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	_, _ = w.Write([]byte("# Harbor gateway metrics land in Week 4\n"))
}

func (s *Server) withLogging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		s.log.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"remote", r.RemoteAddr,
			"latency_ms", time.Since(start).Milliseconds(),
		)
	})
}
