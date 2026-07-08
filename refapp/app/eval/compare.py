"""Regression detection: compare a candidate eval run against a baseline.

Why not just compare means? Eval scores are noisy (LLM-judge stochasticity,
sampling variance, non-normal distributions), so a raw mean drop can be noise
and a small consistent drop can hide under an unchanged mean. We therefore use
the Mann-Whitney U test — a non-parametric rank test that makes no normality
assumption — per evaluator, pair it with an effect size (Cliff's delta) so we
only fail on drops that are both statistically significant AND practically
meaningful, and apply a Holm correction because we test several evaluators at
once.

Note: we treat the two runs as independent samples (Mann-Whitney). The scores
happen to be paired by test case, so a Wilcoxon signed-rank test is a valid
alternative; Mann-Whitney is the slightly more conservative choice and matches
the design.
"""
from dataclasses import dataclass, field

from scipy.stats import mannwhitneyu
from sqlmodel import Session, select

from app.db import engine
from app.models import EvalResult, EvalRun

ALPHA = 0.05
# Minimum |Cliff's delta| in the regressive direction to count as a real drop.
# ~0.33 corresponds to a "medium" effect (Romano et al.).
MIN_EFFECT = 0.33


@dataclass
class EvaluatorComparison:
    evaluator: str
    baseline_mean: float
    candidate_mean: float
    mean_delta: float
    p_value: float | None = None
    cliffs_delta: float | None = None
    holm_significant: bool = False
    regression: bool = False
    note: str = ""


@dataclass
class Report:
    comparisons: list[EvaluatorComparison] = field(default_factory=list)
    regression: bool = False
    candidate_label: str = ""
    baseline_label: str = ""


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def cliffs_delta(candidate: list[float], baseline: list[float]) -> float:
    """Dominance measure in [-1, 1]; negative => candidate tends lower."""
    gt = sum(1 for c in candidate for b in baseline if c > b)
    lt = sum(1 for c in candidate for b in baseline if c < b)
    n = len(candidate) * len(baseline)
    return (gt - lt) / n if n else 0.0


def compare_score_sets(
    candidate: dict[str, list[float]],
    baseline: dict[str, list[float]],
    alpha: float = ALPHA,
    min_effect: float = MIN_EFFECT,
) -> Report:
    """Core comparison over {evaluator: [scores]} maps. Pure and testable."""
    report = Report()
    evaluators = sorted(set(baseline) | set(candidate))

    for ev in evaluators:
        base = baseline.get(ev, [])
        cand = candidate.get(ev, [])
        comp = EvaluatorComparison(
            evaluator=ev,
            baseline_mean=round(_mean(base), 4),
            candidate_mean=round(_mean(cand), 4),
            mean_delta=round(_mean(cand) - _mean(base), 4),
        )
        if not base or not cand:
            comp.note = "insufficient data"
            report.comparisons.append(comp)
            continue

        # If every value across both groups is identical there is nothing to test.
        if len(set(base) | set(cand)) == 1:
            comp.note = "constant; no change"
            report.comparisons.append(comp)
            continue

        try:
            # H1: candidate is stochastically LESS than baseline (a regression).
            u, p = mannwhitneyu(cand, base, alternative="less")
            comp.p_value = float(p)
        except ValueError:
            comp.note = "identical distributions"
            report.comparisons.append(comp)
            continue

        comp.cliffs_delta = round(cliffs_delta(cand, base), 4)
        report.comparisons.append(comp)

    _apply_holm(report.comparisons, alpha)

    for comp in report.comparisons:
        comp.regression = (
            comp.holm_significant
            and comp.cliffs_delta is not None
            and comp.cliffs_delta <= -min_effect
            and comp.mean_delta < 0
        )
    report.regression = any(c.regression for c in report.comparisons)
    return report


def _apply_holm(comps: list[EvaluatorComparison], alpha: float) -> None:
    """Holm-Bonferroni step-down across evaluators that produced a p-value."""
    testable = [c for c in comps if c.p_value is not None]
    testable.sort(key=lambda c: c.p_value)  # type: ignore[arg-type,return-value]
    m = len(testable)
    for i, comp in enumerate(testable):
        adjusted = alpha / (m - i)
        if comp.p_value is not None and comp.p_value <= adjusted:
            comp.holm_significant = True
        else:
            break  # step-down: once one fails, the rest are not significant


# ---- DB helpers ----

def fetch_scores(run_id: int) -> dict[str, list[float]]:
    with Session(engine) as session:
        rows = session.exec(
            select(EvalResult.evaluator_name, EvalResult.score).where(
                EvalResult.run_id == run_id, EvalResult.score != None  # noqa: E711
            )
        ).all()
    out: dict[str, list[float]] = {}
    for name, score in rows:
        out.setdefault(name, []).append(float(score))
    return out


def run_label(run_id: int) -> str:
    with Session(engine) as session:
        run = session.get(EvalRun, run_id)
        if run is None:
            return f"run {run_id} (missing)"
        return f"run {run.id} ({run.prompt_version}, top_k={run.top_k})"


def compare_runs(candidate_id: int, baseline_id: int) -> Report:
    report = compare_score_sets(fetch_scores(candidate_id), fetch_scores(baseline_id))
    report.candidate_label = run_label(candidate_id)
    report.baseline_label = run_label(baseline_id)
    return report


# ---- Report formatting ----

def format_report(report: Report) -> str:
    lines = []
    lines.append("\n================= Harbor regression report =================")
    lines.append(f"candidate : {report.candidate_label}")
    lines.append(f"baseline  : {report.baseline_label}")
    lines.append(f"alpha={ALPHA} (Holm-corrected)   min |Cliff's d| = {MIN_EFFECT}")
    lines.append("")
    lines.append(f"{'evaluator':<22}{'base':>7}{'cand':>8}{'delta':>8}{'p-value':>10}{'cliff_d':>9}  verdict")
    for c in report.comparisons:
        p = "  —  " if c.p_value is None else f"{c.p_value:.4f}"
        d = "  —  " if c.cliffs_delta is None else f"{c.cliffs_delta:+.3f}"
        verdict = "REGRESSION" if c.regression else (c.note or "ok")
        lines.append(
            f"{c.evaluator:<22}{c.baseline_mean:>7.3f}{c.candidate_mean:>8.3f}"
            f"{c.mean_delta:>+8.3f}{p:>10}{d:>9}  {verdict}"
        )
    lines.append("")
    if report.regression:
        n = sum(1 for c in report.comparisons if c.regression)
        lines.append(f"VERDICT: REGRESSION DETECTED ({n} evaluator(s)) -> gate FAILS")
    else:
        lines.append("VERDICT: no significant regression -> gate PASSES")
    lines.append("============================================================\n")
    return "\n".join(lines)
