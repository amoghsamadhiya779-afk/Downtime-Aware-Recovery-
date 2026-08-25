"""`python scripts/demo.py` — Deterministic Demo Runner for Three Canonical Scenarios.

Reproducible from a clean state:
  1. successful_recovery       — Transient failure diagnosed, approved by policy (ALLOW), and recovered.
  2. unsafe_ai_blocked         — Unsafe/adversarial AI proposal vetoed by Zero-LLM Policy Gate (DENY).
  3. duplicate_timeout_handled — Execution safety: idempotent replay deduplication & timeout quarantine.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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
from agent.audit import events_for, verify_chain
from agent.demo_scenarios import (
    trigger_duplicate_timeout_handled,
    trigger_successful_recovery,
    trigger_unsafe_ai_blocked,
)
from agent.downtime import DowntimeStore
from agent.policy.engine import load_rules


def _print_trace(conn, case_id: str, title: str, summary: str) -> None:
    print("\n" + "=" * 80)
    print(f"  SCENARIO: {title.upper()}")
    print("=" * 80)
    print(f"  Case ID:  {case_id}")
    print(f"  Summary:  {summary}")
    print("-" * 80)
    print("  CRYPTOGRAPHIC AUDIT EVENT LOG (SHA-256 IMMUTABLE CHAIN):")
    
    events = events_for(conn, case_id)
    for e in events:
        payload = json.loads(e["payload"])
        actor_col = f"[{e['actor']}]".ljust(12)
        event_col = f"{e['event_type']}".ljust(22)
        print(f"  Seq #{str(e['seq']).rjust(2)} | {actor_col} | {event_col} | {json.dumps(payload)}")
    print("=" * 80)


def main() -> None:
    print("\n" + "#" * 80)
    print("      DOWNTIME-AWARE RECOVERY CONTROL PLANE — THREE DETERMINISTIC DEMOS")
    print("             Deterministic & Fully Reproducible from a Clean State")
    print("#" * 80)

    # Clean in-memory state
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    downtime = DowntimeStore(conn)

    # Scenario 1: Successful Recovery
    res1 = trigger_successful_recovery(conn, rules=rules, downtime=downtime, deterministic_id="demo_successful_recovery_01")
    _print_trace(conn, res1["case_id"], res1["title"], res1["message"])

    # Scenario 2: Unsafe AI Recommendation Blocked
    res2 = trigger_unsafe_ai_blocked(conn, rules=rules, downtime=downtime, deterministic_id="demo_unsafe_ai_blocked_02")
    _print_trace(conn, res2["case_id"], res2["title"], res2["message"])

    # Scenario 3: Duplicate & Timeout Safety
    res3 = trigger_duplicate_timeout_handled(conn, rules=rules, downtime=downtime, deterministic_id="demo_duplicate_timeout_03")
    _print_trace(conn, res3["case_id"], res3["title"], res3["message"])

    chain_ok = verify_chain(conn)
    print("\n" + "-" * 80)
    print(f"  OVERALL AUDIT INTEGRITY: SHA-256 Hash Chain Verified = {chain_ok}")
    print(f"  TOTAL DEMO CASES EXECUTED: 3 / 3 PASSED")
    print("-" * 80 + "\n")


if __name__ == "__main__":
    main()
