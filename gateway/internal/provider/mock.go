package provider

import (
	"context"
	"strings"
	"time"
)

// Mock is a deterministic, offline provider. It lets the entire Harbor stack
// run and be demoed with zero API keys and no network egress, which also makes
// it the default backend for CI and load tests where determinism matters.
//
// It is NOT pretending to be a real LLM: it produces an extractive answer from
// the retrieved context that the reference app injects into the prompt, then
// streams it token-by-token so downstream streaming behaviour is exercised
// exactly as it would be with a real model.
type Mock struct {
	// PerTokenDelay simulates inter-token latency so the UI streams visibly.
	PerTokenDelay time.Duration
}

func NewMock(perTokenDelay time.Duration) *Mock {
	return &Mock{PerTokenDelay: perTokenDelay}
}

func (m *Mock) Name() string { return "mock" }

func (m *Mock) Stream(ctx context.Context, req *ChatRequest, onDelta DeltaFunc) (string, error) {
	answer := m.compose(LastUserMessage(req))
	for _, tok := range tokenize(answer) {
		select {
		case <-ctx.Done():
			return "stop", ctx.Err()
		default:
		}
		if err := onDelta(tok); err != nil {
			return "stop", err
		}
		if m.PerTokenDelay > 0 {
			time.Sleep(m.PerTokenDelay)
		}
	}
	return "stop", nil
}

// compose builds an extractive answer from the "Context:" / "Question:" blocks
// the reference app formats into the user message.
func (m *Mock) compose(userMsg string) string {
	context, question := splitContextQuestion(userMsg)
	if context == "" {
		return "I could not find any supporting documentation for that question in the current corpus."
	}
	snippet := firstSentences(context, 2)
	q := strings.TrimSpace(question)
	if q == "" {
		q = "your question"
	}
	return "Based on the retrieved documentation: " + snippet +
		" This directly addresses " + strings.ToLower(strings.TrimRight(q, "?")) + ". [1]"
}

func splitContextQuestion(s string) (context, question string) {
	lower := strings.ToLower(s)
	qi := strings.LastIndex(lower, "question:")
	ci := strings.Index(lower, "context:")
	if qi == -1 {
		return strings.TrimSpace(s), ""
	}
	question = strings.TrimSpace(s[qi+len("question:"):])
	if ci != -1 && ci < qi {
		context = strings.TrimSpace(s[ci+len("context:") : qi])
	} else {
		context = strings.TrimSpace(s[:qi])
	}
	return context, question
}

func firstSentences(s string, n int) string {
	// Strip citation markers like "[1]" from the source so the mock answer
	// reads naturally.
	s = strings.Join(strings.Fields(s), " ")
	count := 0
	for i, r := range s {
		if r == '.' || r == '!' || r == '?' {
			count++
			if count >= n {
				return strings.TrimSpace(s[:i+1])
			}
		}
	}
	if len(s) > 300 {
		return strings.TrimSpace(s[:300]) + "..."
	}
	return s
}

// tokenize splits into whitespace-preserving chunks so the reconstructed text
// is identical to the source when concatenated.
func tokenize(s string) []string {
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
