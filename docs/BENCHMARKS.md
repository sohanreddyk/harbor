# Harbor — Measurements

This document reports what Harbor actually does under load, how those numbers
were produced, and — just as importantly — what they do **not** prove. Every
figure here is reproducible from the `make` targets in the repo. Where a number
is shaped by the test setup rather than the system, that is called out inline
rather than buried.

The guiding principle: a benchmark you can't defend in a follow-up question is
worth less than a smaller one you can. The honest qualifiers below are part of
the result, not a disclaimer bolted on afterward.

---

## TL;DR

| Result | Number | The honest one-line version |
|---|---|---|
| Cache hit rate | **85%** (340/400) | On a Zipf-skewed workload (s=1.2) over a 12-topic catalog. Skew and catalog size drive this — see §1. |
| Median latency reduction on hits | **~89%** (≈9.5×) | Hit p50 ≈122 ms vs miss p50 ≈1155 ms. Miss latency is a *simulated* model, hit latency is real — see §1. |
| Estimated spend avoided | **~85%** | Two independent cost models agree on the **percentage**; absolute dollars are model-dependent — see §1. |
| Requests served during a total primary outage | **400/400** | Primary forced to 100% failure; 340 from cache + 60 via fallback, breaker opened. Zero user-facing errors — see §2. |
| Regression gate | **catches real drops, ignores noise** | Bad prompt fails the CI gate (p<1e-4, Cliff's δ=−1.0); an unchanged prompt passes (p≈0.51) — see §3. |

---

## How to reproduce

Everything runs offline against the deterministic **mock provider** — no API
keys, no network egress. The mock injects a per-token delay
(`MOCK_TOKEN_DELAY_MS`, default 40 ms) to stand in for real model generation
time, so latency numbers have a realistic shape without a paid backend.

```bash
make up                 # postgres, redis, gateway, refapp, prometheus, grafana
make ingest             # embed the Kubernetes corpus into pgvector
make reset-cache        # flush Redis + restart gateway -> cold cache for a clean run
make bench              # Zipf workload: 400 requests, concurrency 16, s=1.2
make metrics            # raw Prometheus counters from the gateway
```

Grafana (system view) at `http://localhost:3000`, the React quality dashboard at
`http://localhost:5173`.

**Test environment:** single host, Docker Compose, mock provider with 40 ms/token
injected latency, gateway cost model `COST_PER_1K_TOKENS=0.15`. Workload
generator: `refapp/bench/zipf_load.py` (12 paraphrase clusters, one cache
namespace each).

---

## 1. Semantic caching — cost and latency

**Workload.** 400 requests drawn from a Zipf distribution (skew `s=1.2`) over 12
topic clusters, 16 concurrent, starting from a cold cache. Real LLM traffic is
heavy-tailed — a few questions dominate — which is precisely the condition a
semantic cache exploits. Paraphrases within a cluster ("What is a Pod?" /
"Define a pod in k8s") share a namespace and are expected to hit one another
above the cosine threshold.

**Cache hit rate: 85.0%** (340 hits / 60 misses).

**Latency distribution:**

| | p50 | p95 | p99 |
|---|---|---|---|
| Overall | 125 ms | 1210 ms | 1360 ms |
| Cache hit | 122 ms | 207 ms | — |
| Cache miss | 1155 ms | 1360 ms | — |

Median latency reduction on a hit: **(1 − 122/1155) ≈ 89.5%**, i.e. hits return
roughly **9.5× faster** than misses.

**Cost avoided: ~85%.** This is the number to trust — and here's why it's
trustworthy. Two independent cost models were computed:

- The **workload generator** counts tokens by whitespace words and bills only
  misses: `$0.5664` with cache vs `$3.9208` without → **85.6% saved**.
- The **gateway's own Prometheus counters** count tokens by `chars/4` and split
  spend into billed (misses) vs avoided (hits): `$0.7894` billed vs `$4.5714`
  avoided → **85.3% saved**.

The absolute dollar figures differ because the two token estimators differ; the
**percentage saved is identical to within noise** because savings track the hit
rate, not the tokenizer. When quoting a dollar figure, quote it as illustrative;
when quoting the percentage, it's solid.

**Interpretation.** The cache turns a heavy-tailed request stream into mostly
near-instant replays, and the savings — both cost and latency — are governed by
the hit rate. That hit rate is real but *conditioned on the workload*: see the
limitations section for why 85% is a ceiling for this setup, not a universal
claim.

---

## 2. Fault tolerance — fallback and circuit breaker

**Setup.** The primary provider was forced to fail every request
(`PRIMARY_FAULT_RATE=1.0`) while the same 400-request workload ran.

**Result.** **400/400 requests still returned a valid response** — 340 served
from cache, 60 served by the fallback provider. After the failure count crossed
the breaker threshold, the primary's circuit **opened** (visible as
`harbor_provider_breaker_state{provider="mock"} = 2`), so subsequent requests
skipped the known-dead primary instead of paying its timeout. Zero user-facing
errors.

**Interpretation.** This demonstrates the resilience *mechanics*: fallback
before the first token is emitted, a circuit breaker that stops hammering a dead
dependency, and a graceful degraded response if every provider is down (never
cached). The fallback here is a second mock; in production it would be a real
secondary model or provider. What's being proven is the control flow, not the
quality of a specific backup model.

One measured wrinkle worth naming: during the cold-start burst, **59–61 misses
came from only ~34 unique queries** — concurrent duplicates raced before the
first response populated the cache. Harbor does not yet coalesce these
(single-flight); doing so would push the hit rate even higher. It's a known,
understood limitation rather than a surprise.

---

## 3. Evaluation regression gate

**Method.** For each evaluator, candidate scores are compared to a committed
baseline with a **Mann-Whitney U test** (one-sided), gated on a **Cliff's delta**
effect size (|δ| ≥ 0.33) so tiny-but-significant wiggles don't trip it, with
**Holm-Bonferroni** correction across evaluators to control the family-wise error
rate. A regression requires *significance AND a meaningful effect AND a negative
mean delta*. The gate exits non-zero on regression, which fails the GitHub
Actions check.

**Unchanged prompt (should pass):** prompt `v1` vs its own baseline.

| evaluator | base | cand | Δ | p | Cliff's δ | verdict |
|---|---|---|---|---|---|---|
| embedding_similarity | 0.744 | 0.744 | +0.000 | 0.51 | 0.00 | ok |
| keyword_coverage | 0.486 | 0.486 | +0.000 | 0.51 | 0.00 | ok |
| exact_match | 0.000 | 0.000 | +0.000 | — | — | constant; skipped |

→ **gate PASSES.** No false positive.

**Degraded prompt (should fail):** `v2-nocontext`, which drops retrieved context
from the prompt.

| evaluator | base | cand | Δ | p | Cliff's δ | verdict |
|---|---|---|---|---|---|---|
| embedding_similarity | 0.744 | 0.494 | −0.250 | <1e-4 | −1.000 | REGRESSION |
| keyword_coverage | 0.486 | 0.000 | −0.486 | ~5e-4 | −0.667 | REGRESSION |
| exact_match | 0.000 | 0.000 | +0.000 | — | — | constant; skipped |

→ **gate FAILS (exit 1).**

**Interpretation.** The gate distinguishes a genuine quality collapse from
run-to-run noise, and it correctly *ignores* `exact_match`, which is a constant 0
under the mock (there's no signal there, so it shouldn't dilute or fake a
verdict). This is the "safe to change" property: a prompt or model edit that
quietly degrades answers can't merge without a human seeing a red check and the
per-evaluator report.

---

## What these numbers do and don't show

Read this section before quoting anything above.

1. **Miss latency is simulated.** The mock provider injects 40 ms/token to
   emulate generation time, so absolute *miss* latencies are a stand-in, not a
   measurement of any real model. The **hit** path (~120 ms p50) is fully real:
   query embedding + cosine lookup + streamed replay. The relative speedup and
   the caching mechanics are real; the absolute miss number is a placeholder for
   "whatever your model costs."

2. **The 85% hit rate is a ceiling for this setup.** It's produced by heavy skew
   (`s=1.2`) over a small catalog (12 clusters). Lower skew or a broader query
   space lowers it — informal sweeps land roughly in the **40–85%** range
   depending on `s`. Quote it as "up to ~85% on skewed traffic," never as a flat
   guarantee.

3. **Cost is an estimate, not a bill.** Both cost models multiply a token count
   by a fixed price; neither is a real provider invoice. Trust the *percentage*
   (robust across models), treat dollars as illustrative.

4. **No request coalescing yet.** Concurrent duplicate misses aren't single-
   flighted, so cold-start bursts under-count the achievable hit rate.

5. **Single-node cache.** The semantic cache is in-process with Redis
   write-through for warm restarts; it is not yet a shared cache across gateway
   replicas. Horizontal scaling would need a shared vector store or sticky
   routing.

## What would change with a real backend / at scale

- Point `PROVIDER=openai` at OpenAI, Ollama, or vLLM and the same cache/routing/
  fallback logic applies unchanged; miss latency and cost become real.
- Add single-flight coalescing → higher effective hit rate under bursty load.
- Move the vector cache to a shared store (or shard by namespace) → multi-replica
  gateways without duplicated cold starts.
- The eval gate is backend-agnostic; with a real model, the `llm_judge` evaluator
  (which skips gracefully under the mock) also contributes.

---

*All figures above are from a cold-cache run on the mock provider; regenerate
with the commands in "How to reproduce."*
