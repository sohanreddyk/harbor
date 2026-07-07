package provider

import "context"

// Message is a single chat turn in the OpenAI chat-completions format.
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ChatRequest is the OpenAI-compatible request body the gateway accepts.
type ChatRequest struct {
	Model       string    `json:"model"`
	Messages    []Message `json:"messages"`
	Stream      bool      `json:"stream"`
	Temperature *float64  `json:"temperature,omitempty"`
	MaxTokens   *int      `json:"max_tokens,omitempty"`
}

// DeltaFunc is invoked once per streamed content delta. Returning an error
// aborts the stream (e.g. the client disconnected).
type DeltaFunc func(delta string) error

// Provider is a streaming chat-completion backend. Everything downstream of
// the gateway (mock, OpenAI, Ollama, vLLM) implements this single interface,
// which keeps caching, routing, and fallback logic provider-agnostic.
type Provider interface {
	Name() string
	// Stream drives the completion, calling onDelta for each token/chunk and
	// returning the finish reason ("stop", "length", ...) when complete.
	Stream(ctx context.Context, req *ChatRequest, onDelta DeltaFunc) (finishReason string, err error)
}

// LastUserMessage returns the content of the final user turn, or "".
func LastUserMessage(req *ChatRequest) string {
	for i := len(req.Messages) - 1; i >= 0; i-- {
		if req.Messages[i].Role == "user" {
			return req.Messages[i].Content
		}
	}
	return ""
}
