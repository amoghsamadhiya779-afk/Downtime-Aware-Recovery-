"""`make gen` — regenerate the seeded dev corpus from scratch (n=300, seed=42, S1).

Rerunning this drops and recreates data/dev.db, so `make gen && make eval` always
starts from a clean, reproducible state (Phase 1 acceptance criterion 3).
"""

from __future__ import annotations

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


def main() -> None:
    records, windows, manifest = generate(seed=SEED, n=N, corpus="dev", scenario_id="S1")
    conn = agent_db.reset(DATA_DIR / "dev.db")
    rules = load_rules()
    write_operational_db(conn, records, windows, SEED, rules)
    write_ground_truth(DATA_DIR / "dev_ground_truth.jsonl", records, manifest)

    n_ambiguous = sum(1 for r in records if r.ground_truth.ambiguity == "AMBIGUOUS")
    print(f"generated {N} cases (seed={SEED}) -> {DATA_DIR / 'dev.db'}")
    print(f"  {len(windows)} downtime windows, {n_ambiguous} ambiguous cases")
    print(f"hidden ground truth -> {DATA_DIR / 'dev_ground_truth.jsonl'} (never read by agent/)")


if __name__ == "__main__":
    main()
