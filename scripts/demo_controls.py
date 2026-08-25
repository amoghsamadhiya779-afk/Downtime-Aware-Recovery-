"""Developer & Demo CLI Control Runner for the Three Deterministic Scenarios.

Usage:
  python scripts/demo_controls.py --scenario successful_recovery
  python scripts/demo_controls.py --scenario unsafe_ai_blocked
  python scripts/demo_controls.py --scenario duplicate_timeout_handled
  python scripts/demo_controls.py --all
  python scripts/demo_controls.py --clean
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path when script is executed directly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from agent import db as agent_db
from agent.demo_scenarios import run_demo_scenario
from agent.downtime import DowntimeStore
from agent.policy.engine import load_rules


def print_scenario_result(res: dict) -> None:
    scenario = res["scenario"]
    case_id = res["case_id"]
    title = res.get("title", scenario)
    msg = res.get("message", "")
    detail = res.get("detail", {})

    print("\n" + "=" * 76)
    print(f"  DEMO SCENARIO: {title.upper()}")
    print("=" * 76)
    print(f"  Scenario:   {scenario}")
    print(f"  Case ID:    {case_id}")
    print(f"  Summary:    {msg}")
    print("-" * 76)

    if detail:
        ev = detail.get("event", {})
        ctx = detail.get("context", {})
        diag = detail.get("ai_diagnosis", {})
        evi = detail.get("evidence", {})
        prop = detail.get("proposed_action", {})
        pol = detail.get("policy_result", {})
        exec_info = detail.get("execution", {})
        out = detail.get("outcome", {})
        aud = detail.get("audit_trail", {})

        print("  9-PHASE TRANSACTION LIFECYCLE:")
        print(f"  1. EVENT:           Method={ev.get('method')}, Amount=INR {ev.get('amount_rupees')}, Reason={ev.get('error_reason')}")
        print(f"  2. CONTEXT:         Cohort={ctx.get('cohort')}, Attempt={ctx.get('attempt_no')}, Ambiguous={ctx.get('triage_is_ambiguous')}")
        print(f"  3. AI DIAGNOSIS:    Class={diag.get('recoverability')}, Conf={diag.get('confidence_pct')}%, Tier={diag.get('fallback_tier')}")
        print(f"  4. EVIDENCE:        Grounded={evi.get('is_grounded')}, Cited={evi.get('cited_fields')}")
        print(f"  5. PROPOSAL:        Action={prop.get('proposed_action')}, Delay={prop.get('proposed_delay_minutes')}m, P(succ)={prop.get('expected_success_probability_pct')}%")
        print(f"  6. POLICY VERDICT:  Decision={pol.get('policy_decision')}, Action={pol.get('authorized_action')}, FiredRules={pol.get('fired_rules')}")
        print(f"  7. EXECUTION:       Dispatched={exec_info.get('is_dispatched')}, Mode={exec_info.get('execution_mode')}, Replayed={exec_info.get('replayed')}")
        print(f"  8. OUTCOME:         FinalState={out.get('final_state')}, Status={out.get('outcome_status')}, Succeeded={out.get('succeeded')}")
        print(f"  9. AUDIT TRAIL:     ChainVerified={aud.get('chain_valid')}, TotalEvents={aud.get('total_events')}")
    print("=" * 76 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger Exactly Three Deterministic Demo Scenarios")
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        help="Scenario to trigger: 'successful_recovery' (1), 'unsafe_ai_blocked' (2), 'duplicate_timeout_handled' (3), or 'all'",
    )
    parser.add_argument("--all", action="store_true", help="Run all 3 deterministic scenarios sequentially")
    parser.add_argument("--clean", action="store_true", default=True, help="Run against a clean in-memory database state")
    parser.add_argument("--db", type=str, default=None, help="Optional SQLite database path (defaults to :memory: for clean state)")
    args = parser.parse_args()

    db_target = args.db if args.db else ":memory:"
    conn = agent_db.connect(db_target)
    rules = load_rules()
    downtime = DowntimeStore(conn)

    canonical_scenarios = [
        "successful_recovery",
        "unsafe_ai_blocked",
        "duplicate_timeout_handled",
    ]

    if args.all or args.scenario == "all":
        scenarios_to_run = canonical_scenarios
    else:
        scenarios_to_run = [args.scenario]

    for sc in scenarios_to_run:
        result = run_demo_scenario(conn, sc, rules=rules, downtime=downtime)
        print_scenario_result(result)


if __name__ == "__main__":
    main()
