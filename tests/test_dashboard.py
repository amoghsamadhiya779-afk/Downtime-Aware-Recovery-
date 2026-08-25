import json
import random
import sqlite3
import pytest
from datetime import datetime, timezone

from agent.clock import VirtualClock
from agent.dashboard import (
    compute_dashboard_metrics,
    get_transaction_trace,
    get_transactions_summary,
)
from agent.db import reset
from agent.diagnosis.stub import StubDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.models import (
    Action,
    ErrorObj,
    Instrument,
    Method,
    PaymentFailure,
)
from agent.pipeline import ingest, process_case
from agent.policy.engine import Rules


@pytest.fixture
def setup():
    conn = reset(":memory:")
    rules = Rules(version=2, kill_switch=False, holdout_fraction=0.0, by_id={})
    downtime = DowntimeStore(conn)
    clock = VirtualClock(datetime(2026, 8, 1, tzinfo=timezone.utc))
    executor = SimulatedExecutor(conn, clock, lambda v: 1.0, random.Random(42))
    return conn, rules, downtime, clock, executor


def _create_test_pf(case_id: str, amount_paise: int = 100_000, reason: str = "payment_failed") -> PaymentFailure:
    return PaymentFailure(
        case_id=case_id,
        customer_id=f"cust_{case_id}",
        order_id=f"order_{case_id}",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        method=Method.CARD,
        instrument=Instrument(network="visa", type="credit"),
        amount_paise=amount_paise,
        attempt_no=1,
        error=ErrorObj(
            code="BAD_REQUEST",
            source="gateway",
            step="payment_authorization",
            reason=reason,
            description="payment failed",
        ),
    )


def test_compute_dashboard_metrics_empty(setup):
    conn, _, _, _, _ = setup
    metrics = compute_dashboard_metrics(conn)

    assert "revenue_at_risk_rupees" in metrics
    assert "recovered_value_rupees" in metrics
    assert "recovery_rate_pct" in metrics
    assert "actions_executed" in metrics
    assert "actions_blocked" in metrics
    assert "ai_confidence_pct" in metrics
    assert "failure_rate_pct" in metrics

    assert metrics["revenue_at_risk_rupees"] == 0.0
    assert metrics["recovered_value_rupees"] == 0.0
    assert metrics["recovery_rate_pct"] == 0.0
    assert metrics["actions_executed"] == 0
    assert metrics["total_cases"] == 0


def test_compute_dashboard_metrics_with_cases(setup):
    conn, rules, downtime, clock, executor = setup

    # Case 1: Succeeds (Recovered) - ₹1,000
    pf1 = _create_test_pf("case_rec_1", amount_paise=100_000)
    ingest(conn, pf1, seed=42, rules=rules, now=clock.now())
    executor._outcome_fn = lambda v: 1.0
    process_case(conn, pf1.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=StubDiagnosis(), executor=executor)

    # Case 2: Clean terminal (Blocked/Abandoned) - ₹2,000
    pf2 = _create_test_pf("case_term_2", amount_paise=200_000, reason="fraud_suspected")
    ingest(conn, pf2, seed=42, rules=rules, now=clock.now())
    process_case(conn, pf2.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=StubDiagnosis(), executor=executor)

    metrics = compute_dashboard_metrics(conn)

    # Total at risk = ₹1,000 + ₹2,000 = ₹3,000
    assert metrics["revenue_at_risk_rupees"] == 3000.0
    # Recovered value = ₹1,000
    assert metrics["recovered_value_rupees"] == 1000.0
    # Recovery rate = 1000 / 3000 = 33.33%
    assert metrics["recovery_rate_pct"] == 33.33
    # Actions executed = 1 (Case 1 retry)
    assert metrics["actions_executed"] == 1
    # Actions blocked = 1 (Case 2 clean terminal stopped)
    assert metrics["actions_blocked"] == 1
    # Total cases = 2
    assert metrics["total_cases"] == 2
    # Recovered cases = 1
    assert metrics["recovered_cases"] == 1
    # Failure rate = 1 unrecovered / 2 = 50.0%
    assert metrics["failure_rate_pct"] == 50.0


def test_get_transactions_summary_filtering_and_search(setup):
    conn, rules, downtime, clock, executor = setup

    pf1 = _create_test_pf("case_alpha", amount_paise=50_000)
    pf2 = _create_test_pf("case_beta", amount_paise=75_000, reason="fraud_suspected")

    ingest(conn, pf1, seed=42, rules=rules, now=clock.now())
    ingest(conn, pf2, seed=42, rules=rules, now=clock.now())

    process_case(conn, pf1.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=StubDiagnosis(), executor=executor)
    process_case(conn, pf2.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=StubDiagnosis(), executor=executor)

    # Search for alpha
    res_search = get_transactions_summary(conn, search="alpha")
    assert res_search["total"] == 1
    assert res_search["transactions"][0]["case_id"] == "case_alpha"

    # Filter by state RECOVERED
    res_rec = get_transactions_summary(conn, state_filter="RECOVERED")
    assert res_rec["total"] == 1
    assert res_rec["transactions"][0]["case_id"] == "case_alpha"

    # Filter by state ABANDONED
    res_ab = get_transactions_summary(conn, state_filter="ABANDONED")
    assert res_ab["total"] == 1
    assert res_ab["transactions"][0]["case_id"] == "case_beta"


def test_get_transaction_trace_and_cryptographic_verification(setup):
    conn, rules, downtime, clock, executor = setup

    pf = _create_test_pf("case_trace_001", amount_paise=150_000)
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())
    process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=StubDiagnosis(), executor=executor)

    trace = get_transaction_trace(conn, "case_trace_001")

    assert trace["case_id"] == "case_trace_001"
    assert trace["order_id"] == pf.order_id
    assert trace["amount_rupees"] == 1500.0
    assert trace["chain_valid"] is True
    assert trace["event_count"] >= 5

    event_types = [e["event_type"] for e in trace["timeline"]]
    assert "SIGNAL_RECEIVED" in event_types
    assert "COHORT_ASSIGNED" in event_types
    assert "TRIAGE_RESULT" in event_types
    assert "POLICY_VERDICT" in event_types
    assert "DECISION_RECORDED" in event_types


def test_get_transaction_trace_not_found(setup):
    conn, _, _, _, _ = setup
    with pytest.raises(KeyError):
        get_transaction_trace(conn, "non_existent_case")
