"""Idempotency (Phase 1 review FIX #3): executing the same verdict twice must not
double-spend — the second call returns the original result without drawing a new
outcome or inserting a second `actions` row.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from agent import db as agent_db
from agent.clock import VirtualClock
from agent.executors.simulated import SimulatedExecutor
from agent.models import Action, Cohort, Decision, ErrorObj, Instrument, Method, PaymentFailure, Verdict
from agent.state import create_case

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _make_case(conn, case_id: str = "idem_1") -> str:
    pf = PaymentFailure(
        case_id=case_id, customer_id="cust1", order_id="o1", created_at=NOW,
        method=Method.UPI, instrument=Instrument(vpa_handle="oksbi"), amount_paise=5000,
        attempt_no=1, error=ErrorObj(code="X", source="gateway", step="s", reason="payment_failed"),
    )
    create_case(conn, pf, Cohort.TREATED)
    return pf.case_id


def test_duplicate_execution_does_not_double_spend():
    conn = agent_db.connect(":memory:")
    case_id = _make_case(conn)
    clock = VirtualClock(start=NOW)

    calls = {"n": 0}

    def outcome_fn(verdict):
        calls["n"] += 1
        return 1.0  # always succeeds, IF actually drawn

    executor = SimulatedExecutor(conn, clock, outcome_fn, random.Random(0))
    verdict = Verdict(
        case_id=case_id, decision=Decision.ALLOW, action=Action.RETRY, execute_at=NOW,
        rules_version=1, decided_at=NOW,
    )

    first = executor.execute(verdict)
    second = executor.execute(verdict)

    assert first.idempotency_key == second.idempotency_key
    assert first.succeeded == second.succeeded
    assert second.detail == "idempotent replay — no second attempt spent"
    assert calls["n"] == 1, "outcome_fn must be consulted exactly once per idempotency key"

    n_rows = conn.execute(
        "SELECT COUNT(*) c FROM actions WHERE idempotency_key = ?", (first.idempotency_key,)
    ).fetchone()["c"]
    assert n_rows == 1


def test_different_attempt_numbers_are_not_deduplicated():
    """Idempotency is scoped to (case_id, action, attempt_no) — a genuinely new
    attempt, once `cases.attempts` has advanced, must draw its own outcome."""
    conn = agent_db.connect(":memory:")
    case_id = _make_case(conn)
    clock = VirtualClock(start=NOW)

    calls = {"n": 0}

    def outcome_fn(verdict):
        calls["n"] += 1
        return 1.0

    executor = SimulatedExecutor(conn, clock, outcome_fn, random.Random(0))
    verdict = Verdict(
        case_id=case_id, decision=Decision.ALLOW, action=Action.RETRY, execute_at=NOW,
        rules_version=1, decided_at=NOW,
    )

    first = executor.execute(verdict)
    conn.execute("UPDATE cases SET attempts = attempts + 1 WHERE case_id = ?", (case_id,))
    second = executor.execute(verdict)

    assert calls["n"] == 2
    assert first.idempotency_key != second.idempotency_key
    n_rows = conn.execute("SELECT COUNT(*) c FROM actions WHERE case_id = ?", (case_id,)).fetchone()["c"]
    assert n_rows == 2
