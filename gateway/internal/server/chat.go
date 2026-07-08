package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/sohanreddy/harbor/gateway/internal/cache"
	"github.com/sohanreddy/harbor/gateway/internal/provider"
)

// ---- OpenAI-compatible response envelopes ----

type chunkChoice struct {
	Index        int            `json:"index"`
	Delta        map[string]any `json:"delta"`
	FinishReason *string        `json:"finish_reason"`
}

type streamChunk struct {
	ID      string        `json:"id"`
	Object  string        `json:"object"`
	Created int64         `json:"created"`
	Model   string        `json:"model"`
	Choices []chunkChoice `json:"choices"`
}

// harborMeta carries Harbor-specific hints; parsed from the client but never
// forwarded upstream (the provider only sees the embedded provider.ChatRequest).
type harborMeta struct {
	Embedding     []float32 `json:"embedding,omitempty"`
	ContextHash   string    `json:"context_hash,omitempty"`
	PromptVersion string    `json:"prompt_version,omitempty"`
	ClientID      string    `json:"client_id,omitempty"`
}

type incomingRequest struct {
	provider.ChatRequest
	Harbor *harborMeta `json:"harbor,omitempty"`
}

func (s *Server) handleChat(w http.ResponseWriter, r *http.Request) {
	var in incomingRequest
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}
	req := &in.ChatRequest
	if len(req.Messages) == 0 {
		http.Error(w, `{"error":"messages is required"}`, http.StatusBadRequest)
		return
	}
	meta := in.Harbor
	if meta == nil {
		meta = &harborMeta{}
	}

	// --- Rate limiting ---
	if s.cfg.RateLimitEnabled {
		clientID := meta.ClientID
		if clientID == "" {
			clientID = r.Header.Get("X-Harbor-Client")
		}
		if clientID == "" {
			clientID = "global"
		}
		if !s.limiter.Allow(r.Context(), clientID, time.Now().UnixMilli()) {
			s.metrics.RateLimited.Inc()
			w.Header().Set("Content-Type", "application/json")
			http.Error(w, `{"error":"rate limit exceeded"}`, http.StatusTooManyRequests)
			return
		}
	}

	// --- Routing (deterministic; sets the model that also namespaces the cache) ---
	decision := s.router.Route(req)
	req.Model = decision.Model

	ctx, cancel := context.WithTimeout(r.Context(), s.cfg.RequestTimeout)
	defer cancel()

	// --- Cache lookup ---
	namespace := req.Model + "|" + meta.ContextHash + "|" + meta.PromptVersion
	exactKey := cache.HashMessages(req.Model, messageParts(req)...)
	var hit *cache.Entry
	var sim float64
	if s.cfg.CacheEnabled {
		if len(meta.Embedding) > 0 {
			hit, sim = s.cache.LookupSemantic(namespace, meta.Embedding, s.cfg.CacheThreshold)
		} else {
			hit = s.cache.LookupExact(namespace, exactKey)
			sim = 1.0
		}
	}

	if hit != nil {
		s.cache.TouchHit(hit)
		s.serveHit(w, req, hit, sim, decision.Tier)
		return
	}
	s.serveMiss(ctx, w, req, meta, namespace, exactKey, decision.Tier)
}

// serveHit replays a cached response as an SSE stream at near-zero latency.
func (s *Server) serveHit(w http.ResponseWriter, req *provider.ChatRequest, e *cache.Entry, sim float64, tier string) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, `{"error":"streaming unsupported"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("X-Harbor-Cache", "hit")
	w.Header().Set("X-Harbor-Cache-Similarity", fmt.Sprintf("%.4f", sim))
	w.Header().Set("X-Harbor-Model", e.Model)
	w.Header().Set("X-Harbor-Route", tier)
	setSSEHeaders(w)

	id := "chatcmpl-" + randID()
	created := time.Now().Unix()
	start := time.Now()
	toks := tokenizeReplay(e.Response)
	for _, tok := range toks {
		_ = sse(w, flusher, deltaChunk(id, created, req.Model, tok))
		if s.cfg.CacheReplayPacing > 0 {
			time.Sleep(s.cfg.CacheReplayPacing)
		}
	}
	_ = sse(w, flusher, finalChunk(id, created, req.Model, "stop"))
	fmt.Fprint(w, "data: [DONE]\n\n")
	flusher.Flush()
	s.metrics.ObserveChat("hit", tier, "cache", false, time.Since(start),
		promptTokens(req), len(toks), s.cfg.CostPer1kTokens)
	s.syncGauges()
	s.log.Info("chat completed", "cache", "hit", "similarity", sim,
		"model", req.Model, "route", tier, "latency_ms", time.Since(start).Milliseconds())
}

// serveMiss streams a fresh completion through the fallback chain while
// accumulating the full text, then caches the complete response.
func (s *Server) serveMiss(ctx context.Context, w http.ResponseWriter, req *provider.ChatRequest, meta *harborMeta, namespace, exactKey, tier string) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, `{"error":"streaming unsupported"}`, http.StatusInternalServerError)
		return
	}

	id := "chatcmpl-" + randID()
	created := time.Now().Unix()
	start := time.Now()
	var full strings.Builder
	compTokens := 0
	headersWritten := false

	onFirst := func(providerName string, fallback bool) {
		w.Header().Set("X-Harbor-Cache", "miss")
		w.Header().Set("X-Harbor-Model", req.Model)
		w.Header().Set("X-Harbor-Route", tier)
		w.Header().Set("X-Harbor-Provider", providerName)
		if fallback {
			w.Header().Set("X-Harbor-Fallback", "true")
		}
		setSSEHeaders(w)
		headersWritten = true
	}
	onDelta := func(delta string) error {
		full.WriteString(delta)
		compTokens++
		return sse(w, flusher, deltaChunk(id, created, req.Model, delta))
	}

	result, err := s.chain.Stream(ctx, req, onFirst, onDelta)

	// No provider produced any output -> graceful degraded response.
	if !headersWritten {
		s.serveDegraded(w, flusher, req, tier, id, created, err)
		s.metrics.ObserveChat("miss", tier, "degraded", false, time.Since(start),
			promptTokens(req), 0, s.cfg.CostPer1kTokens)
		s.syncGauges()
		return
	}

	finish := result.Finish
	if finish == "" {
		finish = "stop"
	}
	_ = sse(w, flusher, finalChunk(id, created, req.Model, finish))
	fmt.Fprint(w, "data: [DONE]\n\n")
	flusher.Flush()

	// Cache only complete, non-empty, successfully-served responses.
	if s.cfg.CacheEnabled && err == nil && ctx.Err() == nil && full.Len() > 0 {
		entry := &cache.Entry{ID: randID(), Namespace: namespace, Response: full.String(), Model: req.Model}
		if len(meta.Embedding) > 0 {
			entry.Embedding = meta.Embedding
		} else {
			entry.ExactKey = exactKey
		}
		s.cache.Store(context.Background(), entry)
	}
	s.metrics.ObserveChat("miss", tier, result.Provider, result.Fallback, time.Since(start),
		promptTokens(req), compTokens, s.cfg.CostPer1kTokens)
	s.syncGauges()
	s.log.Info("chat completed", "cache", "miss", "provider", result.Provider,
		"fallback", result.Fallback, "route", tier, "model", req.Model,
		"latency_ms", time.Since(start).Milliseconds())
}

// serveDegraded emits a short, honest fallback message as a stream when every
// provider is unavailable, so the client degrades gracefully instead of getting
// a hard error. Degraded responses are never cached.
func (s *Server) serveDegraded(w http.ResponseWriter, flusher http.Flusher, req *provider.ChatRequest, tier, id string, created int64, cause error) {
	w.Header().Set("X-Harbor-Cache", "miss")
	w.Header().Set("X-Harbor-Degraded", "true")
	w.Header().Set("X-Harbor-Route", tier)
	setSSEHeaders(w)
	msg := "Harbor is temporarily unable to reach an upstream model. Please retry in a moment."
	for _, tok := range tokenizeReplay(msg) {
		_ = sse(w, flusher, deltaChunk(id, created, req.Model, tok))
	}
	_ = sse(w, flusher, finalChunk(id, created, req.Model, "stop"))
	fmt.Fprint(w, "data: [DONE]\n\n")
	flusher.Flush()
	s.log.Warn("degraded response served", "route", tier, "cause", cause)
}

// ---- helpers ----

func setSSEHeaders(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
}

func deltaChunk(id string, created int64, model, delta string) streamChunk {
	return streamChunk{
		ID: id, Object: "chat.completion.chunk", Created: created, Model: model,
		Choices: []chunkChoice{{Index: 0, Delta: map[string]any{"content": delta}}},
	}
}

func finalChunk(id string, created int64, model, finish string) streamChunk {
	return streamChunk{
		ID: id, Object: "chat.completion.chunk", Created: created, Model: model,
		Choices: []chunkChoice{{Index: 0, Delta: map[string]any{}, FinishReason: &finish}},
	}
}

func promptTokens(req *provider.ChatRequest) int {
	total := 0
	for _, m := range req.Messages {
		total += len(m.Content)
	}
	return total / 4
}

func messageParts(req *provider.ChatRequest) []string {
	parts := make([]string, len(req.Messages))
	for i, m := range req.Messages {
		parts[i] = m.Role + ":" + m.Content
	}
	return parts
}

func tokenizeReplay(s string) []string {
	var out []string
	var b strings.Builder
	for _, r := range s {
		b.WriteRune(r)
		if r == ' ' {
			out = append(out, b.String())
			b.Reset()
		}
	}
	if b.Len() > 0 {
		out = append(out, b.String())
	}
	return out
}

func sse(w http.ResponseWriter, flusher http.Flusher, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	if _, err := fmt.Fprintf(w, "data: %s\n\n", b); err != nil {
		return err
	}
	flusher.Flush()
	return nil
}

func randID() string {
	const charset = "abcdefghijklmnopqrstuvwxyz0123456789"
	b := make([]byte, 12)
	now := time.Now().UnixNano()
	for i := range b {
		b[i] = charset[(now>>(i*3))%int64(len(charset))]
	}
	return string(b)
}
