"""Zipf-distributed workload generator for the Harbor gateway.

Real LLM traffic is heavy-tailed: a handful of questions dominate, which is
exactly what makes a semantic cache pay off. This tool draws requests from a
catalog of paraphrase clusters using a Zipf distribution (tunable skew), sends
them through the gateway, and reports cache hit rate, latency percentiles, and
estimated cost savings — real numbers, not assertions.

Run inside the refapp container (it has fastembed + httpx + numpy):

    docker compose exec refapp python bench/zipf_load.py --n 400 --concurrency 16 --zipf-s 1.2

Each cluster shares a fixed context, so paraphrases land in the same cache
namespace and can semantically hit one another above the gateway threshold.
"""
import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.embeddings import embed_query  # noqa: E402

SYSTEM = (
    "You are Harbor's documentation assistant. Answer using ONLY the provided "
    "context and cite sources like [1]."
)

# (fixed_context, [paraphrases]) — one namespace per cluster.
CLUSTERS: list[tuple[str, list[str]]] = [
    ("A Pod is the smallest deployable unit in Kubernetes and wraps one or more containers.",
     ["What is a Pod?", "Can you explain what a Kubernetes Pod is?",
      "Define a pod in k8s", "What does a Pod represent in Kubernetes?"]),
    ("A Deployment provides declarative updates for Pods and manages ReplicaSets for rolling updates.",
     ["How do Deployments work?", "What is a Kubernetes Deployment?",
      "Explain rolling updates in a Deployment", "How does a Deployment roll out changes?"]),
    ("A Service exposes a stable network endpoint and load-balances across the Pods it selects.",
     ["What is a Service?", "How does a Kubernetes Service work?",
      "Explain Service types", "What does a Service do in k8s?"]),
    ("A ReplicaSet maintains a stable set of replica Pods running at any given time.",
     ["What is a ReplicaSet?", "What does a ReplicaSet do?",
      "Explain ReplicaSets in Kubernetes"]),
    ("A ConfigMap stores non-confidential configuration data as key-value pairs.",
     ["What is a ConfigMap?", "How do ConfigMaps work?",
      "Explain ConfigMaps in Kubernetes"]),
    ("A namespace provides a scope for names and divides cluster resources between users.",
     ["What is a namespace?", "What are Kubernetes namespaces for?",
      "Explain namespaces in k8s"]),
    ("A HorizontalPodAutoscaler scales the replica count based on observed metrics like CPU.",
     ["What is an HPA?", "How does the HorizontalPodAutoscaler work?",
      "Explain autoscaling in Kubernetes"]),
    ("A StatefulSet manages stateful applications and gives Pods stable identities.",
     ["What is a StatefulSet?", "When should I use a StatefulSet?"]),
    ("A DaemonSet ensures a copy of a Pod runs on all (or some) nodes.",
     ["What is a DaemonSet?", "What does a DaemonSet do?"]),
    ("An Ingress manages external HTTP access to Services with host and path routing.",
     ["What is an Ingress?", "How does Ingress routing work?"]),
    ("A PersistentVolume is cluster storage provisioned independently of any Pod.",
     ["What is a PersistentVolume?", "Explain PersistentVolumes"]),
    ("Liveness and readiness probes let the kubelet decide when to restart or route traffic.",
     ["What are liveness and readiness probes?", "How do health probes work in k8s?"]),
]


def zipf_weights(n: int, s: float) -> np.ndarray:
    ranks = np.arange(1, n + 1, dtype=float)
    w = 1.0 / np.power(ranks, s)
    return w / w.sum()


def approx_tokens(text: str) -> int:
    return max(1, len(text.split()))


async def one_request(client: httpx.AsyncClient, url: str, cid: int, question: str,
                      context: str, embedding: list) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Context:\n[1] {context}\n\nQuestion: {question}"},
    ]
    payload = {
        "model": "bench-model",
        "stream": True,
        "messages": messages,
        "harbor": {
            "embedding": embedding,
            "context_hash": f"cluster-{cid}",
            "prompt_version": "v1",
        },
    }
    prompt_toks = approx_tokens(messages[0]["content"] + messages[1]["content"])
    start = time.perf_counter()
    completion = []
    cache_status = "unknown"
    async with client.stream("POST", url, json=payload) as resp:
        cache_status = resp.headers.get("X-Harbor-Cache", "unknown")
        async for line in resp.aiter_lines():
            if line.startswith("data:") and '"content"' in line:
                completion.append(line)
    latency_ms = (time.perf_counter() - start) * 1000.0
    return {
        "cache": cache_status,
        "latency_ms": latency_ms,
        "prompt_tokens": prompt_toks,
        "completion_tokens": len(completion),
    }


async def run(args) -> None:
    url = args.gateway_url.rstrip("/") + "/v1/chat/completions"
    weights = zipf_weights(len(CLUSTERS), args.zipf_s)
    rng = np.random.default_rng(args.seed)
    cluster_ids = rng.choice(len(CLUSTERS), size=args.n, p=weights)

    # Build the full request plan first, then precompute every embedding BEFORE
    # the timed phase. embed_query is CPU-bound and blocking; doing it inside
    # the async workers would starve the event loop and inflate the measured
    # latency of concurrent requests. Here it never touches the timed path, so
    # latency reflects pure gateway (cache vs provider) behaviour.
    plan: list[tuple[int, str, str]] = []
    for c in cluster_ids:
        cid = int(c)
        context, paras = CLUSTERS[cid]
        question = paras[int(rng.integers(len(paras)))]
        plan.append((cid, question, context))

    unique_questions = sorted({q for _, q, _ in plan})
    print(f"Precomputing {len(unique_questions)} embeddings (off the timed path) ...")
    emb_map = {q: embed_query(q) for q in unique_questions}

    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []

    print(f"Sending {len(plan)} requests to {url} ...")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async def worker(cid: int, question: str, context: str):
            async with sem:
                results.append(
                    await one_request(client, url, cid, question, context, emb_map[question])
                )

        await asyncio.gather(*(worker(cid, q, ctx) for cid, q, ctx in plan))

    summarize(results, args)


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(values, p))


def summarize(results: list[dict], args) -> None:
    n = len(results)
    hits = [r for r in results if r["cache"] == "hit"]
    misses = [r for r in results if r["cache"] == "miss"]
    hit_rate = len(hits) / n if n else 0.0

    all_lat = [r["latency_ms"] for r in results]
    hit_lat = [r["latency_ms"] for r in hits]
    miss_lat = [r["latency_ms"] for r in misses]

    # Cost model: a hit costs ~nothing; a miss costs (prompt+completion) tokens.
    price = args.price_per_1k
    def cost(r: dict) -> float:
        return (r["prompt_tokens"] + r["completion_tokens"]) / 1000.0 * price

    spend_with_cache = sum(cost(r) for r in misses)
    spend_without_cache = sum(cost(r) for r in results)
    saved_pct = (1 - spend_with_cache / spend_without_cache) * 100 if spend_without_cache else 0.0

    print("\n================ Harbor workload summary ================")
    print(f"requests            : {n}  (zipf s={args.zipf_s}, concurrency={args.concurrency})")
    print(f"cache hit rate      : {hit_rate*100:.1f}%  ({len(hits)} hits / {len(misses)} misses)")
    print(f"latency p50/p95/p99 : {pct(all_lat,50):.0f} / {pct(all_lat,95):.0f} / {pct(all_lat,99):.0f} ms")
    if hit_lat:
        print(f"  hit  p50/p95      : {pct(hit_lat,50):.0f} / {pct(hit_lat,95):.0f} ms")
    if miss_lat:
        print(f"  miss p50/p95      : {pct(miss_lat,50):.0f} / {pct(miss_lat,95):.0f} ms")
    if hit_lat and miss_lat:
        print(f"  latency reduction : {(1 - statistics.median(hit_lat)/statistics.median(miss_lat))*100:.1f}% (median)")
    print(f"est. spend w/ cache : ${spend_with_cache:.4f}")
    print(f"est. spend no cache : ${spend_without_cache:.4f}")
    print(f"est. cost saved     : {saved_pct:.1f}%")
    print("=========================================================\n")

    if args.out:
        import csv
        with open(args.out, "w", newline="") as f:
            wtr = csv.DictWriter(f, fieldnames=["cache", "latency_ms", "prompt_tokens", "completion_tokens"])
            wtr.writeheader()
            wtr.writerows(results)
        print(f"per-request rows written to {args.out}")


def parse_args():
    p = argparse.ArgumentParser(description="Harbor Zipf workload generator")
    p.add_argument("--n", type=int, default=400, help="number of requests")
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument("--zipf-s", dest="zipf_s", type=float, default=1.2, help="Zipf skew; higher = more repeats")
    p.add_argument("--gateway-url", default="http://gateway:8080")
    p.add_argument("--price-per-1k", dest="price_per_1k", type=float, default=0.15, help="USD per 1K tokens")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="", help="optional CSV output path")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
