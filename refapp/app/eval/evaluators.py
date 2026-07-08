"""Evaluator framework.

Each evaluator scores a generated answer against a test case, returning a score
in [0, 1], a pass/fail, and a detail dict. Deterministic evaluators (exact
match, keyword coverage, embedding similarity) need no model and run offline;
the LLM-as-judge evaluator calls the gateway and is used when a real provider is
configured (it degrades to "skipped" when the response isn't valid JSON, e.g.
against the mock provider).
"""
import json
import re
from dataclasses import dataclass, field

from app.embeddings import embed_passages
from app.gateway_client import stream_chat
from app.models import TestCase

# Pass thresholds per evaluator.
KEYWORD_PASS = 0.6
EMBEDDING_PASS = 0.70
JUDGE_PASS = 0.6


@dataclass
class Score:
    score: float | None          # None => evaluator skipped
    passed: bool | None
    detail: dict = field(default_factory=dict)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def exact_match(answer: str, case: TestCase) -> Score:
    hit = _norm(answer) == _norm(case.gold_answer)
    return Score(1.0 if hit else 0.0, hit, {})


def keyword_coverage(answer: str, case: TestCase) -> Score:
    kws = case.gold_keywords or []
    if not kws:
        return Score(None, None, {"skipped": "no gold_keywords"})
    low = answer.lower()
    present = [kw for kw in kws if kw.lower() in low]
    cov = len(present) / len(kws)
    return Score(round(cov, 4), cov >= KEYWORD_PASS,
                 {"present": present, "missing": [k for k in kws if k not in present]})


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def embedding_similarity(answer: str, case: TestCase) -> Score:
    vecs = embed_passages([answer, case.gold_answer])
    sim = _cosine(vecs[0], vecs[1])
    sim = max(0.0, min(1.0, sim))
    return Score(round(sim, 4), sim >= EMBEDDING_PASS, {"cosine": round(sim, 4)})


# name -> deterministic evaluator fn
DETERMINISTIC = {
    "exact_match": exact_match,
    "keyword_coverage": keyword_coverage,
    "embedding_similarity": embedding_similarity,
}


_JUDGE_SYSTEM = (
    "You are a strict grader. Compare the candidate answer to the reference "
    "answer for the given question. Respond with ONLY a JSON object of the form "
    '{"score": <float 0..1>, "reason": "<short reason>"} and nothing else.'
)


def _extract_json(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


async def llm_judge(answer: str, case: TestCase, model: str) -> Score:
    """LLM-as-judge via the gateway. Skips gracefully on non-JSON output."""
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": (
            f"Question: {case.question}\n\n"
            f"Reference answer: {case.gold_answer}\n\n"
            f"Candidate answer: {answer}"
        )},
    ]
    parts = []
    try:
        async for delta in stream_chat(messages, model):
            parts.append(delta)
    except Exception as exc:  # noqa: BLE001
        return Score(None, None, {"skipped": f"judge call failed: {exc}"})

    parsed = _extract_json("".join(parts))
    if parsed is None or "score" not in parsed:
        return Score(None, None, {"skipped": "non-JSON judge response"})
    try:
        val = max(0.0, min(1.0, float(parsed["score"])))
    except (TypeError, ValueError):
        return Score(None, None, {"skipped": "bad score field"})
    return Score(round(val, 4), val >= JUDGE_PASS, {"reason": parsed.get("reason", "")})
