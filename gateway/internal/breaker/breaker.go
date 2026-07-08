// Package breaker is a small per-provider circuit breaker.
//
// Closed  -> normal operation; consecutive failures increment a counter.
// Open    -> calls are rejected immediately; entered when failures reach the
//            threshold. After a cooldown it transitions to HalfOpen.
// HalfOpen-> a single trial call is allowed; success closes the breaker, any
//            failure re-opens it.
//
// This prevents hammering a provider that is already failing and gives it time
// to recover, while a fallback provider absorbs traffic.
package breaker

import (
	"sync"
	"time"
)

type State int

const (
	Closed State = iota
	Open
	HalfOpen
)

func (s State) String() string {
	switch s {
	case Open:
		return "open"
	case HalfOpen:
		return "half-open"
	default:
		return "closed"
	}
}

type Breaker struct {
	mu        sync.Mutex
	state     State
	failures  int
	threshold int
	cooldown  time.Duration
	openedAt  time.Time
}

func New(threshold int, cooldown time.Duration) *Breaker {
	return &Breaker{state: Closed, threshold: threshold, cooldown: cooldown}
}

// Allow reports whether a call may proceed, moving Open -> HalfOpen once the
// cooldown has elapsed.
func (b *Breaker) Allow() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.state == Open {
		if time.Since(b.openedAt) >= b.cooldown {
			b.state = HalfOpen
			return true
		}
		return false
	}
	return true
}

func (b *Breaker) Success() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.failures = 0
	b.state = Closed
}

func (b *Breaker) Failure() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.failures++
	if b.state == HalfOpen || b.failures >= b.threshold {
		b.state = Open
		b.openedAt = time.Now()
	}
}

func (b *Breaker) State() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.state.String()
}
