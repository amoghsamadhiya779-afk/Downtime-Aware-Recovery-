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


def make_outcome_fn(ground_truth):
    def outcome_fn(verdict):
        gt = ground_truth.get(verdict.case_id)
        if not gt:
            return 0.5
        if "DOWNTIME_DEFER" in verdict.fired_rules:
            return gt.p_retry_after_downtime
        return gt.p_retry_now

    return outcome_fn


def run(db_path: Path, gt_path: Path, out_path: Path, *, seed: int, provider: str = "stub", output_json: bool = False) -> str:
    load_dotenv()
    if not gt_path.exists() or not db_path.exists():
        raise ConfigurationError(
            f"Evaluation dataset not found at '{gt_path}' or database '{db_path}' missing. "
            f"Please run 'python scripts/gen.py' or 'make gen' first to generate the dataset."
        )

    conn = agent_db.connect(db_path)
    rules = load_rules()
    manifest, ground_truth = read_ground_truth(gt_path)

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
        )
    conn.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    return report


import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay a generated corpus and score it.")
    ap.add_argument("--db", default=str(DATA_DIR / "dev.db"))
    ap.add_argument("--gt", default=str(DATA_DIR / "dev_ground_truth.jsonl"))
    ap.add_argument("--out", default=str(EVAL_DIR / "report.md"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--provider",
        choices=["stub", "baseline", "claude", "groq"],
        default="stub",
        help="diagnosis backend. 'baseline' is the non-AI A1 ablation arm "
             "(context-blind fixed retry) — the thing the AI arms must beat.",
    )
    ap.add_argument("--json", action="store_true", help="Output machine-readable JSON metrics instead of markdown report")
    args = ap.parse_args()
    report = run(Path(args.db), Path(args.gt), Path(args.out), seed=args.seed, provider=args.provider, output_json=args.json)
    print(report)


if __name__ == "__main__":
    main()
