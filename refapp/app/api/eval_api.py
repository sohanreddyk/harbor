"""Read-only control-plane API for the React quality dashboard.

Serves the quality metrics that live in Postgres (eval run history, per-evaluator
means, pass rates) — the counterpart to the system metrics Grafana reads from
Prometheus.
"""
import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import EvalResult, EvalRun, TestCase

router = APIRouter(prefix="/api", tags=["eval"])


def _pass_rates(session: Session) -> tuple[dict[int, int], dict[int, int]]:
    total = dict(session.exec(
        select(EvalResult.run_id, func.count()).where(
            EvalResult.passed != None  # noqa: E711
        ).group_by(EvalResult.run_id)
    ).all())
    passed = dict(session.exec(
        select(EvalResult.run_id, func.count()).where(
            EvalResult.passed == True  # noqa: E712
        ).group_by(EvalResult.run_id)
    ).all())
    return total, passed


@router.get("/eval/runs")
def list_eval_runs(limit: int = 50) -> list[dict]:
    with Session(engine) as session:
        runs = session.exec(
            select(EvalRun).order_by(EvalRun.id.desc()).limit(limit)  # type: ignore[union-attr]
        ).all()
        total, passed = _pass_rates(session)

    out = []
    for r in runs:
        t = total.get(r.id, 0)
        p = passed.get(r.id, 0)
        out.append({
            "id": r.id,
            "suite_id": r.suite_id,
            "prompt_version": r.prompt_version,
            "model": r.model,
            "top_k": r.top_k,
            "status": r.status,
            "num_cases": r.num_cases,
            "mean_score": r.mean_score,
            "per_evaluator": r.per_evaluator,
            "pass_rate": round(p / t, 4) if t else None,
            "git_sha": r.git_sha,
            "baseline_run_id": r.baseline_run_id,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
        })
    return out


@router.get("/eval/runs/{run_id}")
def eval_run_detail(run_id: int) -> dict:
    with Session(engine) as session:
        run = session.get(EvalRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        results = session.exec(select(EvalResult).where(EvalResult.run_id == run_id)).all()
        tc_ids = {r.test_case_id for r in results}
        cases = {
            tc.id: tc for tc in session.exec(
                select(TestCase).where(TestCase.id.in_(tc_ids))  # type: ignore[attr-defined]
            ).all()
        }

    by_case: dict[int, dict] = {}
    for r in results:
        entry = by_case.setdefault(r.test_case_id, {
            "test_case_id": r.test_case_id,
            "question": cases[r.test_case_id].question if r.test_case_id in cases else "",
            "results": [],
        })
        entry["results"].append({
            "evaluator": r.evaluator_name,
            "score": r.score,
            "passed": r.passed,
            "detail": r.detail,
        })
    return {
        "run": {"id": run.id, "prompt_version": run.prompt_version, "mean_score": run.mean_score},
        "cases": list(by_case.values()),
    }


@router.get("/cache/summary")
async def cache_summary() -> dict:
    """Best-effort proxy of the gateway's semantic-cache stats for the UI."""
    url = settings.gateway_url.rstrip("/") + "/v1/cache/stats"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception:  # noqa: BLE001
        return {"entries": None, "total_hits": None}
