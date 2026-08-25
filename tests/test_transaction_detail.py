import random
import sqlite3
import pytest
from datetime import datetime, timezone

from agent.clock import VirtualClock
from agent.dashboard import get_transaction_detail
from agent.db import reset
from agent.diagnosis.stub import AdversarialDiagnosis, StubDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.models import (
    ErrorObj,
    Instrument,
    Method,
    PaymentFailure,
)
from agent.pipeline import ingest, process_case
import dataclasses
from agent.policy.engine import Rules, load_rules


@pytest.fixture
def setup():
    conn = reset(":memory:")
    rules = dataclasses.replace(load_rules(), holdout_fraction=0.0)
    downtime = DowntimeStore(conn)
    clock = VirtualClock(datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))
    executor = SimulatedExecutor(conn, clock, lambda v: 1.0, random.Random(42))
    return conn, rules, downtime, clock, executor


def _create_test_pf(
    case_id: str,
    amount_paise: int = 150_000,
    reason: str = "payment_failed",
    method: Method = Method.CARD,
) -> PaymentFailure:
    return PaymentFailure(
        case_id=case_id,
        customer_id=f"cust_{case_id}",
        order_id=f"order_{case_id}",
        created_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        method=method,
        instrument=Instrument(network="visa", type="credit"),
        amount_paise=amount_paise,
        attempt_no=1,
        error=ErrorObj(
            code="BAD_REQUEST",
            source="gateway",
            step="payment_authorization",
            reason=reason,
            description="Transaction failed at bank network",
        ),
    )


def test_transaction_detail_all_9_phases_recovered(setup):
    conn, rules, downtime, clock, executor = setup

    pf = _create_test_pf("case_rec_99", amount_paise=250_000, reason="payment_failed")
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())
    executor._outcome_fn = lambda v: 1.0
    process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=StubDiagnosis(), executor=executor)

    detail = get_transaction_detail(conn, "case_rec_99")

    # Verify top-level structure contains all 9 phases
    assert detail["case_id"] == "case_rec_99"
    assert "event" in detail
    assert "context" in detail
    assert "ai_diagnosis" in detail
    assert "evidence" in detail
    assert "proposed_action" in detail
    assert "policy_result" in detail
    assert "execution" in detail
    assert "outcome" in detail
    assert "audit_trail" in detail

    # Phase 1: Event
    ev = detail["event"]
    assert ev["order_id"] == "order_case_rec_99"
    assert ev["amount_rupees"] == 2500.0
    assert ev["method"] == "card"
    assert ev["error_reason"] == "payment_failed"

    # Phase 2: Context
    ctx = detail["context"]
    assert ctx["cohort"] == "TREATED"
    assert ctx["attempt_no"] == 2
    assert ctx["prior_failures_count"] == 1

    # Phase 3: AI Diagnosis
    diag = detail["ai_diagnosis"]
    assert diag["recoverability"] == "TRANSIENT_INFRA"
    assert diag["confidence"] == 0.7
    assert diag["confidence_pct"] == 70.0

    # Phase 4: Evidence
    evi = detail["evidence"]
    assert "error.reason=payment_failed" in evi["cited_fields"]
    assert evi["is_grounded"] is True

    # Phase 5: Proposed Action
    prop = detail["proposed_action"]
    assert prop["proposed_action"] == "RETRY"
    assert prop["proposed_delay_minutes"] == 15
    assert prop["expected_success_probability"] == 0.5

    # Phase 6: Policy Result
    pol = detail["policy_result"]
    assert pol["policy_decision"] == "ALLOW"
    assert pol["authorized_action"] == "RETRY"
    assert pol["is_executable"] is True

    # Phase 7: Execution
    exec_info = detail["execution"]
    assert exec_info["is_dispatched"] is True
    assert exec_info["idempotency_key"] is not None
    assert exec_info["execution_mode"].upper() == "SIM"

    # Phase 8: Outcome
    out = detail["outcome"]
    assert out["final_state"] == "RECOVERED"
    assert out["outcome_status"] == "SUCCEEDED"
    assert out["succeeded"] is True

    # Phase 9: Audit Trail
    aud = detail["audit_trail"]
    assert aud["chain_valid"] is True
    assert aud["total_events"] >= 6
    assert aud["decision_record"] is not None


def test_transaction_detail_policy_denial(setup):
    conn, rules, downtime, clock, executor = setup

    pf = _create_test_pf("case_fraud_01", amount_paise=500_000, reason="fraud_suspected")
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())
    process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=StubDiagnosis(), executor=executor)

    detail = get_transaction_detail(conn, "case_fraud_01")

    # Phase 6: Policy Result
    pol = detail["policy_result"]
    assert pol["policy_decision"] == "DENY"
    assert pol["authorized_action"] == "STOP"
    assert pol["is_executable"] is False

    # Phase 7: Execution
    exec_info = detail["execution"]
    assert exec_info["is_dispatched"] is False

    # Phase 8: Outcome
    out = detail["outcome"]
    assert out["final_state"] == "ABANDONED"
    assert out["outcome_status"] == "BLOCKED_BY_POLICY"
    assert out["succeeded"] is None

    # Phase 9: Audit Trail
    assert detail["audit_trail"]["chain_valid"] is True


def test_transaction_detail_adversarial_blocked_by_policy(setup):
    conn, rules, downtime, clock, executor = setup

    # When attempt count has reached the cap (4 for card), Policy Engine vetos even a 100% confident RETRY proposal
    pf = _create_test_pf("case_adv_01", reason="payment_failed")
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())
    # Manually simulate previous attempts reaching cap
    conn.execute("UPDATE cases SET attempts = 4 WHERE case_id = 'case_adv_01'")

    process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=AdversarialDiagnosis(), executor=executor)

    detail = get_transaction_detail(conn, "case_adv_01")

    # AI Diagnosis proposed RETRY with 100% confidence
    assert detail["ai_diagnosis"]["confidence_pct"] == 100.0
    assert detail["proposed_action"]["proposed_action"] == "RETRY"

    # But Policy Vetoes due to ATTEMPT_CAP
    assert detail["policy_result"]["policy_decision"] == "DENY"
    assert "ATTEMPT_CAP" in detail["policy_result"]["fired_rules"]
    assert detail["outcome"]["final_state"] == "ABANDONED"


def test_transaction_detail_not_found(setup):
    conn, _, _, _, _ = setup
    with pytest.raises(KeyError):
        get_transaction_detail(conn, "missing_case_id_xyz")
