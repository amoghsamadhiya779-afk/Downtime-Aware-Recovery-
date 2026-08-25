"""Benchmark script to run the evaluation on a held-out dataset and compare baseline vs AI."""

import json
import logging
import sys
from pathlib import Path

# Ensure the project root is in sys.path so imports like 'agent' work when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import db as agent_db
from agent.policy.engine import load_rules
from datagen.generate import generate, write_ground_truth, write_operational_db
from evalharness.run import run

DATA_DIR = Path("data")

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    # Requirements: held-out dataset, reproducible results
    seed = 777001
    n = 1000
    corpus = "test"
    scenario = "S1"
    
    db_path = DATA_DIR / "eval.db"
    gt_path = DATA_DIR / "eval_ground_truth.jsonl"
    out_baseline = DATA_DIR / "benchmark_baseline.json"
    out_ai = DATA_DIR / "benchmark_ai.json"
    
    logging.info(f"Generating held-out dataset (n={n}, seed={seed})...")
    records, windows, manifest = generate(seed=seed, n=n, corpus=corpus, scenario_id=scenario)
    conn = agent_db.reset(db_path)
    rules = load_rules()
    write_operational_db(conn, records, windows, seed, rules)
    write_ground_truth(gt_path, records, manifest)
    conn.close()

    logging.info("Running baseline provider...")
    # Baseline comparison
    baseline_report_str = run(
        db_path=db_path,
        gt_path=gt_path,
        out_path=out_baseline,
        seed=seed,
        provider="baseline",
        output_json=True
    )
    baseline_metrics = json.loads(baseline_report_str)

    logging.info("Resetting operational DB for AI run...")
    conn = agent_db.reset(db_path)
    write_operational_db(conn, records, windows, seed, rules)
    conn.close()

    logging.info("Running AI (stub) provider...")
    # AI provider (stub used here to avoid API dependency, can be changed via args if needed)
    ai_report_str = run(
        db_path=db_path,
        gt_path=gt_path,
        out_path=out_ai,
        seed=seed,
        provider="stub",
        output_json=True
    )
    ai_metrics = json.loads(ai_report_str)
    
    # Calculate Deltas
    baseline_inc = baseline_metrics["incremental"]["incremental_per_1000"]
    ai_inc = ai_metrics["incremental"]["incremental_per_1000"]
    
    result = {
        "benchmark_config": {
            "corpus": corpus,
            "seed": seed,
            "n": n,
            "scenario": scenario
        },
        "baseline_metrics": baseline_metrics,
        "ai_metrics": ai_metrics,
        "comparison": {
            "ai_incremental_rupees_per_1000": ai_inc,
            "baseline_incremental_rupees_per_1000": baseline_inc,
            "lift_over_baseline": ai_inc - baseline_inc,
            "ai_macro_f1": ai_metrics["ai"]["macro_f1"],
            "baseline_macro_f1": baseline_metrics["ai"]["macro_f1"],
        }
    }
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
