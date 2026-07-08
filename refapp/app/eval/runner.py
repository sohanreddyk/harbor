"""Eval runner: score the RAG app over a golden dataset and persist results.

For each test case it retrieves context, builds a prompt for the requested
prompt version, calls the gateway, collects the streamed answer, scores it with
every evaluator, and writes an EvalRun + EvalResult rows. Changing the prompt
version or top_k changes the answers — which is exactly how Week 3b demonstrates
a quality regression.
"""
import os
from collections import defaultdict
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.config import settings
from app.db import engine, init_db
from app.embeddings import embed_query
from app.eval.evaluators import DETERMINISTIC, llm_judge
from app.gateway_client import stream_chat
from app.models import EvalResult, EvalRun, EvalSuite, TestCase
from app.retrieval import retrieve_with_vector

# Prompt versions. "v1" is the grounded baseline; "v2-nocontext" deliberately
# drops retrieved context so answers become ungrounded — a controllable
# regression that even the deterministic offline evaluators detect.
PROMPT_TEMPLATES: dict[str, dict] = {
    "v1": {
        "use_context": True,
        "system": (
            "You are Harbor's documentation assistant. Answer using ONLY the "
            "provided context and cite sources with bracketed numbers like [1]."
        ),
    },
    "v2-nocontext": {
        "use_context": False,
        "system": "Answer the question from general knowledge in one sentence.",
    },
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_messages(prompt_version: str, question: str, chunks) -> list[dict]:
    tmpl = PROMPT_TEMPLATES[prompt_version]
    if tmpl["use_context"]:
        ctx = "\n\n".join(f"[{c.rank}] {c.content}" for c in chunks)
        user = f"Context:\n{ctx}\n\nQuestion: {question}"
    else:
        user = f"Question: {question}"
    return [
        {"role": "system", "content": tmpl["system"]},
        {"role": "user", "content": user},
    ]


async def _collect_answer(messages: list[dict], model: str) -> str:
    parts: list[str] = []
    async for delta in stream_chat(messages, model):
        parts.append(delta)
    return "".join(parts)


async def run_suite(
    suite_name: str,
    prompt_version: str = "v1",
    top_k: int = 4,
    model: str | None = None,
    use_judge: bool = False,
    baseline_run_id: int | None = None,
) -> int:
    if prompt_version not in PROMPT_TEMPLATES:
        raise ValueError(f"unknown prompt_version: {prompt_version}")
    init_db()
    model = model or settings.primary_model

    with Session(engine) as session:
        suite = session.exec(select(EvalSuite).where(EvalSuite.name == suite_name)).first()
        if suite is None:
            raise ValueError(f"suite not found: {suite_name} (run `eval seed` first)")
        cases = session.exec(select(TestCase).where(TestCase.suite_id == suite.id)).all()
        if not cases:
            raise ValueError(f"suite {suite_name} has no test cases")

        run = EvalRun(
            suite_id=suite.id, prompt_version=prompt_version, model=model, top_k=top_k,
            git_sha=os.getenv("HARBOR_GIT_SHA"), status="running", num_cases=len(cases),
            baseline_run_id=baseline_run_id, started_at=_utcnow(),
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        per_eval: dict[str, list[float]] = defaultdict(list)
        for case in cases:
            qvec = embed_query(case.question)
            chunks = retrieve_with_vector(session, qvec, top_k)
            messages = build_messages(prompt_version, case.question, chunks)
            answer = await _collect_answer(messages, model)

            scores = {name: fn(answer, case) for name, fn in DETERMINISTIC.items()}
            if use_judge:
                scores["llm_judge"] = await llm_judge(answer, case, model)

            for name, sc in scores.items():
                session.add(EvalResult(
                    run_id=run.id, test_case_id=case.id, evaluator_name=name,
                    score=sc.score, passed=sc.passed, detail=sc.detail,
                ))
                if sc.score is not None:
                    per_eval[name].append(sc.score)
        session.commit()

        per_eval_mean = {k: round(sum(v) / len(v), 4) for k, v in per_eval.items() if v}
        all_scores = [s for v in per_eval.values() for s in v]
        run.per_evaluator = per_eval_mean
        run.mean_score = round(sum(all_scores) / len(all_scores), 4) if all_scores else None
        run.status = "done"
        run.finished_at = _utcnow()
        session.add(run)
        session.commit()
        return run.id


def get_run(run_id: int) -> EvalRun | None:
    with Session(engine) as session:
        return session.get(EvalRun, run_id)


def list_runs(limit: int = 20) -> list[EvalRun]:
    with Session(engine) as session:
        return list(session.exec(
            select(EvalRun).order_by(EvalRun.id.desc()).limit(limit)  # type: ignore[union-attr]
        ).all())
