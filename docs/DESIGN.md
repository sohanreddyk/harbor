# Harbor — Design

A self-hosted LLM reliability platform: gateway, semantic cache, model routing,
fallback, an evaluation control plane with CI regression gating, and
observability. This document is the authoritative architecture reference.

---

## 1. Name

**Harbor.** A harbor is where traffic safely docks and is measured before it
proceeds — the metaphor fits a reliability layer that requests pass through.
One caveat: it collides with the CNCF *Harbor* container registry
(goharbor.io); the README disambiguates. If total uniqueness is preferred,
**Breakwater** is the fallback (the structure that protects a harbor).

## 2. One-line product description

Harbor is an open-source, self-hostable reliability layer that makes any LLM
application cheaper, faster, observable, and safe to change.

## 3. One-line resume description

Built a self-hosted LLM reliability platform (Go gateway + Python control
plane) with semantic caching, model routing/fallback, and statistical eval-CI
regression gating.

## 4. Problem statement

Teams shipping LLM features hit the same wall: costs balloon on repetitive
traffic, tail latency is multi-second, prompt/model changes silently regress
quality, provider outages take features down, and nobody can see cost, latency,
or quality in one place. Point tools exist for pieces of this, but wiring them
together — and understanding the correctness tradeoffs — is left to each team.
Harbor packages the reliability layer as one self-hosted system.

## 5. Why this is impressive

It spans real distributed-systems and ML-systems surface area: a low-latency
Go data plane with streaming, caching, and circuit breaking; a Python control
plane doing statistical hypothesis testing on noisy eval scores; and honest,
reproducible measurement of hard tradeoffs (cache threshold vs false-hit rate,
naive vs statistical regression detection). Every headline number is produced
by a script against a Zipf-distributed workload, not asserted.

## 6. What Harbor is not

Not multi-tenant, no auth, no billing, no SaaS admin UI, no org/team
management, no payments, no hosted cloud product. Single-tenant, self-hosted,
one reference app, one strong demo flow, serious measurement.

## 7. Full system architecture

Two planes plus a reference app.

- **Reference RAG app (Python/FastAPI):** retrieves context from pgvector,
  builds the prompt, calls the gateway, streams SSE to the browser with
  citations. Also hosts the control plane (eval APIs, Celery workers).
- **Data plane (Go gateway):** OpenAI-compatible endpoint. On the request path:
  semantic-cache lookup → rate limit → route → provider call (with fallback and
  circuit breaking) → stream response while accumulating → cache on completion.
- **Control plane (Python/Celery):** offline eval suites over a golden dataset
  with regression detection gating CI; online sampling of live traffic scored
  asynchronously to detect quality drift.
- **Storage:** PostgreSQL + pgvector for corpus/embeddings, request logs, cache
  metadata, eval data, versions, alerts. Redis for cache vectors + rate limits +
  Celery broker.
- **Observability:** Prometheus + Grafana for system metrics; a custom React
  dashboard for quality/eval metrics.

```
Browser ─SSE─ FastAPI refapp ─HTTP─ Go gateway ─── provider (mock|OpenAI|Ollama|vLLM)
                  │                     │
              pgvector              Redis (cache vectors, token buckets)
                  │
        Celery workers ── eval scoring ── Postgres (runs, results, drift)
                  │
        GitHub Actions eval gate
```

## 8. Data plane architecture

Request lifecycle inside the gateway:

1. Parse OpenAI-compatible request; normalize prompt.
2. **Semantic cache lookup** — embed the normalized prompt, cosine-search Redis;
   on hit above threshold τ, replay the stored full response as an SSE stream.
3. **Rate limit** — Redis + Lua atomic token bucket keyed per client/route.
4. **Route** — pick model tier from features (query length, retrieved-context
   size, keywords).
5. **Call provider** — stream tokens out while accumulating the full text; on
   timeout/error trigger **fallback** to a backup provider; a **circuit breaker**
   per provider trips after a failure-rate threshold and recovers half-open.
6. **Cache write** — on a complete (non-aborted) stream, store the full response
   keyed by (prompt embedding, context hash, model, prompt version).
7. **Metrics** — record cost, latency, tokens, cache status, fallback, errors.

Provider abstraction is a single `Provider` interface (`Stream(ctx, req,
onDelta)`), so mock/OpenAI/Ollama/vLLM are interchangeable and caching operates
on plain text, not raw SSE.

## 9. Control plane architecture

- **Offline:** a change to prompt/model/retrieval/system-instruction triggers an
  eval run over the golden dataset. Each test case is scored by one or more
  evaluators. The run is compared against the stored baseline run; regression is
  decided first by mean comparison, then by Mann-Whitney U. Significant drops
  fail CI.
- **Online:** a configurable fraction of live requests is sampled and enqueued
  to Celery eval workers. Scores are written to a time series; drift below a
  threshold raises an alert.

## 10. Reference RAG app design

Corpus: Kubernetes documentation (+ GitHub issues later). Ingestion chunks docs
paragraph-aware, embeds with a local model, stores in pgvector with an HNSW
cosine index. At query time: embed query (with BGE retrieval instruction),
top-k cosine search, format `[n]`-numbered context, call gateway, stream tokens,
emit a `sources` SSE event mapping `[n]` → document. React renders streaming
text + citation chips.

## 11. Tech stack decision with justification

- **Go 1.24 gateway** — the data plane is latency- and concurrency-critical;
  goroutines + net/http give cheap streaming fan-out. Week 1 is stdlib-only so
  it builds offline; go-redis and prometheus deps arrive when needed.
- **Redis + Lua** — atomic token-bucket rate limiting needs check-and-decrement
  in one round trip; Lua runs server-side atomically. Redis also holds cache
  vectors and is the Celery broker.
- **FastAPI + Celery + Postgres + pgvector** — Python owns retrieval, evals, and
  stats (scipy). pgvector avoids a second datastore. Celery decouples online
  eval from the request path.
- **fastembed (ONNX) over sentence-transformers/torch** — keeps images small and
  cold-start fast for a self-hosted system; bge-small-en-v1.5 (384-d) is a
  strong small retriever.
- **React + TS + Tailwind + Recharts** — streaming chat UX + a quality
  dashboard.
- **Prometheus/Grafana + custom React dashboard** — Prometheus for system
  metrics (RPS, latency histograms, errors); React for quality metrics
  (eval scores, pass rate, cache correctness) that live in Postgres.

## 12. Database schema (Postgres + pgvector)

Retrieval: `corpus_documents`, `corpus_chunks(embedding vector(384), HNSW
cosine)`. Data plane: `request_logs`, `cache_entries(prompt_embedding, context
hash, model, prompt_version, response_text, hit_count)`. Control plane:
`eval_suites`, `test_cases(input, gold_answer, gold_citations)`,
`prompt_versions`, `model_versions`, `eval_runs(baseline_run_id, mean_score,
git_sha)`, `eval_results(run_id, evaluator, score, passed)`, `quality_metrics`
(time series), `alerts`. Week 1 creates only the two retrieval tables; the rest
land with Alembic in Week 3.

## 13. API design

Gateway: `POST /v1/chat/completions` (stream), `GET /healthz`, `GET /metrics`.
Reference app: `POST /api/chat` (SSE), `GET /api/health`, `GET
/api/corpus/stats`; later `POST /api/eval/run`, `GET /api/eval/runs`, `GET
/api/metrics/quality`.

## 14. Gateway design

See §8. Key structures: `Provider` interface, per-provider circuit breaker,
token-bucket limiter (Redis+Lua), semantic cache client. Handler is thin and
composes middleware so cache/route/fallback layer in without rewrites.

## 15. Evaluation control plane design

An `EvalRun` fixes (suite, prompt_version, model_version, retrieval_config,
git_sha). Workers score every test case with the configured evaluators,
persist `eval_results`, compute per-evaluator score distributions, then run
regression detection against the baseline. CLI `harbor-eval run` powers both
local use and CI.

## 16. Semantic cache design

Cache key is the tuple (normalized-prompt embedding, context hash, model,
prompt version) — **not** just the prompt string. Same question over a changed
corpus, model, or prompt template must not collide, so context/version are part
of the key (namespace or dimension). Lookup: cosine-search cached embeddings;
serve if similarity ≥ τ. Only complete streams are cached; aborted ones are not.

## 17. Cache correctness measurement design

Build a labeled probe set: paraphrase pairs (should-hit) and distinct-but-
similar pairs (should-miss). Sweep τ and measure, per threshold: **hit rate**,
**false-hit rate** (served a cached answer that materially differs from the
fresh answer — judged by embedding similarity to the fresh answer plus an
LLM-judge agreement check), **cost saved**, **latency saved**. Output tradeoff
curves (τ vs each). The chosen τ is the knee that maximizes savings while
holding false-hit rate under a stated bound. This is the flagship interview
story.

## 18. Routing and fallback design

Routing v1 is rule-based: short/factual queries with small retrieved context →
cheap/small model; long queries, large context, or keywords (explain, debug,
why, compare) → strong model. Later: classifier- and evaluator-informed routing.
Fallback: primary timeout/5xx → secondary provider; per-provider circuit breaker
(closed→open→half-open on failure-rate window); degraded mode returns a
cached/template answer flagged via header. Metrics expose fallback count and
provider health.

## 19. Streaming design

Miss path: tee the provider stream — forward each delta to the client while
appending to a buffer; on completion write the full text to cache. Hit path:
reconstruct a synthetic SSE stream from the cached text (optionally paced), so
UX is identical and latency is near-zero. Aborted streams (client disconnect,
provider error) are never cached.

## 20. Eval CI design

A GitHub Action runs the eval suite on PRs that touch prompts/models/retrieval
config, compares against the committed baseline, and **fails the check** on a
statistically significant regression, attaching a readable report artifact
(per-evaluator deltas, p-values, effect sizes, example regressions).

## 21. Regression detection design

Start with mean-score comparison, then move to **Mann-Whitney U** (non-
parametric, no normality assumption) with an effect size (rank-biserial /
Cliff's delta) and a minimum sample size. Multiple evaluators → Holm-Bonferroni
correction. A regression must be both statistically significant and practically
meaningful (effect-size floor) to fail CI.

## 22. Online evaluation design

Sample a fraction of live requests → enqueue to Celery → score with a subset of
evaluators (favoring reference-free ones: groundedness, citation correctness) →
write `quality_metrics` time series → alert on drift below threshold using a
rolling-window comparison.

## 23. Observability dashboard design

Prometheus/Grafana: gateway RPS, p50/p95/p99 latency, token counts, provider
error rate, fallback count, cache hit rate. Custom React dashboard (from
Postgres): cost per request, total simulated spend, estimated cost saved,
semantic-cache threshold + false-hit estimate, eval scores over time, pass rate,
regression alerts.

## 24. Synthetic workload design (Zipf)

Real LLM traffic is heavy-tailed: a few queries dominate, which is exactly what
makes caching pay off. The generator draws from a query catalog (derived from
the corpus) using a Zipf distribution with a tunable skew `s`; higher `s` →
more repeats → higher achievable hit rate. This lets us honestly report how
savings depend on traffic shape.

## 25. Measurement plan

Scripts produce: p50/p99 latency before/after cache; cost saved on repeat-heavy
Zipf traffic (target ~40%); sustained gateway RPS under load; false-hit rate vs
τ curve; fallback success rate under injected provider failure; and an eval-CI
demonstration where a seeded bad prompt drops accuracy (e.g. 88%→79%) and CI
blocks the merge. No invented numbers.

## 26. Folder structure

```
gateway/    Go data plane (cmd/, internal/{config,provider,server})
refapp/     FastAPI app (app/{api,...}), scripts/ingest.py, data/corpus/
frontend/   React + TS + Tailwind
docs/       this document + runbooks
```

## 27. Five-week roadmap

- **W1 Integration spine** — refapp → gateway → provider, e2e streaming, corpus
  in pgvector.
- **W2 Cache + routing + fallback** — semantic cache, rules routing, fallback,
  Zipf workload, first cost/latency numbers.
- **W3 Eval CI + regression detection** — golden dataset, evaluators, baseline,
  Mann-Whitney U, GitHub Action gate.
- **W4 Observability + frontend polish** — Prometheus/Grafana + React dashboard,
  citations, run history.
- **W5 Measurement + release** — load test, final metrics, docs, README, demo,
  resume bullets.

## 28. Buffer week

Kubernetes manifests, HPA, deployment docs, optional Grafana dashboards.

## 29. Testing strategy

Go: unit tests for provider parsing, cache key derivation, breaker state
machine, limiter; httptest for the SSE handler. Python: pytest for chunking,
retrieval, evaluators, and regression stats (including known-distribution
sanity checks). Integration: docker-compose smoke test hitting `/api/chat`.

## 30. Deployment plan

Docker Compose first (this repo). Kubernetes manifests + HPA in the buffer week.
Mock provider keeps CI and demos key-free.

## 31. Documentation plan

This design doc, a README quickstart, per-component READMEs, an architecture
diagram, and a measurement writeup with the tradeoff curves.

## 32. Demo video script

(1) Ask a question, watch streamed RAG answer with citations. (2) Ask a repeat →
instant cached streaming replay; show hit-rate/cost panel. (3) Kill the primary
provider → fallback keeps answering; show breaker + fallback metrics. (4) Open a
PR with a worse prompt → CI eval gate fails with a regression report. (5) Show
the dashboard tying cost, latency, and quality together.

## 33. Interview stories

Semantic-cache threshold vs false-hit tradeoff; streaming-plus-caching
tee/replay; regression detection under noisy evals (why Mann-Whitney U);
routing + fallback + circuit breaking; honest measurement on Zipf traffic.

## 34. "Isn't this just Helicone/LangSmith?"

Yes — same problem space (LangSmith, Helicone, Portkey, Langfuse, LiteLLM). I
built a self-hostable version from scratch to understand the systems tradeoffs
firsthand: cache correctness, streaming cache replay, model fallback, and
statistical regression detection — the parts those products hide behind the UI.

## 35. Resume bullets

Finalized in Week 5 from measured numbers. Draft frame: "self-hosted LLM
reliability platform (Go gateway + Python control plane) cutting simulated spend
~40% via semantic caching on repeat-heavy traffic, with Mann-Whitney U eval-CI
that blocks quality regressions before merge."

## 36. First coding steps

Week 1: scaffold gateway (stdlib, mock provider, SSE) → refapp (pgvector
retrieval + SSE) → frontend → docker-compose → ingest corpus → verify e2e
streaming.
