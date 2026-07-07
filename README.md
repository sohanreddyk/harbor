# Harbor

**A self-hostable reliability layer for LLM applications.** Harbor sits between
your app and your model provider and makes LLM traffic cheaper, faster,
observable, safer to change, and more resilient — combining an OpenAI-compatible
gateway, semantic caching, model routing, provider fallback, an evaluation
control plane with CI regression gating, and end-to-end observability in one
system you run yourself.

> Not affiliated with the CNCF "Harbor" container registry.

Harbor ships with a **reference RAG app** (question answering over a Kubernetes
documentation corpus) purely to generate realistic traffic and make the
platform demoable. The engineering substance is the reliability layer.

---

## Architecture (at a glance)

```
React UI ──▶ FastAPI reference app ──▶ Harbor Gateway (Go) ──▶ LLM provider
                    │                          │
              pgvector retrieval        semantic cache · routing · fallback
                                        rate limiting · metrics
                    │
              Control plane: eval suites · regression detection · online drift
```

- **Data plane** — Go gateway: OpenAI-compatible proxy, semantic cache with
  streaming replay, Redis+Lua rate limiting, routing, fallback, circuit
  breaking, metrics.
- **Control plane** — Python/FastAPI/Celery: eval suites over a golden dataset,
  Mann-Whitney U regression detection, GitHub Actions eval gate, online
  quality-drift monitoring.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full design.

---

## Status

**Week 1 — Integration spine.** Reference app → gateway → provider with
end-to-end SSE streaming and a corpus ingested into pgvector. Semantic cache,
routing, eval CI, and observability arrive in later phases.

The gateway defaults to a **deterministic mock provider**, so the whole stack
runs with **no API keys and no network egress**. Point it at any
OpenAI-compatible endpoint (OpenAI, Ollama, vLLM) when you want a real model.

---

## Quickstart

Requirements: Docker + Docker Compose, and Node 18+ (for the frontend).

```bash
# 1. Start postgres, redis, gateway, refapp
make up

# 2. Embed the starter Kubernetes corpus into pgvector
make ingest

# 3. Sanity-check the services
make health
make stats

# 4. Run the chat UI (host)
make fe        # http://localhost:5173
```

Ask *"What is a Pod in Kubernetes?"* and watch the answer stream in with
citations. In mock mode the answer is extracted from the retrieved context.

To use a real model, edit `.env`:

```env
PROVIDER=openai
OPENAI_BASE_URL=https://api.openai.com/v1   # or http://host.docker.internal:11434/v1 for Ollama
OPENAI_API_KEY=sk-...
PRIMARY_MODEL=gpt-4o-mini
```

Then `make up` again.

---

## Services & ports

| Service   | Port | Purpose                                    |
|-----------|------|--------------------------------------------|
| refapp    | 8000 | FastAPI reference app + control-plane host |
| gateway   | 8080 | Go data-plane gateway (OpenAI-compatible)  |
| postgres  | 5432 | pgvector store                             |
| redis     | 6379 | cache + rate-limit backend (Week 2+)       |
| frontend  | 5173 | React chat UI (host dev server)            |

## Repo layout

```
gateway/    Go 1.24 data-plane gateway (stdlib-only in Week 1)
refapp/     FastAPI reference RAG app + ingestion + control plane
frontend/   React + TypeScript + Tailwind chat UI
docs/       Architecture & design documentation
```

## License

MIT.
