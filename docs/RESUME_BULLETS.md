# Harbor — resume & LinkedIn bullets

Every figure here is defended in `docs/BENCHMARKS.md`. Framing is deliberately
qualified so it survives an interviewer's follow-up questions. Pick 2–4.

## Resume bullets (XYZ form)

- Built **Harbor**, a self-hosted LLM reliability gateway (Go data plane +
  Python/FastAPI control plane + React) that fronts any OpenAI-compatible model
  with semantic caching, model routing, provider fallback, and a CI-gated
  evaluation harness; fully containerized with Prometheus/Grafana observability.

- Designed a **streaming semantic cache** (cosine similarity over query
  embeddings, Redis write-through) that cut estimated token spend by **up to
  ~85%** and returned cache hits **~9.5× faster** (p50 ≈120 ms vs multi-second
  generation) on Zipf-skewed traffic.

- Implemented **provider fallback with per-provider circuit breakers** that
  sustained **100% request success during a simulated total primary-provider
  outage** (served from cache + fallback), with graceful degraded responses when
  all providers fail.

- Built a **statistical regression gate** for answer quality — Mann-Whitney U
  test with a Cliff's-delta effect-size threshold and Holm-Bonferroni correction
  — wired into GitHub Actions so prompt/model changes that degrade quality **fail
  CI before merge**.

## One-line summary (top of resume / LinkedIn headline)

> Harbor — a self-hosted LLM reliability gateway (Go + Python + React): semantic
> caching (~85% spend saved, ~9.5× faster hits), provider fallback with circuit
> breaking, and a statistical eval gate in CI.

## Interview talking points (know these cold)

- **Why the cache stays coherent under routing:** routing is deterministic, so a
  given prompt always maps to the same model, which is part of the cache key —
  no split-brain between "cheap" and "strong" answers for the same query.
- **Why two stats, not one, in the gate:** a Mann-Whitney U p-value alone flags
  tiny, significant-but-meaningless drops; requiring a Cliff's-delta effect size
  (|δ| ≥ 0.33) too means it fails on drops that actually matter. Holm-Bonferroni
  keeps the family-wise error at 0.05 across multiple evaluators.
- **Why the % cost figure and not the dollar figure:** two independent token
  models disagree on absolute dollars but agree on ~85% saved — savings track
  the hit rate, not the tokenizer.
- **What you'd do next:** single-flight request coalescing (concurrent duplicate
  misses aren't collapsed yet), a shared vector cache for multi-replica gateways,
  and Alembic migrations.
