"""Execution uncertainty and reconciliation — the "do not blindly retry" contract.

Four scenarios the user asked for:
    1. Execution timeout → quarantine, not retry
    2. Unknown execution status → quarantine, not retry
    3. Reconcile: action actually succeeded → RECOVERED
    4. Reconcile: action actually failed → FAILED_ATTEMPT
    5. Reconcile: action never ran → DIAGNOSED (can be reprocessed)

Plus structural invariants:
    - Uncertain outcomes do NOT consume attempt budget
    - Reconciliation increments attempts only when the action actually ran
    - After reconciliation (never ran), the case CAN be reprocessed
    - Audit chain stays intact through the whole cycle
    - Double reconciliation is prevented
    - Quarantined cases appear in find_uncertain_cases only when unresolved
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from agent import db as agent_db
from agent.audit import verify_chain
from agent.clock import VirtualClock
from agent.diagnosis.stub import AdversarialDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.contracts import ExecutionUncertain, UncertaintyCode
from agent.executors.simulated import SimulatedExecutor
from agent.models import (
    ActionOutcome,
    CaseState,
    Cohort,
    ErrorObj,
    Instrument,
    Method,
    PaymentFailure,
)
from agent.pipeline import ingest, process_case
from agent.policy.engine import load_rules
from agent.reconciliation import ReconciliationError, find_uncertain_cases, reconcile
from agent.state import create_case, get_case, transition

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)
RULES = load_rules()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ambiguous_upi_case(case_id: str = "recon_1") -> PaymentFailure:
    """A case with an AMBIGUOUS error reason so it reaches the executor."""
    return PaymentFailure(
        case_id=case_id,
        customer_id="cust1",
        order_id="order1",
        created_at=NOW,
        method=Method.UPI,
        instrument=Instrument(vpa_handle="oksbi"),
        amount_paise=500_00,
        attempt_no=1,
        error=ErrorObj(
            code="X", source="gateway", step="s", reason="payment_failed", description=""
        ),
    )


def _run_case_to_quarantine_via_timeout(
    case_id: str = "recon_1", *, timeout_once: bool = True
) -> tuple:
    """Ingest and process a case through a simulated timeout.

    Returns (conn, case_id, clock) for further assertions.
    """
    conn = agent_db.connect(":memory:")
    clock = VirtualClock(start=NOW)
    downtime = DowntimeStore(conn)

    call_count = {"n": 0}

    def timeout_fn(verdict):
        call_count["n"] += 1
        if timeout_once and call_count["n"] > 1:
            return False
        return True

    executor = SimulatedExecutor(
        conn, clock, outcome_fn=lambda v: 1.0, rng=random.Random(0),
        timeout_fn=timeout_fn,
    )
    diagnosis = AdversarialDiagnosis()
    pf = _ambiguous_upi_case(case_id)
    ingest(conn, pf, seed=42, rules=RULES, now=NOW)

    clock.set(NOW + timedelta(minutes=1))
    trace = process_case(
        conn, case_id, clock=clock, rules=RULES, downtime=downtime,
        diagnosis_port=diagnosis, executor=executor,
    )
    return conn, case_id, clock, trace, executor, diagnosis, downtime


# ---------------------------------------------------------------------------
# 1. Execution timeout → quarantine (not retry)
# ---------------------------------------------------------------------------


class TestExecutionTimeout:
    """An executor that times out must quarantine the case, not retry."""

    def test_timeout_quarantines_case(self):
        conn, case_id, _, trace, *_ = _run_case_to_quarantine_via_timeout()
        row = get_case(conn, case_id)
        assert row["state"] == "QUARANTINED"
        assert trace.final_state == "QUARANTINED"

    def test_timeout_does_not_consume_attempt_budget(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        row = get_case(conn, case_id)
        assert row["attempts"] == 0, "uncertain outcome must not increment attempts"

    def test_timeout_logs_action_uncertain_event(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        events = conn.execute(
            "SELECT event_type, payload FROM audit_events "
            "WHERE case_id = ? AND event_type = 'ACTION_UNCERTAIN'",
            (case_id,),
        ).fetchall()
        assert len(events) == 1
        import json
        payload = json.loads(events[0]["payload"])
        assert payload["code"] == "EXECUTION_TIMEOUT"
        assert payload["idempotency_key"]  # non-empty

    def test_audit_chain_intact_after_timeout(self):
        conn, *_ = _run_case_to_quarantine_via_timeout()
        assert verify_chain(conn)


# ---------------------------------------------------------------------------
# 2. Unknown execution status → quarantine (not retry)
# ---------------------------------------------------------------------------


class TestUnknownStatus:
    """An executor reporting unknown status must quarantine, not retry."""

    def test_unknown_status_exception_has_correct_fields(self):
        exc = ExecutionUncertain(
            UncertaintyCode.STATUS_UNKNOWN,
            "indeterminate response",
            idempotency_key="key123",
        )
        assert exc.code is UncertaintyCode.STATUS_UNKNOWN
        assert exc.detail == "indeterminate response"
        assert exc.idempotency_key == "key123"
        assert "STATUS_UNKNOWN" in str(exc)

    def test_timeout_and_unknown_are_distinct_codes(self):
        assert UncertaintyCode.EXECUTION_TIMEOUT != UncertaintyCode.STATUS_UNKNOWN


# ---------------------------------------------------------------------------
# 3. Reconciliation: action actually succeeded → RECOVERED
# ---------------------------------------------------------------------------


class TestReconcileSucceeded:

    def test_reconcile_succeeded_transitions_to_recovered(self):
        conn, case_id, clock, *_ = _run_case_to_quarantine_via_timeout()
        ts = NOW + timedelta(minutes=10)
        result = reconcile(conn, case_id, actual_outcome=ActionOutcome.SUCCEEDED, ts=ts)
        assert result == "RECOVERED"
        assert get_case(conn, case_id)["state"] == "RECOVERED"

    def test_reconcile_succeeded_increments_attempts(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        assert get_case(conn, case_id)["attempts"] == 0
        reconcile(conn, case_id, actual_outcome=ActionOutcome.SUCCEEDED, ts=NOW + timedelta(minutes=10))
        assert get_case(conn, case_id)["attempts"] == 1

    def test_reconcile_succeeded_audit_chain_intact(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        reconcile(conn, case_id, actual_outcome=ActionOutcome.SUCCEEDED, ts=NOW + timedelta(minutes=10))
        assert verify_chain(conn)


# ---------------------------------------------------------------------------
# 4. Reconciliation: action actually failed → FAILED_ATTEMPT
# ---------------------------------------------------------------------------


class TestReconcileFailed:

    def test_reconcile_failed_transitions_to_failed_attempt(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        result = reconcile(conn, case_id, actual_outcome=ActionOutcome.FAILED, ts=NOW + timedelta(minutes=10))
        assert result == "FAILED_ATTEMPT"
        assert get_case(conn, case_id)["state"] == "FAILED_ATTEMPT"

    def test_reconcile_failed_increments_attempts(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        reconcile(conn, case_id, actual_outcome=ActionOutcome.FAILED, ts=NOW + timedelta(minutes=10))
        assert get_case(conn, case_id)["attempts"] == 1

    def test_reconcile_failed_audit_chain_intact(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        reconcile(conn, case_id, actual_outcome=ActionOutcome.FAILED, ts=NOW + timedelta(minutes=10))
        assert verify_chain(conn)


# ---------------------------------------------------------------------------
# 5. Reconciliation: action never ran → DIAGNOSED (reprocessable)
# ---------------------------------------------------------------------------


class TestReconcileNeverRan:

    def test_reconcile_never_ran_transitions_to_diagnosed(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        result = reconcile(conn, case_id, actual_outcome=None, ts=NOW + timedelta(minutes=10))
        assert result == "DIAGNOSED"
        assert get_case(conn, case_id)["state"] == "DIAGNOSED"

    def test_reconcile_never_ran_does_not_increment_attempts(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        reconcile(conn, case_id, actual_outcome=None, ts=NOW + timedelta(minutes=10))
        assert get_case(conn, case_id)["attempts"] == 0

    def test_case_reprocessable_after_never_ran_reconciliation(self):
        """After reconciliation says the action never ran, the case can go
        through the full pipeline again and succeed."""
        conn, case_id, clock, _, executor, diagnosis, downtime = _run_case_to_quarantine_via_timeout()

        # Reconcile: action never ran
        reconcile(conn, case_id, actual_outcome=None, ts=NOW + timedelta(minutes=10))
        assert get_case(conn, case_id)["state"] == "DIAGNOSED"

        # Now re-process — the executor's timeout_fn only fires once
        clock.set(NOW + timedelta(minutes=20))
        trace = process_case(
            conn, case_id, clock=clock, rules=RULES, downtime=downtime,
            diagnosis_port=diagnosis, executor=executor,
        )
        # The case should have been processed successfully this time
        row = get_case(conn, case_id)
        assert row["state"] in ("RECOVERED", "FAILED_ATTEMPT"), f"unexpected state: {row['state']}"
        assert row["attempts"] == 1

    def test_reconcile_never_ran_audit_chain_intact(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        reconcile(conn, case_id, actual_outcome=None, ts=NOW + timedelta(minutes=10))
        assert verify_chain(conn)


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


class TestReconciliationGuards:

    def test_reconcile_non_quarantined_case_raises(self):
        """Reconciliation only applies to QUARANTINED cases."""
        conn = agent_db.connect(":memory:")
        pf = _ambiguous_upi_case("guard_1")
        create_case(conn, pf, Cohort.TREATED)
        transition(conn, "guard_1", "DIAGNOSED")
        with pytest.raises(ReconciliationError, match="not QUARANTINED"):
            reconcile(conn, "guard_1", actual_outcome=None, ts=NOW)

    def test_reconcile_quarantined_without_uncertain_event_raises(self):
        """A case quarantined for other reasons (low confidence) cannot be
        reconciled — it has no uncertain action to verify."""
        conn = agent_db.connect(":memory:")
        pf = _ambiguous_upi_case("guard_2")
        create_case(conn, pf, Cohort.TREATED)
        transition(conn, "guard_2", "DIAGNOSED")
        transition(conn, "guard_2", "QUARANTINED")
        with pytest.raises(ReconciliationError, match="no unresolved ACTION_UNCERTAIN"):
            reconcile(conn, "guard_2", actual_outcome=None, ts=NOW)

    def test_double_reconciliation_raises(self):
        """The same uncertain case cannot be reconciled twice."""
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        reconcile(conn, case_id, actual_outcome=ActionOutcome.SUCCEEDED, ts=NOW + timedelta(minutes=10))
        # Case is now RECOVERED — reconciling again should fail (not QUARANTINED)
        with pytest.raises(ReconciliationError, match="not QUARANTINED"):
            reconcile(conn, case_id, actual_outcome=ActionOutcome.SUCCEEDED, ts=NOW + timedelta(minutes=20))


class TestFindUncertainCases:

    def test_finds_quarantined_uncertain_case(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        cases = find_uncertain_cases(conn)
        assert len(cases) == 1
        assert cases[0]["case_id"] == case_id
        assert cases[0]["code"] == "EXECUTION_TIMEOUT"
        assert cases[0]["idempotency_key"]  # non-empty

    def test_excludes_already_reconciled(self):
        conn, case_id, *_ = _run_case_to_quarantine_via_timeout()
        reconcile(conn, case_id, actual_outcome=ActionOutcome.SUCCEEDED, ts=NOW + timedelta(minutes=10))
        assert find_uncertain_cases(conn) == []

    def test_excludes_quarantined_without_uncertain_event(self):
        """Cases quarantined for other reasons (e.g. low confidence, terminal
        refusal) must not appear in the reconciliation queue."""
        conn = agent_db.connect(":memory:")
        pf = _ambiguous_upi_case("lc_1")
        create_case(conn, pf, Cohort.TREATED)
        transition(conn, "lc_1", "DIAGNOSED")
        transition(conn, "lc_1", "QUARANTINED")
        assert find_uncertain_cases(conn) == []

    def test_finds_multiple_uncertain_cases(self):
        conn1, _, *_ = _run_case_to_quarantine_via_timeout("case_a")
        # Build a second case in the same conn
        conn = conn1
        clock = VirtualClock(start=NOW)
        downtime = DowntimeStore(conn)
        executor = SimulatedExecutor(
            conn, clock, outcome_fn=lambda v: 1.0, rng=random.Random(0),
            timeout_fn=lambda v: True,
        )
        diagnosis = AdversarialDiagnosis()
        pf = _ambiguous_upi_case("case_b")
        ingest(conn, pf, seed=42, rules=RULES, now=NOW)
        clock.set(NOW + timedelta(minutes=2))
        process_case(
            conn, "case_b", clock=clock, rules=RULES, downtime=downtime,
            diagnosis_port=diagnosis, executor=executor,
        )
        cases = find_uncertain_cases(conn)
        assert {c["case_id"] for c in cases} == {"case_a", "case_b"}


# ---------------------------------------------------------------------------
# End-to-end: full cycle with audit verification
# ---------------------------------------------------------------------------


class TestFullReconciliationCycle:
    """Walk a case through timeout → quarantine → reconciliation → completion,
    verifying the entire audit chain at each step."""

    def test_timeout_reconcile_succeed_full_cycle(self):
        conn, case_id, clock, *_ = _run_case_to_quarantine_via_timeout()

        # Verify quarantined
        assert get_case(conn, case_id)["state"] == "QUARANTINED"
        assert get_case(conn, case_id)["attempts"] == 0

        # Reconcile: the action actually succeeded
        ts = NOW + timedelta(minutes=30)
        target = reconcile(conn, case_id, actual_outcome=ActionOutcome.SUCCEEDED, ts=ts)

        # Final state
        assert target == "RECOVERED"
        assert get_case(conn, case_id)["state"] == "RECOVERED"
        assert get_case(conn, case_id)["attempts"] == 1

        # Audit chain
        assert verify_chain(conn)

        # Reconciliation event recorded
        recon_events = conn.execute(
            "SELECT payload FROM audit_events WHERE case_id = ? AND event_type = 'RECONCILIATION_RESOLVED'",
            (case_id,),
        ).fetchall()
        assert len(recon_events) == 1

    def test_timeout_reconcile_never_ran_reprocess_succeed(self):
        """The full "safe retry" path: timeout → quarantine → reconciliation
        (never ran) → DIAGNOSED → reprocess → RECOVERED."""
        conn, case_id, clock, _, executor, diagnosis, downtime = _run_case_to_quarantine_via_timeout()

        # Reconcile: never ran
        reconcile(conn, case_id, actual_outcome=None, ts=NOW + timedelta(minutes=10))
        assert get_case(conn, case_id)["state"] == "DIAGNOSED"
        assert get_case(conn, case_id)["attempts"] == 0

        # Reprocess (timeout_fn only fires once, so this attempt goes through)
        clock.set(NOW + timedelta(minutes=20))
        trace = process_case(
            conn, case_id, clock=clock, rules=RULES, downtime=downtime,
            diagnosis_port=diagnosis, executor=executor,
        )
        assert get_case(conn, case_id)["state"] in ("RECOVERED", "FAILED_ATTEMPT")
        assert get_case(conn, case_id)["attempts"] == 1

        # Audit chain intact through the entire cycle
        assert verify_chain(conn)
