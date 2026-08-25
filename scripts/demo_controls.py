"""Developer & Demo CLI Control Runner for Real Failure Modes.

Usage:
  python scripts/demo_controls.py --scenario duplicate_event
  python scripts/demo_controls.py --scenario invalid_ai_output
  python scripts/demo_controls.py --scenario policy_rejection
  python scripts/demo_controls.py --scenario execution_timeout
  python scripts/demo_controls.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent import db as agent_db
from agent.clock import VirtualClock
from agent.demo_scenarios import run_demo_scenario
from agent.downtime import DowntimeStore
from agent.policy.engine import load_rules


def print_scenario_result(res: dict) -> None:
    scenario = res["scenario"]
    case_id = res["case_id"]
    title = res.get("title", scenario)
    msg = res.get("message", "")
    detail = res.get("detail", {})

    print("\n" + "=" * 70)
    print(f"  DEMO CONTROL: {title.upper()}")
    print("=" * 70)
    print(f"  Scenario:   {scenario}")
    print(f"  Case ID:    {case_id}")
    print(f"  Summary:    {msg}")
    print("-" * 70)

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
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger Real Failure Mode Scenarios")
    parser.add_argument(
        "--scenario",
        type=str,
        choices=["duplicate_event", "invalid_ai_output", "policy_rejection", "execution_timeout"],
        help="The failure mode to trigger",
    )
    parser.add_argument("--all", action="store_true", help="Run all 4 demo scenarios sequentially")
    parser.add_argument("--db", type=str, default=":memory:", help="SQLite database path")
    args = parser.parse_args()

    conn = agent_db.connect(args.db)
    rules = load_rules()
    downtime = DowntimeStore(conn)

    scenarios_to_run = (
        ["duplicate_event", "invalid_ai_output", "policy_rejection", "execution_timeout"]
        if args.all
        else [args.scenario] if args.scenario else ["duplicate_event"]
    )

    for sc in scenarios_to_run:
        result = run_demo_scenario(conn, sc, rules=rules, downtime=downtime)
        print_scenario_result(result)


if __name__ == "__main__":
    main()
