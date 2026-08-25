import io
import json
import logging
import random
import sqlite3
import pytest
from datetime import datetime, timezone

from agent.clock import VirtualClock
from agent.db import reset
from agent.diagnosis.port import DiagnosisInput, DiagnosisPort
from agent.downtime import DowntimeStore
from agent.executors.contracts import ActionErrorCode, ActionRefused, ExecutionUncertain, UncertaintyCode
from agent.executors.simulated import SimulatedExecutor
from agent.logger import (
    StructuredJsonFormatter,
    StructuredLogger,
    configure_logging,
    get_logger,
    log_context,
    redact_string,
    sanitize_data,
)
from agent.models import (
    Action,
    CaseState,
    Decision,
    DiagnosisProposal,
    ErrorObj,
    ExpectedOutcome,
    Instrument,
    Method,
    PaymentFailure,
    Recoverability,
)
from agent.pipeline import ingest, process_case
from agent.policy.engine import Rules
from agent.reconciliation import reconcile


class LogCaptureHandler(logging.Handler):
    """Test helper to capture structured log entries as parsed JSON dicts."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.entries: list[dict] = []
        self.setFormatter(StructuredJsonFormatter())

    def emit(self, record: logging.LogRecord):
        self.records.append(record)
        formatted = self.format(record)
        self.entries.append(json.loads(formatted))


@pytest.fixture
def log_capture():
    handler = LogCaptureHandler()
    logger = logging.getLogger("agent")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)


@pytest.fixture
def setup():
    conn = reset(":memory:")
    rules = Rules(version=2, kill_switch=False, holdout_fraction=0.0, by_id={})
    downtime = DowntimeStore(conn)
    clock = VirtualClock(datetime(2026, 8, 1, tzinfo=timezone.utc))
    executor = SimulatedExecutor(conn, clock, lambda v: 1.0, random.Random(42))
    return conn, rules, downtime, clock, executor


def _pf(case_id: str = "case_log_001") -> PaymentFailure:
    return PaymentFailure(
        case_id=case_id,
        customer_id="cust_log_1",
        order_id="order_log_1",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        method=Method.CARD,
        instrument=Instrument(network="visa", type="credit"),
        amount_paise=100_000,
        attempt_no=1,
        error=ErrorObj(
            code="BAD_REQUEST",
            source="gateway",
            step="payment_authentication",
            reason="payment_failed",
            description="",
        ),
    )


class StubDiagnosis(DiagnosisPort):
    def __init__(self, action: Action = Action.RETRY, confidence: float = 0.95):
        self.action = action
        self.confidence = confidence

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        return DiagnosisProposal(
            recoverability=Recoverability.TRANSIENT_INFRA,
            confidence=self.confidence,
            evidence=["error.reason"],
            proposed_action=self.action,
            proposed_delay_minutes=15,
            expected_outcome=ExpectedOutcome(probability_of_success=0.8, horizon_minutes=15),
            risks=[],
            missing_information=[],
            rationale="stub diagnosis for logging test",
            fallback_tier=0,
        )


# --- 1. Formatter & JSON Structure Tests ---

def test_structured_json_formatter():
    formatter = StructuredJsonFormatter()
    logger = get_logger("agent.test")
    record = logger.makeRecord(
        name="agent.test",
        level=logging.INFO,
        fn="test.py",
        lno=10,
        msg="test message",
        args=(),
        exc_info=None,
        extra={"event": "test.event", "latency_ms": 12.34, "data": {"key": "val"}},
    )

    formatted = formatter.format(record)
    entry = json.loads(formatted)

    assert entry["level"] == "INFO"
    assert entry["logger"] == "agent.test"
    assert entry["event"] == "test.event"
    assert entry["latency_ms"] == 12.34
    assert entry["data"] == {"key": "val"}
    assert "timestamp" in entry


def test_context_propagation():
    formatter = StructuredJsonFormatter()
    logger = get_logger("agent.test")

    with log_context(case_id="case_123", order_id="order_456", attempt_no=2):
        record = logger.makeRecord(
            name="agent.test",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="test",
            args=(),
            exc_info=None,
            extra={"event": "test.context"},
        )
        entry = json.loads(formatter.format(record))
        assert entry["case_id"] == "case_123"
        assert entry["order_id"] == "order_456"
        assert entry["attempt_no"] == 2
        assert entry["context"]["case_id"] == "case_123"


# --- 2. Sensitive Data & Secret Sanitization Tests ---

def test_redact_card_numbers():
    text = "User paid with card 4111 2222 3333 4444 and fallback 5555-5555-5555-5555."
    sanitized = redact_string(text)
    assert "4111 2222 3333 4444" not in sanitized
    assert "5555-5555-5555-5555" not in sanitized
    assert "****-****-****-4444" in sanitized
    assert "****-****-****-5555" in sanitized


def test_redact_api_keys_and_secrets():
    text = "Failed with key gsk_1234567890abcdef1234567890 and anthropic sk-ant-api03-abcdef1234567890 and Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    sanitized = redact_string(text)
    assert "gsk_" not in sanitized
    assert "sk-ant-" not in sanitized
    assert "Bearer eyJhb" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized


def test_sanitize_dict_sensitive_keys():
    payload = {
        "user": "alice",
        "api_key": "secret_key_123",
        "nested": {
            "cvv": "123",
            "password": "super_secret_pass",
            "normal_field": "visible",
        },
    }
    sanitized = sanitize_data(payload)
    assert sanitized["user"] == "alice"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["cvv"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert sanitized["nested"]["normal_field"] == "visible"


# --- 3. Request Lifecycle Logging Tests ---

def test_ingest_lifecycle_logging(setup, log_capture):
    conn, rules, downtime, clock, executor = setup
    pf = _pf("case_ingest_test")

    cohort = ingest(conn, pf, seed=42, rules=rules, now=clock.now())

    events = [e["event"] for e in log_capture.entries]
    assert "request.ingest.started" in events
    assert "request.ingest.completed" in events

    completed_entry = next(e for e in log_capture.entries if e["event"] == "request.ingest.completed")
    assert completed_entry["case_id"] == "case_ingest_test"
    assert completed_entry["order_id"] == pf.order_id
    assert "latency_ms" in completed_entry
    assert completed_entry["latency_ms"] >= 0.0
    assert completed_entry["data"]["cohort"] == cohort.value


# --- 4. Agent Decisions & Latency Logging Tests ---

def test_agent_decisions_and_latency_logging(setup, log_capture):
    conn, rules, downtime, clock, executor = setup
    pf = _pf("case_agent_test")
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())

    process_case(
        conn,
        pf.case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=StubDiagnosis(Action.RETRY, confidence=0.95),
        executor=executor,
    )

    events = {e["event"]: e for e in log_capture.entries if e.get("case_id") == "case_agent_test"}

    # Triage decision
    assert "agent.triage.completed" in events
    triage_entry = events["agent.triage.completed"]
    assert "latency_ms" in triage_entry
    assert triage_entry["latency_ms"] >= 0.0
    assert triage_entry["data"]["is_ambiguous"] is True

    # Diagnosis decision
    assert "agent.diagnosis.completed" in events
    diag_entry = events["agent.diagnosis.completed"]
    assert "latency_ms" in diag_entry
    assert diag_entry["latency_ms"] >= 0.0
    assert diag_entry["data"]["recoverability"] == "TRANSIENT_INFRA"
    assert diag_entry["data"]["confidence"] == 0.95
    assert diag_entry["data"]["proposed_action"] == "RETRY"


# --- 5. Policy Decisions Logging Tests ---

def test_policy_decisions_logging(setup, log_capture):
    conn, rules, downtime, clock, executor = setup
    rules.by_id["CONFIDENCE_FLOOR"] = {"enabled": True, "params": {"min_calibrated_confidence": 0.5}}
    pf = _pf("case_policy_test")
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())

    # Low confidence triggers REVIEW
    process_case(
        conn,
        pf.case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=StubDiagnosis(Action.RETRY, confidence=0.1),
        executor=executor,
    )

    events = {e["event"]: e for e in log_capture.entries if e.get("case_id") == "case_policy_test"}

    assert "policy.evaluate.completed" in events
    policy_entry = events["policy.evaluate.completed"]
    assert "latency_ms" in policy_entry
    assert policy_entry["data"]["decision"] == "REVIEW"
    assert policy_entry["data"]["action"] == "STOP"
    assert "CONFIDENCE_FLOOR" in policy_entry["data"]["fired_rules"]

    assert "policy.verdict.non_executable" in events
    non_exec_entry = events["policy.verdict.non_executable"]
    assert non_exec_entry["data"]["final_state"] == "QUARANTINED"


# --- 6. Execution Lifecycle & Error Logging Tests ---

def test_execution_lifecycle_and_errors(setup, log_capture):
    conn, rules, downtime, clock, executor = setup
    pf = _pf("case_exec_test")
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())

    process_case(
        conn,
        pf.case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=StubDiagnosis(Action.RETRY, confidence=0.9),
        executor=executor,
    )

    events = {e["event"]: e for e in log_capture.entries if e.get("case_id") == "case_exec_test"}

    assert "execution.dispatched" in events
    assert "execution.completed" in events
    exec_completed = events["execution.completed"]
    assert "latency_ms" in exec_completed
    assert exec_completed["data"]["succeeded"] is True


def test_execution_refused_error_logging(setup, log_capture, monkeypatch):
    conn, rules, downtime, clock, executor = setup
    pf = _pf("case_refused_test")
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())

    def mock_refused(verdict):
        raise ActionRefused(ActionErrorCode.DUPLICATE_IN_FLIGHT, "in flight conflict")

    monkeypatch.setattr(executor, "execute", mock_refused)

    process_case(
        conn,
        pf.case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=StubDiagnosis(Action.RETRY, confidence=0.9),
        executor=executor,
    )

    refused_entry = next(
        e for e in log_capture.entries
        if e.get("case_id") == "case_refused_test" and e["event"] == "execution.refused"
    )
    assert refused_entry["level"] == "WARNING"
    assert refused_entry["data"]["code"] == ActionErrorCode.DUPLICATE_IN_FLIGHT.value
    assert refused_entry["data"]["retryable"] is True
    assert "latency_ms" in refused_entry


def test_execution_uncertain_error_logging(setup, log_capture, monkeypatch):
    conn, rules, downtime, clock, executor = setup
    pf = _pf("case_uncertain_test")
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())

    def mock_uncertain(verdict):
        raise ExecutionUncertain(UncertaintyCode.EXECUTION_TIMEOUT, "timed out waiting", idempotency_key="key_123")

    monkeypatch.setattr(executor, "execute", mock_uncertain)

    process_case(
        conn,
        pf.case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=StubDiagnosis(Action.RETRY, confidence=0.9),
        executor=executor,
    )

    uncertain_entry = next(
        e for e in log_capture.entries
        if e.get("case_id") == "case_uncertain_test" and e["event"] == "execution.uncertain"
    )
    assert uncertain_entry["level"] == "ERROR"
    assert uncertain_entry["data"]["code"] == UncertaintyCode.EXECUTION_TIMEOUT.value
    assert "latency_ms" in uncertain_entry


# --- 7. Reconciliation Logging Tests ---

def test_reconciliation_logging(setup, log_capture, monkeypatch):
    conn, rules, downtime, clock, executor = setup
    pf = _pf("case_reconcile_test")
    ingest(conn, pf, seed=42, rules=rules, now=clock.now())

    def mock_uncertain(verdict):
        raise ExecutionUncertain(UncertaintyCode.EXECUTION_TIMEOUT, "timed out", idempotency_key="key_rec_123")

    monkeypatch.setattr(executor, "execute", mock_uncertain)

    process_case(
        conn,
        pf.case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=StubDiagnosis(Action.RETRY, confidence=0.9),
        executor=executor,
    )

    # Now reconcile
    from agent.models import ActionOutcome
    reconcile(conn, pf.case_id, actual_outcome=ActionOutcome.SUCCEEDED, ts=clock.now())

    events = [e for e in log_capture.entries if e.get("case_id") == "case_reconcile_test"]
    rec_started = next(e for e in events if e["event"] == "reconciliation.started")
    rec_resolved = next(e for e in events if e["event"] == "reconciliation.resolved")

    assert rec_started is not None
    assert rec_resolved["data"]["target_state"] == "RECOVERED"
    assert rec_resolved["data"]["actual_outcome"] == "SUCCEEDED"
    assert "latency_ms" in rec_resolved
    assert rec_resolved["latency_ms"] >= 0.0
