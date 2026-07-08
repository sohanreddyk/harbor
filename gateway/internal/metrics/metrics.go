// Package metrics holds Harbor's Prometheus instrumentation for the data plane.
// One place owns every collector so the /metrics endpoint and the recording
// call sites can't drift apart.
package metrics

import (
	"net/http"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type Metrics struct {
	reg *prometheus.Registry

	Requests     *prometheus.CounterVec   // by cache/route/provider/fallback
	Latency      *prometheus.HistogramVec // by cache (hit vs miss)
	Tokens       *prometheus.CounterVec   // by kind (prompt/completion)
	CacheEntries prometheus.Gauge
	Fallback     prometheus.Counter
	RateLimited  prometheus.Counter
	CostUSD      prometheus.Counter // estimated billed spend (misses)
	CostSavedUSD prometheus.Counter // estimated spend avoided by cache hits
	BreakerState *prometheus.GaugeVec
}

func New() *Metrics {
	reg := prometheus.NewRegistry()
	m := &Metrics{
		reg: reg,
		Requests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "harbor_requests_total",
			Help: "Chat requests served, labelled by cache status, route tier, provider and fallback.",
		}, []string{"cache", "route", "provider", "fallback"}),
		Latency: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "harbor_request_latency_seconds",
			Help:    "End-to-end gateway latency by cache status.",
			Buckets: []float64{0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10},
		}, []string{"cache"}),
		Tokens: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "harbor_tokens_total",
			Help: "Approximate tokens processed, by kind.",
		}, []string{"kind"}),
		CacheEntries: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "harbor_cache_entries", Help: "Current number of semantic cache entries.",
		}),
		Fallback: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "harbor_fallback_total", Help: "Requests served by a fallback provider.",
		}),
		RateLimited: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "harbor_rate_limited_total", Help: "Requests rejected by the rate limiter.",
		}),
		CostUSD: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "harbor_cost_usd_total", Help: "Estimated billed spend (cache misses).",
		}),
		CostSavedUSD: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "harbor_cost_saved_usd_total", Help: "Estimated spend avoided by cache hits.",
		}),
		BreakerState: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Name: "harbor_provider_breaker_state", Help: "Circuit breaker state: 0=closed, 1=half-open, 2=open.",
		}, []string{"provider"}),
	}
	reg.MustRegister(
		m.Requests, m.Latency, m.Tokens, m.CacheEntries, m.Fallback,
		m.RateLimited, m.CostUSD, m.CostSavedUSD, m.BreakerState,
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
	)
	return m
}

func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.reg, promhttp.HandlerOpts{})
}

// ObserveChat records a single completed chat request.
func (m *Metrics) ObserveChat(cache, route, provider string, fallback bool,
	latency time.Duration, promptTokens, completionTokens int, costPer1k float64) {
	fb := "false"
	if fallback {
		fb = "true"
	}
	m.Requests.WithLabelValues(cache, route, provider, fb).Inc()
	m.Latency.WithLabelValues(cache).Observe(latency.Seconds())
	m.Tokens.WithLabelValues("prompt").Add(float64(promptTokens))
	m.Tokens.WithLabelValues("completion").Add(float64(completionTokens))

	cost := float64(promptTokens+completionTokens) / 1000.0 * costPer1k
	if cache == "hit" {
		m.CostSavedUSD.Add(cost)
	} else {
		m.CostUSD.Add(cost)
	}
	if fallback {
		m.Fallback.Inc()
	}
}

func (m *Metrics) SetCacheEntries(n int) { m.CacheEntries.Set(float64(n)) }

func (m *Metrics) SetBreaker(provider, state string) {
	v := 0.0
	switch state {
	case "half-open":
		v = 1
	case "open":
		v = 2
	}
	m.BreakerState.WithLabelValues(provider).Set(v)
}
