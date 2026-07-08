// Package router implements rule-based model routing: cheap/small models for
// short, simple queries; stronger models for long or reasoning-heavy ones.
// Routing is deterministic (same query -> same model), which keeps the
// downstream semantic cache coherent, since the cache is namespaced by model.
//
// Week 2b is intentionally rule-based. Classifier- and evaluator-informed
// routing are noted in the design doc as later evolutions.
package router

import (
	"strings"

	"github.com/sohanreddy/harbor/gateway/internal/provider"
)

// Decision is the outcome of routing a single request.
type Decision struct {
	Model  string
	Tier   string // "cheap" | "strong"
	Reason string
}

type Router struct {
	cheap          string
	strong         string
	tokenThreshold int
	keywords       []string
}

func New(cheap, strong string, tokenThreshold int) *Router {
	return &Router{
		cheap:          cheap,
		strong:         strong,
		tokenThreshold: tokenThreshold,
		keywords: []string{
			"explain", "why", "debug", "compare", "how does", "design",
			"trade-off", "tradeoff", "difference between", "step by step",
		},
	}
}

// Route picks a model tier from the request's shape. Reasoning keywords force
// the strong tier; otherwise a large prompt (query + retrieved context) does.
func (r *Router) Route(req *provider.ChatRequest) Decision {
	text := strings.ToLower(provider.LastUserMessage(req))
	for _, kw := range r.keywords {
		if strings.Contains(text, kw) {
			return Decision{Model: r.strong, Tier: "strong", Reason: "keyword:" + kw}
		}
	}
	if approxTokens(req) >= r.tokenThreshold {
		return Decision{Model: r.strong, Tier: "strong", Reason: "long_prompt"}
	}
	return Decision{Model: r.cheap, Tier: "cheap", Reason: "short_simple"}
}

// approxTokens is a cheap heuristic (~4 chars/token) over all message content,
// which naturally accounts for the size of retrieved RAG context.
func approxTokens(req *provider.ChatRequest) int {
	total := 0
	for _, m := range req.Messages {
		total += len(m.Content)
	}
	return total / 4
}
