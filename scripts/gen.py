"""`python scripts/gen.py` — Seeded synthetic corpus generator for S1, S2, and S3 scenarios.

Scenarios:
  S1: Realistic baseline downtime rate (downtime_rate=0.05) -> data/dev.db & data/dev_ground_truth.jsonl
  S2: Burst outage scenario with elevated downtime (downtime_rate=0.40) -> data/dev_s2.db & data/dev_s2_ground_truth.jsonl
  S3: Negative control with zero downtime (downtime_rate=0.0) -> data/dev_s3.db & data/dev_s3_ground_truth.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path when script is executed directly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent import db as agent_db
from agent.policy.engine import load_rules
from datagen.generate import generate, write_ground_truth, write_operational_db

DATA_DIR = Path("data")
SEED = 42
N = 300


def generate_scenario(
    scenario_id: str,
    *,
    seed: int = SEED,
    n: int = N,
    corpus: str = "dev",
) -> tuple[Path, Path, int, int]:
    """Generates a scenario and writes its operational DB and hidden ground truth."""
    records, windows, manifest = generate(seed=seed, n=n, corpus=corpus, scenario_id=scenario_id)
    rules = load_rules()

    suffix = "" if scenario_id == "S1" else f"_{scenario_id.lower()}"
    db_path = DATA_DIR / f"{corpus}{suffix}.db"
    gt_path = DATA_DIR / f"{corpus}{suffix}_ground_truth.jsonl"

    conn = agent_db.reset(db_path)
    write_operational_db(conn, records, windows, seed, rules)
    write_ground_truth(gt_path, records, manifest)

    n_ambiguous = sum(1 for r in records if r.ground_truth.ambiguity == "AMBIGUOUS")
    print(f"Scenario {scenario_id}: generated {n} cases (seed={seed}) -> {db_path}")
    print(f"  {len(windows)} downtime windows, {n_ambiguous} ambiguous cases")
    print(f"  ground truth -> {gt_path}")

    # Also maintain data/dev_s1.db alias if S1 for explicit scenario paths
    if scenario_id == "S1":
        s1_db = DATA_DIR / f"{corpus}_s1.db"
        s1_gt = DATA_DIR / f"{corpus}_s1_ground_truth.jsonl"
        conn_s1 = agent_db.reset(s1_db)
        write_operational_db(conn_s1, records, windows, seed, rules)
        write_ground_truth(s1_gt, records, manifest)

    return db_path, gt_path, len(windows), n_ambiguous


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic dataset for recovery control plane.")
    parser.add_argument(
        "--corpus",
        "-c",
        choices=["dev", "test", "calibration", "all"],
        default="all",
        help="Corpus to generate: dev (n=300, seed=42), test (n=1000, seed=777042), calibration (n=500), or all (default: all)",
    )
    parser.add_argument(
        "--scenario",
        "-s",
        choices=["S1", "S2", "S3", "all"],
        default="all",
        help="Scenario to generate: S1 (realistic), S2 (burst outage), S3 (negative control), or all (default: all)",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed override")
    parser.add_argument("--n", type=int, default=None, help="Number of records override")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    corpora_configs = {
        "dev": {"seed": args.seed or 42, "n": args.n or 300},
        "test": {"seed": args.seed or 777042, "n": args.n or 1000},  # Fresh unburned seed for test corpus
        "calibration": {"seed": args.seed or 12345, "n": args.n or 500},
    }

    target_corpora = list(corpora_configs.keys()) if args.corpus == "all" else [args.corpus]
    target_scenarios = ["S1", "S2", "S3"] if args.scenario == "all" else [args.scenario]

    for c in target_corpora:
        cfg = corpora_configs[c]
        for s in target_scenarios:
            generate_scenario(s, seed=cfg["seed"], n=cfg["n"], corpus=c)


if __name__ == "__main__":
    main()


