import json
import sqlite3
import pytest
from datetime import datetime, timezone
from agent.clock import VirtualClock
from agent.db import reset
from agent.models import (
    Recoverability,
    Action,
    ExpectedOutcome,
    DiagnosisProposal,
    Cohort,
)
from agent.diagnosis.port import DiagnosisInput, DiagnosisPort
from agent.executors.simulated import SimulatedExecutor
from agent.downtime import DowntimeStore
from agent.pipeline import process_case, ingest
from agent.policy.engine import Rules

# Shared test fixtures
@pytest.fixture
def setup():
    conn = reset(":memory:")
    rules = Rules(version=2, kill_switch=False, holdout_fraction=0.0, by_id={})
    downtime = DowntimeStore(conn)
    clock = VirtualClock(datetime(2026, 8, 1, tzinfo=timezone.utc))
    import random
    executor = SimulatedExecutor(conn, clock, lambda v: 1.0, random.Random(42))
    return conn, rules, downtime, clock, executor

def _pf(case_id: str):
    from agent.models import PaymentFailure, ErrorObj, Method, Instrument
    return PaymentFailure(
        case_id=case_id, customer_id="c1", order_id="o1", created_at=datetime(2026, 8, 1, tzinfo=timezone.utc), method=Method.CARD, instrument=Instrument(network="visa", type="credit"),
        amount_paise=100000, attempt_no=1, error=ErrorObj(code="X", source="bank", step="s", reason="payment_failed", description="")
    )

class DummyDiagnosis(DiagnosisPort):
    def __init__(self, action: Action, confidence: float = 0.99):
        self.action = action
        self.confidence = confidence

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        return DiagnosisProposal(
            recoverability=Recoverability.TRANSIENT_INFRA, confidence=self.confidence, evidence=[],
            proposed_action=self.action, proposed_delay_minutes=0,
            expected_outcome=ExpectedOutcome(probability_of_success=0.99, horizon_minutes=0),
            risks=[], missing_information=[], rationale="dummy", fallback_tier=0
        )

def get_last_decision(conn: sqlite3.Connection, case_id: str) -> dict:
    from agent.audit import events_for
    events = events_for(conn, case_id)
    decisions = [json.loads(e["payload"]) for e in events if e["event_type"] == "DECISION_RECORDED"]
    assert len(decisions) > 0, "No DECISION_RECORDED event found"
    return decisions[-1]


def test_financial_action_recorded(setup):
    conn, rules, downtime, clock, executor = setup
    pf = _pf("test_financial")
    ingest(conn, pf, 42, rules, clock.now())
    executor.outcome_fn = lambda v: 1.0  # succeed
    
    process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=DummyDiagnosis(Action.RETRY), executor=executor)
    
    decision = get_last_decision(conn, pf.case_id)
    print("Decision reason:", decision["reason"])
    assert decision["policy_decision"] == "ALLOW"
    assert decision["execution_result"] == "SUCCESS"
    assert decision["transaction_id"] == "test_financial"


def test_denied_actions_recorded(setup):
    conn, rules, downtime, clock, executor = setup
    rules.by_id["CONFIDENCE_FLOOR"] = {"enabled": True, "params": {"min_calibrated_confidence": 0.5}}
    pf = _pf("test_denied")
    ingest(conn, pf, 42, rules, clock.now())
    
    # Low confidence triggers REVIEW (denied execution)
    process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=DummyDiagnosis(Action.RETRY, confidence=0.1), executor=executor)
    
    decision = get_last_decision(conn, pf.case_id)
    print("Decision reason:", decision["reason"])
    assert decision["policy_decision"] == "REVIEW"
    assert decision["execution_result"] is None
    assert "calibrated confidence" in decision["reason"]


def test_failures_recorded(setup):
    conn, rules, downtime, clock, executor = setup
    pf = _pf("test_failed")
    ingest(conn, pf, 42, rules, clock.now())
    executor._outcome_fn = lambda v: 0.0  # fail
    
    process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=DummyDiagnosis(Action.RETRY), executor=executor)
    
    decision = get_last_decision(conn, pf.case_id)
    assert decision["policy_decision"] == "ALLOW"
    assert decision["execution_result"] == "FAILED"


def test_duplicate_attempts_recorded(setup):
    conn, rules, downtime, clock, executor = setup
    rules.by_id["DUPLICATE_ACTION"] = {"enabled": True, "params": {}}
    pf = _pf("test_dup")
    ingest(conn, pf, 42, rules, clock.now())
    
    # Simulate a crash where the action was executed but the attempt counter wasn't incremented
    from agent.models import idempotency_key
    key = idempotency_key(pf.case_id, Action.RETRY, 1)
    conn.execute(
        "INSERT INTO actions (idempotency_key, case_id, action, scheduled_at, executed_at, succeeded) VALUES (?, ?, ?, ?, ?, ?)",
        (key, pf.case_id, Action.RETRY.value, clock.now().isoformat(), clock.now().isoformat(), True)
    )
    
    process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=DummyDiagnosis(Action.RETRY), executor=executor)
    
    decision = get_last_decision(conn, pf.case_id)
    assert decision["policy_decision"] == "DENY"
    assert decision["execution_result"] is None
    assert "action already executed" in decision["reason"]
