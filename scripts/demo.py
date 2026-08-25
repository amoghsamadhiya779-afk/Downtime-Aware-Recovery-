"""`make demo` — prints two full decision traces, hand-built rather than sampled from
the random generator so both are guaranteed to appear rather than merely likely:

  1. demo_downtime_defer   — a retryable UPI failure during a live outage. The
     verdict must defer the retry to after the downtime window's `end` (acceptance
     criterion 6).
  2. demo_terminal_abandon — a terminal, unambiguous failure. The verdict must STOP
     with zero attempts spent (acceptance criterion 7).

Both cases are forced into the TREATED cohort purely so the demo is legible; this
script measures nothing and must never be cited as evidence — that is eval/report.md's
job.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on sys.path when script is executed directly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent import db as agent_db
from agent.audit import events_for, verify_chain
from agent.clock import VirtualClock
from agent.diagnosis.stub import StubDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.ledger import assign_cohort
from agent.models import Cohort, DowntimeWindow, ErrorObj, Instrument, Method, PaymentFailure
from agent.pipeline import ingest, process_case
from agent.policy.engine import load_rules


def _print_trace(conn, case_id: str) -> None:
    print(f"\n{'=' * 78}\nCASE {case_id}\n{'=' * 78}")
    for e in events_for(conn, case_id):
        payload = json.loads(e["payload"])
        print(f"[{e['event_type']:<20}] actor={e['actor']:<10} {json.dumps(payload)}")


def _find_demo_seed(case_ids: list[str], holdout_fraction: float, start_seed: int = 42) -> int:
    """Both demo cases must land TREATED, or the trace would show HOLDOUT_GUARD
    instead of the two behaviours this script exists to demonstrate."""
    seed = start_seed
    for _ in range(10_000):
        if all(assign_cohort(cid, seed, holdout_fraction) is Cohort.TREATED for cid in case_ids):
            return seed
        seed += 1
    raise RuntimeError("no seed found placing both demo cases in TREATED")


def main() -> None:
    start = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    downtime = DowntimeStore(conn)

    # A live UPI outage covering oksbi, ending two hours from `start`.
    downtime.add(
        DowntimeWindow(
            id="down_demo_1",
            method=Method.UPI,
            instrument=Instrument(vpa_handle="oksbi"),
            begin=start - timedelta(hours=1),
            end=start + timedelta(hours=2),
            status="started",
            scheduled=False,
            severity="high",
        )
    )

    case_a = PaymentFailure(
        case_id="demo_downtime_defer",
        customer_id="cust_demo_a",
        order_id="order_a",
        created_at=start,
        method=Method.UPI,
        instrument=Instrument(vpa_handle="oksbi"),
        amount_paise=250_000,
        attempt_no=1,
        error=ErrorObj(
            code="BAD_REQUEST_ERROR",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",  # ambiguous -> reaches diagnosis
            description="payment failed",
        ),
    )
    case_b = PaymentFailure(
        case_id="demo_terminal_abandon",
        customer_id="cust_demo_b",
        order_id="order_b",
        created_at=start,
        method=Method.CARD,
        instrument=Instrument(network="visa", type="credit"),
        amount_paise=500_000,
        attempt_no=1,
        error=ErrorObj(
            code="BAD_REQUEST_ERROR",
            source="issuer_bank",
            step="payment_authorization",
            reason="fraud_suspected",  # clean -> TERMINAL, never reaches the model
            description="fraud suspected",
        ),
    )

    seed = _find_demo_seed([case_a.case_id, case_b.case_id], rules.holdout_fraction)
    ingest(conn, case_a, seed, rules, start)
    ingest(conn, case_b, seed, rules, start)

    def outcome_fn(verdict):
        return 0.8  # legible demo only — real numbers live in eval/report.md

    clock = VirtualClock(start=start)
    executor = SimulatedExecutor(conn, clock, outcome_fn, random.Random(seed))
    diagnosis = StubDiagnosis()

    process_case(conn, case_a.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=diagnosis, executor=executor)
    process_case(conn, case_b.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=diagnosis, executor=executor)

    print("PHASE 1 DEMO — two decision traces proving the thesis")
    print(f"(demo seed={seed}, both cases forced TREATED for legibility; not a measurement run)")
    _print_trace(conn, case_a.case_id)
    _print_trace(conn, case_b.case_id)
    print(f"\naudit chain verifies: {verify_chain(conn)}")


if __name__ == "__main__":
    main()
