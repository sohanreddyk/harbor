package server

import (
	"log/slog"
	"net/http"
	"time"

	"github.com/sohanreddy/harbor/gateway/internal/config"
	"github.com/sohanreddy/harbor/gateway/internal/provider"
)

// Server is the Harbor data-plane HTTP surface.
type Server struct {
	cfg  config.Config
	prov provider.Provider
	log  *slog.Logger
}

func New(cfg config.Config, prov provider.Provider, log *slog.Logger) *Server {
	return &Server{cfg: cfg, prov: prov, log: log}
}

// Routes returns the fully wired HTTP handler.
func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/chat/completions", s.handleChat)
	mux.HandleFunc("GET /healthz", s.handleHealth)
	mux.HandleFunc("GET /metrics", s.handleMetrics)
	return s.withLogging(mux)
}

func (s *Server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"status":"ok","provider":"` + s.prov.Name() + `"}`))
}

// handleMetrics is a placeholder in Week 1. Prometheus wiring
// (github.com/prometheus/client_golang) lands in Week 4 once the counters we
// care about — cache hits, fallbacks, latency histograms — exist.
func (s *Server) handleMetrics(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	_, _ = w.Write([]byte("# Harbor gateway metrics land in Week 4\n"))
}

// withLogging emits one structured log line per request with latency.
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
