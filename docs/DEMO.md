# Harbor — 2-minute demo script

A tight screen-recording walkthrough that shows the four things that matter:
caching, resilience, quality gating, and the UI. Keep it under ~2:30. Have
`make up` already running and the corpus ingested before you hit record.

**Pre-roll (do this before recording):**

```bash
make up && make ingest
make fe        # leave the UI open at http://localhost:5173
```

---

## Scene 1 — What it is (0:00–0:20)

On the chat UI, say:

> "This is Harbor — a self-hosted reliability layer that sits between an app and
> any LLM provider. Everything you'll see runs offline against a mock model; the
> same code works against OpenAI or a local vLLM."

Ask **"What is a Pod in Kubernetes?"** Let it stream. Point at the badge row:

> "The answer streams back with citations, and this telemetry — cache miss,
> route, provider — is read straight from the gateway's response headers."

## Scene 2 — The cache (0:20–0:50)

Ask a paraphrase: **"Can you explain what a pod is?"**

> "Same question, different words. It's a **cache hit** with a similarity score —
> served from a semantic cache in about 120 milliseconds instead of a full
> generation."

Switch to a terminal:

```bash
make reset-cache
make bench
```

Read the summary out loud:

> "Over 400 skewed requests: 85% hit rate, hits about 9.5× faster than misses,
> and roughly 85% of token spend avoided."

## Scene 3 — Resilience (0:50–1:25)

```bash
make grafana        # open the Grafana URL it prints
```

Show the dashboard (ideally right after the bench, so the gauge is live):

> "Real Prometheus metrics — request rate by cache status, latency percentiles,
> cost saved, breaker state."

Then kill the primary provider and re-run:

```bash
PRIMARY_FAULT_RATE=1.0 make up
make bench
make providers
```

> "I've forced the primary provider to fail 100% of requests. Every request
> still succeeds — served from cache or a fallback provider — and the primary's
> circuit breaker has opened. Zero user-facing errors during a total outage."

Reset it afterward: `make up` (with `PRIMARY_FAULT_RATE=0` in `.env`).

## Scene 4 — Safe to change (1:25–2:00)

```bash
make eval-gate
```

> "This is the evaluation gate. A candidate prompt is scored against a golden
> dataset and compared to a committed baseline with a Mann-Whitney U test plus an
> effect-size threshold. Unchanged prompt — it passes."

```bash
make eval-gate-bad
```

> "Now a prompt that drops the retrieved context. The gate detects the quality
> collapse — significant, large effect — and **exits non-zero**. In CI that's a
> red check that blocks the merge."

## Scene 5 — Close (2:00–2:20)

Flip to the **Quality** tab in the UI.

> "The quality dashboard tracks eval runs over time — you can see exactly where
> that bad prompt tanked the scores. Gateway in Go, control plane in Python,
> React front end, fully containerized with Prometheus and Grafana. That's
> Harbor."

---

### Recording tips
- Terminal font large; light or dark UI theme, your call (dark reads better on
  video).
- Pre-run each command once so Docker images are warm and there's no wait.
- If you want the Grafana hit-ratio gauge non-zero on camera, screen-record
  within ~30s of `make bench` (the gauge is a 5-minute rate).
