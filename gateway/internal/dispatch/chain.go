// Package dispatch composes providers into an ordered fallback chain, each
// fronted by a circuit breaker. It is the piece that turns "a provider" into
// "a resilient data path."
package dispatch

import (
	"context"
	"errors"
	"sync/atomic"

	"github.com/sohanreddy/harbor/gateway/internal/breaker"
	"github.com/sohanreddy/harbor/gateway/internal/provider"
)

// Backend is one provider in the chain plus its breaker.
type Backend struct {
	Name    string
	Prov    provider.Provider
	Breaker *breaker.Breaker
}

// Result describes how a request was ultimately served.
type Result struct {
	Provider string
	Fallback bool
	Finish   string
	Degraded bool
}

type Chain struct {
	backends      []Backend
	fallbackCount atomic.Int64
}

func New(backends []Backend) *Chain {
	return &Chain{backends: backends}
}

var ErrAllUnavailable = errors.New("all providers unavailable")

// Stream tries backends in order. Critical rule: a backend is only failed over
// if it errors BEFORE emitting any content. Once tokens have been streamed to
// the client, mid-stream failure cannot be recovered without corrupting output,
// so it surfaces as an error on the current backend.
//
// onFirst is invoked exactly once, immediately before the first delta, with the
// serving backend name and whether this was a fallback — letting the caller set
// response headers at the correct moment (before the SSE body is committed).
func (c *Chain) Stream(
	ctx context.Context,
	req *provider.ChatRequest,
	onFirst func(providerName string, fallback bool),
	onDelta provider.DeltaFunc,
) (Result, error) {
	var lastErr error = ErrAllUnavailable
	for i, b := range c.backends {
		if !b.Breaker.Allow() {
			lastErr = errors.New("circuit open: " + b.Name)
			continue
		}
		started := false
		wrapped := func(d string) error {
			if !started {
				started = true
				onFirst(b.Name, i > 0)
			}
			return onDelta(d)
		}
		finish, err := b.Prov.Stream(ctx, req, wrapped)
		if err == nil {
			b.Breaker.Success()
			if i > 0 {
				c.fallbackCount.Add(1)
			}
			return Result{Provider: b.Name, Fallback: i > 0, Finish: finish}, nil
		}
		b.Breaker.Failure()
		lastErr = err
		if started {
			// Partial output already sent to the client; cannot fall back.
			return Result{Provider: b.Name, Fallback: i > 0, Finish: finish}, err
		}
		// Failed before first token: safe to try the next backend.
	}
	return Result{Degraded: true}, lastErr
}

func (c *Chain) FallbackCount() int64 { return c.fallbackCount.Load() }

// Health returns per-backend breaker state for the /v1/providers endpoint.
func (c *Chain) Health() []map[string]any {
	out := make([]map[string]any, 0, len(c.backends))
	for _, b := range c.backends {
		out = append(out, map[string]any{"provider": b.Name, "breaker": b.Breaker.State()})
	}
	return out
}
