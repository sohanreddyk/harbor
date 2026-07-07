package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

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

// handleChat is the gateway data-plane entrypoint. In Week 1 it proxies the
// request straight to the active provider and re-frames the token stream as
// OpenAI-compatible SSE. Cache lookup, routing, and fallback slot in around
// this same handler in Weeks 2+.
func (s *Server) handleChat(w http.ResponseWriter, r *http.Request) {
	var req provider.ChatRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}
	if len(req.Messages) == 0 {
		http.Error(w, `{"error":"messages is required"}`, http.StatusBadRequest)
		return
	}
	if req.Model == "" {
		req.Model = s.cfg.PrimaryModel
	}

	ctx, cancel := context.WithTimeout(r.Context(), s.cfg.RequestTimeout)
	defer cancel()

	if req.Stream {
		s.streamResponse(ctx, w, &req)
		return
	}
	s.bufferedResponse(ctx, w, &req)
}

func (s *Server) streamResponse(ctx context.Context, w http.ResponseWriter, req *provider.ChatRequest) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, `{"error":"streaming unsupported"}`, http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no") // disable proxy buffering
	w.WriteHeader(http.StatusOK)

	id := "chatcmpl-" + randID()
	created := time.Now().Unix()
	start := time.Now()
	var tokens int

	writeChunk := func(delta string) error {
		tokens++
		chunk := streamChunk{
			ID: id, Object: "chat.completion.chunk", Created: created, Model: req.Model,
			Choices: []chunkChoice{{Index: 0, Delta: map[string]any{"content": delta}}},
		}
		return sse(w, flusher, chunk)
	}

	finish, err := s.prov.Stream(ctx, req, writeChunk)
	if err != nil && ctx.Err() == nil {
		// Provider failed mid-stream and the client is still connected. Fallback
		// and circuit breaking arrive in Week 2; for now surface a final chunk.
		s.log.Error("provider stream failed", "provider", s.prov.Name(), "err", err)
	}

	// Final chunk carries the finish reason and closes the stream.
	final := streamChunk{
		ID: id, Object: "chat.completion.chunk", Created: created, Model: req.Model,
		Choices: []chunkChoice{{Index: 0, Delta: map[string]any{}, FinishReason: &finish}},
	}
	_ = sse(w, flusher, final)
	fmt.Fprint(w, "data: [DONE]\n\n")
	flusher.Flush()

	s.log.Info("chat completed",
		"provider", s.prov.Name(), "model", req.Model,
		"stream", true, "approx_tokens", tokens,
		"latency_ms", time.Since(start).Milliseconds(),
	)
}

func (s *Server) bufferedResponse(ctx context.Context, w http.ResponseWriter, req *provider.ChatRequest) {
	var sb strings.Builder
	finish, err := s.prov.Stream(ctx, req, func(delta string) error {
		sb.WriteString(delta)
		return nil
	})
	if err != nil {
		http.Error(w, `{"error":"provider failure"}`, http.StatusBadGateway)
		return
	}
	resp := map[string]any{
		"id": "chatcmpl-" + randID(), "object": "chat.completion",
		"created": time.Now().Unix(), "model": req.Model,
		"choices": []map[string]any{{
			"index":         0,
			"message":       map[string]string{"role": "assistant", "content": sb.String()},
			"finish_reason": finish,
		}},
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
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

// randID returns a short, non-cryptographic id suitable for correlating logs.
func randID() string {
	const charset = "abcdefghijklmnopqrstuvwxyz0123456789"
	b := make([]byte, 12)
	now := time.Now().UnixNano()
	for i := range b {
		b[i] = charset[(now>>(i*3))%int64(len(charset))]
	}
	return string(b)
}
