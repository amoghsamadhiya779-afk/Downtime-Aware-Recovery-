"""Automated tests for the 10 adversarial scenarios (Adversarial Defenses).

These tests explicitly assert that the defensive mechanisms (Pydantic schema, Policy Engine, 
SQLite constraints, optimistic locking, and cryptographic audit log) hold strong against 
malicious, malformed, or concurrent failure modes.
"""

import json
import sqlite3
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from agent import db as agent_db
from agent.audit import events_for, append
from agent.clock import VirtualClock
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.executors.contracts import ExecutionUncertain, UncertaintyCode
from agent.models import (
    Action, CaseState, DiagnosisProposal, ExpectedOutcome, 
    PaymentFailure, Method, Instrument, ErrorObj, Recoverability, Decision,
    ActionResult
)
from agent.pipeline import ingest, process_case
from agent.policy.engine import load_rules
from agent.state import transition, IllegalTransition, get_case
from agent.diagnosis.port import DiagnosisPort, DiagnosisInput
from agent.diagnosis.claude import ClaudeDiagnosis

START = datetime(2026, 8, 1, tzinfo=timezone.utc)

def _ambiguous_pf() -> PaymentFailure:
    return PaymentFailure(
        case_id="adv_test_001",
        customer_id="cust_001",
        order_id="order_001",
        created_at=START,
        method=Method.CARD,
        instrument=Instrument(network="visa", type="credit"),
        amount_paise=1_000_00,
        attempt_no=1,
        error=ErrorObj(code="X", source="gateway", step="s", reason="payment_failed", description=""),
    )

def _clean_pf() -> PaymentFailure:
    return PaymentFailure(
        case_id="adv_test_002",
        customer_id="cust_002",
        order_id="order_002",
        created_at=START,
        method=Method.CARD,
        instrument=Instrument(network="visa", type="credit"),
        amount_paise=1_000_00,
        attempt_no=1,
        # balance_insufficient is deterministically TERMINAL
        error=ErrorObj(code="BAD_REQUEST_ERROR", source="gateway", step="payment_authentication", reason="balance_insufficient", description=""),
    )

@pytest.fixture
def setup(monkeypatch):
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    from agent.models import Cohort
    monkeypatch.setattr("agent.pipeline.assign_cohort", lambda case_id, seed, fraction: Cohort.TREATED)
    downtime = DowntimeStore(conn)
    clock = VirtualClock(start=START)
    import random
    executor = SimulatedExecutor(conn, clock, outcome_fn=lambda v: 0.0, rng=random.Random(0))
    yield conn, rules, downtime, clock, executor
    conn.close()


# Scenario 1: Bad AI Output
def test_bad_ai_output_schema_violation(setup, monkeypatch):
    conn, rules, downtime, clock, executor = setup
    pf = _ambiguous_pf()
    ingest(conn, pf, 42, rules, clock.now())

    # Mock Claude API to return garbage JSON
    class RantDiagnosis(ClaudeDiagnosis):
        def _call(self, prompt: str) -> str:
            return "This is not valid json, I refuse to answer."

    diagnosis_port = RantDiagnosis(api_key="fake")
    
    trace = process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=diagnosis_port, executor=executor)
    
    # Expected Behaviour: ClaudeDiagnosis catches JSON decode error, retries once, then falls back to Tier 2 (UNKNOWN/TERMINAL)
    # Final State: ABANDONED (because UNKNOWN/STOP -> Policy DENY)
    assert trace.diagnosis.fallback_tier == 3
    assert trace.final_state == "ABANDONED"
    
    # Audit Event: DIAGNOSIS_RETURNED contains the fallback payload
    events = events_for(conn, pf.case_id)
    diag_event = next(e for e in events if e["event_type"] == "DIAGNOSIS_RETURNED")
    payload = json.loads(diag_event["payload"])
    assert payload["fallback_tier"] == 3
    assert payload["rationale"].startswith("stub: unrecognised combination")

# Scenario 2: Low Confidence Override
def test_low_confidence_override(setup):
    conn, rules, downtime, clock, executor = setup
    pf = _ambiguous_pf()
    ingest(conn, pf, 42, rules, clock.now())

    class LowConfDiagnosis(DiagnosisPort):
        def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
            return DiagnosisProposal(
                recoverability=Recoverability.TRANSIENT_INFRA,
                confidence=0.15, # Extremely low confidence
                evidence=[],
                proposed_action=Action.RETRY,
                proposed_delay_minutes=15,
                expected_outcome=ExpectedOutcome(probability_of_success=0.15, horizon_minutes=15),
                risks=[], missing_information=[], rationale="Maybe?", fallback_tier=0
            )

    trace = process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=LowConfDiagnosis(), executor=executor)
    
    # Expected Behaviour: Policy Engine calculates negative EV, returns REVIEW
    # Final State: QUARANTINED (since REVIEW goes to human)
    assert trace.verdict.decision == Decision.REVIEW
    assert trace.final_state == "QUARANTINED"
    
    # Audit Event: POLICY_VERDICT
    events = events_for(conn, pf.case_id)
    policy_event = next(e for e in events if e["event_type"] == "POLICY_VERDICT")
    assert "CONFIDENCE_FLOOR" in json.loads(policy_event["payload"])["fired_rules"]

# Scenario 3: Duplicate Events
def test_duplicate_events_ingestion_storm(setup):
    conn, rules, downtime, clock, executor = setup
    pf = _ambiguous_pf()
    ingest(conn, pf, 42, rules, clock.now())
    
    # Expected Behaviour: Ingesting the same case_id again throws sqlite3.IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        ingest(conn, pf, 42, rules, clock.now())

# Scenario 4: Stale State
def test_stale_state_optimistic_locking(setup):
    conn, rules, downtime, clock, executor = setup
    pf = _ambiguous_pf()
    ingest(conn, pf, 42, rules, clock.now())
    
    # Setup: Move DETECTED -> DIAGNOSED -> SCHEDULED
    transition(conn, pf.case_id, "DIAGNOSED")
    transition(conn, pf.case_id, "SCHEDULED")
    
    # Worker 1 transitions to EXECUTING
    transition(conn, pf.case_id, "EXECUTING")
    
    # Expected Behaviour: Worker 2 attempts the same transition but state is no longer SCHEDULED
    # It must throw IllegalTransition to prevent double execution.
    with pytest.raises(IllegalTransition, match="EXECUTING -> EXECUTING is not permitted"):
        transition(conn, pf.case_id, "EXECUTING")

# Scenario 5: API Timeout
def test_api_timeout_downtime_failsafe(setup, monkeypatch):
    conn, rules, downtime, clock, executor = setup
    pf = _ambiguous_pf()
    ingest(conn, pf, 42, rules, clock.now())

    class TimeoutDiagnosis(DiagnosisPort):
        def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
            return DiagnosisProposal(
                recoverability=Recoverability.TRANSIENT_INFRA, confidence=0.99, evidence=[],
                proposed_action=Action.RETRY, proposed_delay_minutes=0,
                expected_outcome=ExpectedOutcome(probability_of_success=0.99, horizon_minutes=0),
                risks=[], missing_information=[], rationale="Retry now", fallback_tier=0
            )

    # Mock DowntimeStore context_at to simulate catching a network timeout and returning empty failsafe
    def mock_context_at(*args, **kwargs):
        # In a real network setting this would wrap a request that raises TimeoutError
        # and returns an empty DowntimeContext. We simulate that empty return directly.
        from agent.models import DowntimeContext
        return DowntimeContext(active=False)
    
    monkeypatch.setattr(downtime, "context_at", mock_context_at)

    trace = process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=TimeoutDiagnosis(), executor=executor)
    
    # Expected Behaviour: Degradation to immediate retry (no downtime rules fire). Pipeline does not crash.
    assert "DOWNTIME_DEFER" not in trace.verdict.fired_rules
    assert trace.final_state in ["RECOVERED", "FAILED_ATTEMPT"] # Proceeded to execute

# Scenario 6: Partial Failure
def test_partial_failure_execution_uncertain(setup, monkeypatch):
    conn, rules, downtime, clock, executor = setup
    pf = _ambiguous_pf()
    ingest(conn, pf, 42, rules, clock.now())

    class ConfidentDiagnosis(DiagnosisPort):
        def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
            return DiagnosisProposal(
                recoverability=Recoverability.TRANSIENT_INFRA, confidence=0.99, evidence=[],
                proposed_action=Action.RETRY, proposed_delay_minutes=0,
                expected_outcome=ExpectedOutcome(probability_of_success=0.99, horizon_minutes=0),
                risks=[], missing_information=[], rationale="", fallback_tier=0
            )

    # Mock the executor to raise ExecutionUncertain
    def mock_execute(*args, **kwargs):
        raise ExecutionUncertain(UncertaintyCode.STATUS_UNKNOWN, "Network dropped", idempotency_key="idemp_key_1")
    monkeypatch.setattr(executor, "execute", mock_execute)

    trace = process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=ConfidentDiagnosis(), executor=executor)

    # Expected Behaviour: Transitions to QUARANTINED, no blind retry
    assert trace.final_state == "QUARANTINED"
    
    # Audit Event: ACTION_UNCERTAIN
    events = events_for(conn, pf.case_id)
    assert any(e["event_type"] == "ACTION_UNCERTAIN" for e in events)

# Scenario 7: Conflicting Signals
def test_conflicting_signals_triage_override(setup, monkeypatch):
    conn, rules, downtime, clock, executor = setup
    # Clean terminal PF (balance_insufficient)
    pf = _clean_pf()
    ingest(conn, pf, 42, rules, clock.now())

    # Mock Triage to return clean terminal
    from agent.triage import TriageResult
    monkeypatch.setattr("agent.triage.triage", lambda r: TriageResult(matched="clean", recoverability=Recoverability.TERMINAL, is_ambiguous=False))

    # Even if we maliciously inject an AI port that proposes RETRY...
    class MaliciousDiagnosis(DiagnosisPort):
        def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
            return DiagnosisProposal(
                recoverability=Recoverability.TRANSIENT_INFRA, confidence=0.99, evidence=[],
                proposed_action=Action.RETRY, proposed_delay_minutes=0,
                expected_outcome=ExpectedOutcome(probability_of_success=0.99, horizon_minutes=0),
                risks=[], missing_information=[], rationale="Malicious override", fallback_tier=0
            )

    trace = process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=MaliciousDiagnosis(), executor=executor)
    
    # Expected Behaviour: Triage bypasses the model entirely because it's a `clean` terminal match.
    # The Policy Engine then enforces the TERMINAL_CLASS rule and denies it.
    assert "TERMINAL_CLASS" in trace.verdict.fired_rules
    assert trace.final_state == "ABANDONED"
    assert trace.diagnosis.rationale == "triage: clean taxonomy match"

# Scenario 8: Unsafe Action
def test_unsafe_action_pydantic_validation():
    # Expected Behaviour: Pydantic natively prevents instantiating an invalid ActionType
    with pytest.raises(ValidationError) as exc_info:
        DiagnosisProposal(
            recoverability=Recoverability.TRANSIENT_INFRA,
            confidence=0.99,
            evidence=[],
            proposed_action="REFUND", # Invalid action
            proposed_delay_minutes=-10, # Invalid delay but Pydantic enum catches action first
            expected_outcome=ExpectedOutcome(probability_of_success=0.99, horizon_minutes=0),
            risks=[], missing_information=[], rationale="", fallback_tier=0
        )
    assert "Input should be" in str(exc_info.value) # Enum validation error

# Scenario 9: Policy Denial (Attempt Cap)
def test_policy_denial_attempt_cap(setup):
    conn, rules, downtime, clock, executor = setup
    pf = _ambiguous_pf()
    ingest(conn, pf, 42, rules, clock.now())

    # Manually exhaust attempts
    conn.execute("UPDATE cases SET attempts = 5 WHERE case_id = ?", (pf.case_id,))
    
    class ConfidentDiagnosis(DiagnosisPort):
        def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
            return DiagnosisProposal(
                recoverability=Recoverability.TRANSIENT_INFRA, confidence=0.99, evidence=[],
                proposed_action=Action.RETRY, proposed_delay_minutes=0,
                expected_outcome=ExpectedOutcome(probability_of_success=0.99, horizon_minutes=0),
                risks=[], missing_information=[], rationale="", fallback_tier=0
            )

    trace = process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=ConfidentDiagnosis(), executor=executor)
    
    # Expected Behaviour: Policy Engine enforces ATTEMPT_CAP and DENIES the confident retry
    assert trace.verdict.decision == Decision.DENY
    assert "ATTEMPT_CAP" in trace.verdict.fired_rules
    assert trace.final_state == "ABANDONED"

# Scenario 10: Unknown Execution State (Transaction Rollback)
def test_unknown_execution_state_rollback(setup, monkeypatch):
    conn, rules, downtime, clock, executor = setup
    pf = _ambiguous_pf()
    ingest(conn, pf, 42, rules, clock.now())
    
    # Simulate process crash right before writing RECOVERED
    # We'll do this by raising an exception in the final audit.append call of process_case
    original_append = append
    def mock_append(c, case_id, actor, event_type, payload, ts):
        if event_type == "STATE_TRANSITION" and payload.get("to") in ("RECOVERED", "FAILED_ATTEMPT"):
            raise RuntimeError("SIGKILL simulation")
        return original_append(c, case_id=case_id, actor=actor, event_type=event_type, payload=payload, ts=ts)
    
    monkeypatch.setattr("agent.pipeline.append", mock_append)
    
    # Simulate process crash during execution (SIGKILL)
    def mock_execute(*args, **kwargs):
        raise RuntimeError("SIGKILL simulation")
    monkeypatch.setattr(executor, "execute", mock_execute)

    class ConfidentDiagnosis(DiagnosisPort):
        def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
            return DiagnosisProposal(
                recoverability=Recoverability.TRANSIENT_INFRA, confidence=0.99, evidence=[],
                proposed_action=Action.RETRY, proposed_delay_minutes=0,
                expected_outcome=ExpectedOutcome(probability_of_success=0.99, horizon_minutes=0),
                risks=[], missing_information=[], rationale="", fallback_tier=0
            )

    trace = None
    with pytest.raises(RuntimeError, match="SIGKILL simulation"):
        trace = process_case(conn, pf.case_id, clock=clock, rules=rules, downtime=downtime, diagnosis_port=ConfidentDiagnosis(), executor=executor)
    
    if trace:
        print("Verdict:", trace.verdict)
        print("Final state:", trace.final_state)
    
    # Expected Behaviour: Because the transaction rolled back on exception, the state remains EXECUTING
    row = get_case(conn, pf.case_id)
    assert row["state"] == "EXECUTING"
    
    # A subsequent reconciliation worker or watchdog will identify it as stranded.
