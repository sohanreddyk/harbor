"""Harbor eval CLI.

    python -m app.eval.cli seed
    python -m app.eval.cli run --suite k8s-basics --prompt-version v1 --top-k 4
    python -m app.eval.cli run --suite k8s-basics --prompt-version v2-nocontext
    python -m app.eval.cli list
"""
import argparse
import asyncio

from sqlalchemy import func
from sqlmodel import Session, select

from app.db import engine
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


async def _run(args) -> None:
    run_id = await run_suite(
        suite_name=args.suite,
        prompt_version=args.prompt_version,
        top_k=args.top_k,
        model=args.model,
        use_judge=args.judge,
        baseline_run_id=args.baseline,
    )
    _report(run_id)


def _list() -> None:
    runs = list_runs()
    if not runs:
        print("no runs yet")
        return
    print(f"{'id':>4}  {'suite':>5}  {'prompt':<14}  {'mean':>6}  status")
    for r in runs:
        print(f"{r.id:>4}  {r.suite_id:>5}  {r.prompt_version:<14}  {str(r.mean_score):>6}  {r.status}")


def main() -> None:
    p = argparse.ArgumentParser(description="Harbor eval CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="seed the golden dataset")

    r = sub.add_parser("run", help="run an eval suite")
    r.add_argument("--suite", default="k8s-basics")
    r.add_argument("--prompt-version", dest="prompt_version", default="v1",
                   choices=list(PROMPT_TEMPLATES.keys()))
    r.add_argument("--top-k", dest="top_k", type=int, default=4)
    r.add_argument("--model", default=None)
    r.add_argument("--judge", action="store_true", help="also run LLM-as-judge (needs a real provider)")
    r.add_argument("--baseline", type=int, default=None, help="baseline run id to record for comparison")

    sub.add_parser("list", help="list recent runs")

    args = p.parse_args()
    if args.cmd == "seed":
        seed_default()
    elif args.cmd == "run":
        asyncio.run(_run(args))
    elif args.cmd == "list":
        _list()


if __name__ == "__main__":
    main()
