package provider

import (
	"context"
	"errors"
	"math/rand"
)

// Faulty wraps a provider and fails a configurable fraction of calls BEFORE
// emitting any output. It exists purely to exercise fallback and circuit-
// breaker behaviour deterministically, without needing a real provider outage.
// Because it fails before the first token, fallback is always safe.
type Faulty struct {
	inner     Provider
	faultRate float64
}

func NewFaulty(inner Provider, faultRate float64) *Faulty {
	return &Faulty{inner: inner, faultRate: faultRate}
}

func (f *Faulty) Name() string { return f.inner.Name() }

func (f *Faulty) Stream(ctx context.Context, req *ChatRequest, onDelta DeltaFunc) (string, error) {
	if rand.Float64() < f.faultRate {
		return "", errors.New("injected provider fault")
	}
	return f.inner.Stream(ctx, req, onDelta)
}
