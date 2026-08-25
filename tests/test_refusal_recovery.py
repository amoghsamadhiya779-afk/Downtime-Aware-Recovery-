"""A refused command must never strand a case.

The pipeline moves a case to EXECUTING and *then* calls the executor. ADR-019
gave the executor six ways to raise ActionRefused; before ADR-020 any of them
left the case in EXECUTING — a non-terminal state whose only exits are
transitions the function never reaches, because the exception escaped.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from agent import db as agent_db
from agent.audit import verify_chain
from agent.clock import VirtualClock
from agent.diagnosis.stub import StubDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.contracts import ActionErrorCode, ActionRefused
from agent.ledger import assign_cohort
from agent.models import CaseState, Cohort, ErrorObj, Instrument, Method, PaymentFailure
from agent.pipeline import ingest, process_case
from agent.policy.engine import load_rules
from agent.state import TERMINAL_STATES, get_case

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


class _RefusingExecutor:
    """Refuses every dispatch with a chosen code."""

    def __init__(self, code: ActionErrorCode) -> None:
        self._code = code
        self.calls = 0

    def execute(self, verdict):
        self.calls += 1
        raise ActionRefused(self._code, "injected for test")


def _run_one(code: ActionErrorCode):
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    clock = VirtualClock(start=NOW)
    executor = _RefusingExecutor(code)

    pf = PaymentFailure(
        case_id="r1", customer_id="cust1", order_id="o1", created_at=NOW,
        method=Method.CARD, instrument=Instrument(network="visa", type="credit"),
        amount_paise=1_000_00, attempt_no=1,
        error=ErrorObj(code="X", source="gateway", step="s", reason="payment_failed"),
    )
    # seed=0 puts "r1" in the TREATED arm — verified against assign_cohort, not
    # assumed. A holdout case is denied by HOLDOUT_GUARD and never reaches an
    # executor at all, so it could not exercise a refusal.
    assert assign_cohort(pf.case_id, 0, rules.holdout_fraction) is Cohort.TREATED
    ingest(conn, pf, 0, rules, NOW)
    trace = process_case(
        conn, "r1", clock=clock, rules=rules, downtime=DowntimeStore(conn),
        diagnosis_port=StubDiagnosis(), executor=executor,
    )
    return conn, trace, executor


@pytest.mark.parametrize("code", [
    ActionErrorCode.NOT_AUTHORIZED,
    ActionErrorCode.ACTION_MISMATCH,
    ActionErrorCode.INVALID_PARAMS,
    ActionErrorCode.UNKNOWN_CASE,
    ActionErrorCode.ILLEGAL_STATE,
    ActionErrorCode.PROVIDER_REJECTED,
])
def test_terminal_refusal_quarantines_rather_than_stranding(code):
    conn, trace, executor = _run_one(code)
    assert executor.calls == 1
    state = CaseState(get_case(conn, "r1")["state"])
    assert state is CaseState.QUARANTINED
    # QUARANTINED is no longer terminal (reconciliation provides outgoing edges)
    # but it is still the correct landing state for a terminal refusal: the case
    # needs human/system review before any further action.
    assert trace.final_state == "QUARANTINED"


@pytest.mark.parametrize("code", [
    ActionErrorCode.DUPLICATE_IN_FLIGHT,
    ActionErrorCode.PROVIDER_ERROR,
])
def test_retryable_refusal_returns_to_scheduled_for_redispatch(code):
    """Retryable refusals go back to the queue rather than to a human — the work
    is still viable, it just could not run now."""
    conn, trace, executor = _run_one(code)
    state = CaseState(get_case(conn, "r1")["state"])
    assert state is CaseState.SCHEDULED
    assert state not in TERMINAL_STATES  # deliberately: awaiting re-dispatch
    assert trace.final_state == "SCHEDULED"


def test_refusal_consumes_no_attempt():
    """A refused action never ran, so it must not spend attempt budget — that is
    the whole reason ActionRefused is distinct from a FAILED ActionResult."""
    conn, _, _ = _run_one(ActionErrorCode.ILLEGAL_STATE)
    assert get_case(conn, "r1")["attempts"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM actions").fetchone()["c"] == 0


def test_refusal_is_recorded_in_the_audit_trail():
    conn, _, _ = _run_one(ActionErrorCode.PROVIDER_REJECTED)
    row = conn.execute(
        "SELECT payload FROM audit_events WHERE event_type = 'ACTION_REFUSED'"
    ).fetchone()
    assert row is not None, "a refusal must be auditable, not silently swallowed"
    assert "PROVIDER_REJECTED" in row["payload"]


def test_audit_chain_still_verifies_after_a_refusal():
    conn, _, _ = _run_one(ActionErrorCode.ILLEGAL_STATE)
    assert verify_chain(conn)
