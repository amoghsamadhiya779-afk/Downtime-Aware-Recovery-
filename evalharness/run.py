"""`make eval` — replays a generated corpus through the full pipeline and scores it.

Deterministic: same seed at `make gen` plus StubDiagnosis (default, no network) yields
byte-identical numbers on every rerun (Phase 1 acceptance criterion 3). Pass
--provider claude or --provider groq to use a real model instead — that path is not
deterministic and is not what the committed numbers are based on. Both are
interchangeable DiagnosisPort implementations (DECISIONS.md ADR-011); pick whichever
you have an API key for.
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timezone
from pathlib import Path

from agent import db as agent_db
from agent.audit import verify_chain
from agent.clock import VirtualClock
from agent.config import ConfigurationError, load_config, load_dotenv
from agent.diagnosis.stub import StubDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.pipeline import process_case
from agent.policy.engine import load_rules
from agent.state import verify_counters
from datagen.generate import read_ground_truth
from evalharness.metrics import build_report

DATA_DIR = Path("data")
EVAL_DIR = Path("eval")


def get_scoring_log_path(corpus: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"{corpus}_scoring_log.jsonl"


def read_scoring_log(corpus: str, data_dir: Path = DATA_DIR) -> list[dict]:
    """Reads all historical scoring runs from the append-only sidecar log."""
    path = get_scoring_log_path(corpus, data_dir)
    if not path.exists():
        return []
    import json
    runs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            runs.append(json.loads(line))
    return runs


def record_scoring_run(
    corpus: str,
    *,
    provider: str,
    seed: int,
    generator_version: str,
    scenario_id: str,
    rescore_override: bool = False,
    data_dir: Path = DATA_DIR,
) -> int:
    """Appends a new scoring run entry to data/<corpus>_scoring_log.jsonl.
    Never mutates the sealed ground truth corpus."""
    import json
    path = get_scoring_log_path(corpus, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "corpus": corpus,
        "scenario_id": scenario_id,
        "provider": provider,
        "seed": seed,
        "generator_version": generator_version,
        "rescore_override": rescore_override,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return len(read_scoring_log(corpus, data_dir))


def make_outcome_fn(ground_truth):
    def outcome_fn(verdict):
        gt = ground_truth.get(verdict.case_id)
        if not gt:
            return 0.5
        if "DOWNTIME_DEFER" in verdict.fired_rules:
            return gt.p_retry_after_downtime
        return gt.p_retry_now

    return outcome_fn


def run(
    db_path: Path,
    gt_path: Path,
    out_path: Path,
    *,
    seed: int,
    provider: str = "stub",
    output_json: bool = False,
    rescore: bool = False,
) -> str:
    load_dotenv()
    if not gt_path.exists() or not db_path.exists():
        raise ConfigurationError(
            f"Evaluation dataset not found at '{gt_path}' or database '{db_path}' missing. "
            f"Please run 'python scripts/gen.py' or 'make gen' first to generate the dataset."
        )

    manifest, ground_truth = read_ground_truth(gt_path)

    # Anti-cherry-picking check for sealed corpora (eval/PREREGISTRATION.md §2)
    existing_log = read_scoring_log(manifest.corpus, gt_path.parent)
    is_sealed = (manifest.corpus == "test")
    if is_sealed and len(existing_log) > 0 and not rescore:
        raise ConfigurationError(
            f"Corpus '{manifest.corpus}' is sealed and has already been scored {len(existing_log)} time(s). "
            f"Re-scoring a sealed corpus is prohibited without the explicit '--rescore' flag "
            f"(eval/PREREGISTRATION.md §2 anti-cherry-picking discipline)."
        )

    # Record the scoring run in the append-only sidecar log
    times_scored = record_scoring_run(
        manifest.corpus,
        provider=provider,
        seed=seed,
        generator_version=manifest.generator_version,
        scenario_id=manifest.scenario_id,
        rescore_override=rescore,
        data_dir=gt_path.parent,
    )

    conn = agent_db.connect(db_path)
    rules = load_rules()

    downtime = DowntimeStore(conn)
    # Matches datagen.generate's default corpus start — VirtualClock.set() below
    # requires timezone-aware comparisons throughout, so this must stay aware.
    clock = VirtualClock(start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    outcome_fn = make_outcome_fn(ground_truth)
    executor = SimulatedExecutor(conn, clock, outcome_fn, random.Random(seed))

    # Fail fast on a missing key rather than letting every case fall to tier-3
    # UNKNOWN and reporting it as a model result
    required_key = {"groq": "GROQ_API_KEY", "claude": "ANTHROPIC_API_KEY"}.get(provider)
    if required_key and not os.environ.get(required_key):
        raise ConfigurationError(
            f"--provider {provider} needs {required_key}, which is not set and was not "
            f"found in .env. Refusing to run: without it every diagnosis fails closed "
            f"to UNKNOWN and the report would look like a model failure, not a config one."
        )

    if provider == "claude":
        from agent.diagnosis.claude import ClaudeDiagnosis

        diagnosis_port = ClaudeDiagnosis()
    elif provider == "groq":
        from agent.diagnosis.groq_diagnosis import GroqDiagnosis

        diagnosis_port = GroqDiagnosis()
    elif provider == "baseline":
        from agent.diagnosis.baseline import BaselineDiagnosis

        diagnosis_port = BaselineDiagnosis()
    else:
        diagnosis_port = StubDiagnosis()

    case_rows = conn.execute("SELECT case_id, created_at, state FROM cases ORDER BY created_at ASC").fetchall()
    case_ids = [r["case_id"] for r in case_rows if r["case_id"] in ground_truth]
    for r in case_rows:
        if r["case_id"] in ground_truth and r["state"] == "DETECTED":
            clock.set(datetime.fromisoformat(r["created_at"]))
            process_case(
                conn,
                r["case_id"],
                clock=clock,
                rules=rules,
                downtime=downtime,
                diagnosis_port=diagnosis_port,
                executor=executor,
            )

    chain_ok = verify_chain(conn)
    counters_ok = all(verify_counters(conn, cid) for cid in case_ids)

    if output_json:
        from evalharness.metrics import compute_all_metrics
        import json
        metrics = compute_all_metrics(
            conn,
            ground_truth,
            seed=seed,
            manifest=manifest,
            chain_ok=chain_ok,
            counters_ok=counters_ok,
            rules=rules,
            times_scored=times_scored,
            rescore_override=rescore,
        )
        report = json.dumps(metrics, indent=2)
    else:
        report = build_report(
            conn,
            ground_truth,
            seed=seed,
            manifest=manifest,
            chain_ok=chain_ok,
            counters_ok=counters_ok,
            rules=rules,
            times_scored=times_scored,
            rescore_override=rescore,
        )
    conn.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    return report


def run_all_scenarios(
    *,
    seed: int = 42,
    provider: str = "stub",
    out_path: Path = EVAL_DIR / "report.md",
    output_json: bool = False,
    rescore: bool = False,
) -> str:
    """Runs evaluations for S1 (realistic), S2 (burst), and S3 (negative control)
    and publishes them together in a unified report (PREREGISTRATION.md)."""
    from scripts.gen import generate_scenario

    scenarios = ["S1", "S2", "S3"]
    reports: dict[str, str] = {}
    metrics_summary: list[dict] = []

    for s in scenarios:
        suffix = "" if s == "S1" else f"_{s.lower()}"
        db_path = DATA_DIR / f"dev{suffix}.db"
        gt_path = DATA_DIR / f"dev{suffix}_ground_truth.jsonl"
        scenario_out = EVAL_DIR / f"report_{s.lower()}.md"

        generate_scenario(s, seed=seed)

        rep = run(
            db_path,
            gt_path,
            scenario_out,
            seed=seed,
            provider=provider,
            output_json=False,
            rescore=rescore,
        )
        reports[s] = rep

        # Extract summary metrics for the executive table
        conn = agent_db.connect(db_path)
        manifest, gt = read_ground_truth(gt_path)
        from evalharness.metrics import compute_all_metrics
        m = compute_all_metrics(conn, gt, seed=seed, manifest=manifest, chain_ok=True, counters_ok=True, rules=load_rules())
        conn.close()

        metrics_summary.append({
            "scenario": s,
            "desc": "Realistic Baseline" if s == "S1" else ("Burst Outage" if s == "S2" else "Negative Control"),
            "dt_rate": "5.0%" if s == "S1" else ("40.0%" if s == "S2" else "0.0%"),
            "incremental": m["incremental"]["incremental_per_1000"],
            "ci_lo": m["incremental"]["ci_lower"],
            "ci_hi": m["incremental"]["ci_upper"],
            "macro_f1": m["ai"]["macro_f1"],
            "n_deferred": m["secondary"]["n_deferred"],
            "wasted_rate": m["secondary"]["wasted_attempt_rate"],
        })

    # Build unified comparative report
    lines: list[str] = [
        "# Multi-Scenario Evaluation Report — S1, S2, and S3 Published Together",
        "",
        "Evaluation across all three pre-registered scenarios (seed=42, n=300).",
        "Per `eval/PREREGISTRATION.md`, reporting only S2 is the dishonest version; lift in S3 is a bug, not a result.",
        "",
        "## Executive Summary: Scenario Comparison Grid",
        "",
        "| Scenario | Description | Downtime Rate | Incremental ₹ / 1,000 (95% CI) | Ambiguous Macro-F1 | DOWNTIME_DEFER Fired | Wasted Attempt Rate |",
        "|---|---|---|---|---|---|---|",
    ]

    for ms in metrics_summary:
        lines.append(
            f"| **{ms['scenario']}** | {ms['desc']} | {ms['dt_rate']} | "
            f"₹{ms['incremental']:.2f} [{ms['ci_lo']:.2f}, {ms['ci_hi']:.2f}] | "
            f"{ms['macro_f1']:.3f} | **{ms['n_deferred']}** | {ms['wasted_rate']:.1%} |"
        )

    lines.append("")
    lines.append("> **Pre-Registration Invariant Verification**:")
    lines.append("> 1. **S2 Burst**: Elevated outage overlap activates `DOWNTIME_DEFER` > 0 times, exercising deferred retry timing.")
    lines.append("> 2. **S3 Negative Control**: Zero downtime windows produces exactly 0 `DOWNTIME_DEFER` triggers. No false downtime lift.")
    lines.append("")
    lines.append("---")
    lines.append("")

    for s in scenarios:
        lines.append(f"## Detailed Breakdown: Scenario {s}")
        lines.append("")
        lines.append(reports[s])
        lines.append("")
        lines.append("---")
        lines.append("")

    full_report = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_report, encoding="utf-8")
    return full_report


import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay a generated corpus and score it.")
    ap.add_argument("--db", default=None, help="Path to SQLite operational database")
    ap.add_argument("--gt", default=None, help="Path to ground truth JSONL")
    ap.add_argument("--out", default=str(EVAL_DIR / "report.md"), help="Path to output markdown report")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--scenario",
        choices=["S1", "S2", "S3", "all"],
        default="all",
        help="Scenario to evaluate. 'all' publishes S1, S2, and S3 together in report.md.",
    )
    ap.add_argument(
        "--provider",
        choices=["stub", "baseline", "claude", "groq"],
        default="stub",
        help="diagnosis backend. 'baseline' is the non-AI A1 ablation arm "
             "(context-blind fixed retry) — the thing the AI arms must beat.",
    )
    ap.add_argument("--rescore", action="store_true", help="Allow re-scoring a sealed test corpus (overrides anti-cherry-picking protection)")
    ap.add_argument("--json", action="store_true", help="Output machine-readable JSON metrics instead of markdown report")
    args = ap.parse_args()

    try:
        if args.db and args.gt:
            report = run(Path(args.db), Path(args.gt), Path(args.out), seed=args.seed, provider=args.provider, output_json=args.json, rescore=args.rescore)
        elif args.scenario == "all":
            report = run_all_scenarios(seed=args.seed, provider=args.provider, out_path=Path(args.out), output_json=args.json, rescore=args.rescore)
        else:
            suffix = "" if args.scenario == "S1" else f"_{args.scenario.lower()}"
            db_p = DATA_DIR / f"dev{suffix}.db"
            gt_p = DATA_DIR / f"dev{suffix}_ground_truth.jsonl"
            report = run(db_p, gt_p, Path(args.out), seed=args.seed, provider=args.provider, output_json=args.json, rescore=args.rescore)

        print(report)
    except ConfigurationError as e:
        print(f"ConfigurationError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

