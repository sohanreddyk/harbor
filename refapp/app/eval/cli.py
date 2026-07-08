"""Harbor eval CLI.

    python -m app.eval.cli seed
    python -m app.eval.cli run --suite k8s-basics --prompt-version v1
    python -m app.eval.cli list
    python -m app.eval.cli compare --candidate 2 --baseline 1
    python -m app.eval.cli snapshot --run 1 --out eval/baseline.json
    python -m app.eval.cli gate --prompt-version v1 --baseline-file eval/baseline.json
"""
import argparse
import asyncio
import json
import sys

from sqlalchemy import func
from sqlmodel import Session, select

from app.db import engine
from app.eval.compare import (
    compare_runs,
    compare_score_sets,
    fetch_scores,
    format_report,
    run_label,
)
from app.eval.runner import PROMPT_TEMPLATES, list_runs, run_suite
from app.eval.seed import seed_default
from app.models import EvalResult, EvalRun


def _report(run_id: int) -> None:
    with Session(engine) as session:
        run = session.get(EvalRun, run_id)
        if run is None:
            print(f"run {run_id} not found")
            return
        print("\n================ Harbor eval run ================")
        print(f"run id         : {run.id}")
        print(f"suite / prompt : {run.suite_id} / {run.prompt_version}   top_k={run.top_k}")
        print(f"model          : {run.model}")
        print(f"cases          : {run.num_cases}")
        print(f"overall mean   : {run.mean_score}")
        print("per-evaluator  :")
        for name, mean in sorted(run.per_evaluator.items()):
            passed = session.exec(
                select(func.count()).select_from(EvalResult).where(
                    EvalResult.run_id == run.id,
                    EvalResult.evaluator_name == name,
                    EvalResult.passed == True,  # noqa: E712
                )
            ).one()
            print(f"    {name:<22} mean={mean:<8} passed={passed}/{run.num_cases}")
        print("=================================================\n")


async def _run(args) -> int:
    run_id = await run_suite(
        suite_name=args.suite, prompt_version=args.prompt_version, top_k=args.top_k,
        model=args.model, use_judge=args.judge, baseline_run_id=args.baseline,
    )
    _report(run_id)
    return run_id


def _list() -> None:
    runs = list_runs()
    if not runs:
        print("no runs yet")
        return
    print(f"{'id':>4}  {'suite':>5}  {'prompt':<14}  {'mean':>6}  status")
    for r in runs:
        print(f"{r.id:>4}  {r.suite_id:>5}  {r.prompt_version:<14}  {str(r.mean_score):>6}  {r.status}")


def _compare(args) -> None:
    if args.baseline_file:
        with open(args.baseline_file) as f:
            baseline = json.load(f)["scores"]
        report = compare_score_sets(fetch_scores(args.candidate), baseline)
        report.candidate_label = run_label(args.candidate)
        report.baseline_label = f"baseline file {args.baseline_file}"
    else:
        report = compare_runs(args.candidate, args.baseline)
    print(format_report(report))
    if args.fail_on_regression and report.regression:
        sys.exit(1)


def _snapshot(args) -> None:
    scores = fetch_scores(args.run)
    with Session(engine) as session:
        run = session.get(EvalRun, args.run)
    payload = {
        "run_id": args.run,
        "suite_id": run.suite_id if run else None,
        "prompt_version": run.prompt_version if run else None,
        "scores": scores,
    }
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"wrote baseline snapshot ({sum(len(v) for v in scores.values())} scores) to {args.out}")


async def _gate(args) -> None:
    # Fresh candidate run with the current prompt config...
    candidate_id = await run_suite(
        suite_name=args.suite, prompt_version=args.prompt_version, top_k=args.top_k,
    )
    _report(candidate_id)
    # ...compared against the committed baseline snapshot.
    with open(args.baseline_file) as f:
        baseline = json.load(f)["scores"]
    report = compare_score_sets(fetch_scores(candidate_id), baseline)
    report.candidate_label = run_label(candidate_id)
    report.baseline_label = f"baseline file {args.baseline_file}"
    text = format_report(report)
    print(text)
    if args.report_out:
        with open(args.report_out, "w") as f:
            f.write(text)
    if report.regression:
        sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="Harbor eval CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="seed the golden dataset")
    sub.add_parser("list", help="list recent runs")

    r = sub.add_parser("run", help="run an eval suite")
    r.add_argument("--suite", default="k8s-basics")
    r.add_argument("--prompt-version", dest="prompt_version", default="v1", choices=list(PROMPT_TEMPLATES))
    r.add_argument("--top-k", dest="top_k", type=int, default=4)
    r.add_argument("--model", default=None)
    r.add_argument("--judge", action="store_true", help="also run LLM-as-judge (needs a real provider)")
    r.add_argument("--baseline", type=int, default=None, help="baseline run id to record")

    c = sub.add_parser("compare", help="compare a candidate run against a baseline")
    c.add_argument("--candidate", type=int, required=True)
    c.add_argument("--baseline", type=int, help="baseline run id (DB)")
    c.add_argument("--baseline-file", dest="baseline_file", help="baseline snapshot JSON")
    c.add_argument("--fail-on-regression", dest="fail_on_regression", action="store_true")

    s = sub.add_parser("snapshot", help="dump a run's per-case scores to a baseline file")
    s.add_argument("--run", type=int, required=True)
    s.add_argument("--out", required=True)

    g = sub.add_parser("gate", help="run the suite and fail if it regresses vs a baseline file")
    g.add_argument("--suite", default="k8s-basics")
    g.add_argument("--prompt-version", dest="prompt_version", default="v1", choices=list(PROMPT_TEMPLATES))
    g.add_argument("--top-k", dest="top_k", type=int, default=4)
    g.add_argument("--baseline-file", dest="baseline_file", required=True)
    g.add_argument("--report-out", dest="report_out", default=None)

    args = p.parse_args()
    if args.cmd == "seed":
        seed_default()
    elif args.cmd == "run":
        asyncio.run(_run(args))
    elif args.cmd == "list":
        _list()
    elif args.cmd == "compare":
        _compare(args)
    elif args.cmd == "snapshot":
        _snapshot(args)
    elif args.cmd == "gate":
        asyncio.run(_gate(args))


if __name__ == "__main__":
    main()
