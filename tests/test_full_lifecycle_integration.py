"""End-to-End System Integration Test Suite.

Verifies the complete pipeline flow:
  Ingestion
  -> Reasoning (Triage & Diagnosis)
  -> Policy (Zero-LLM Gate)
  -> Execution (Simulated & Idempotent)
  -> State (Transitions & Concurrency)
  -> Audit (Cryptographic Hash-Chain & Decision Record)
  -> Metrics (7 Core KPIs & Lift)
  -> UI API (Ledger, 9-Phase Detail, Traces, Demo Controls)
"""

from __future__ import annotations

import json
import random
import sqlite3
import pytest
from datetime import datetime, timedelta, timezone

from agent import db as agent_db
from agent.audit import events_for, verify_chain
from agent.clock import VirtualClock
from agent.dashboard import (
    compute_dashboard_metrics,
    get_transaction_detail,
    get_transaction_trace,
    get_transactions_summary,
)
from agent.demo_scenarios import run_demo_scenario
from agent.diagnosis.stub import AdversarialDiagnosis, StubDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.models import (
    Action,
    CaseState,
    Cohort,
    Decision,
    ErrorObj,
    Instrument,
    Method,
    PaymentFailure,
    Recoverability,
)
from agent.pipeline import ingest, process_case
from agent.policy.engine import load_rules
from agent.reconciliation import reconcile


@pytest.fixture
def full_system():
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    downtime = DowntimeStore(conn)
    clock = VirtualClock(start=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))
    return conn, rules, downtime, clock


def test_full_pipeline_ingest_to_ui(full_system):
    conn, rules, downtime, clock = full_system
    executor = SimulatedExecutor(conn, clock, outcome_fn=lambda v: 1.0, rng=random.Random(42))
    diagnosis = StubDiagnosis()

    # 1. INGESTION
    pf = PaymentFailure(
        case_id="e2e_case_001",
        customer_id="cust_e2e_001",
        order_id="order_e2e_001",
        created_at=clock.now(),
        method=Method.CARD,
        instrument=Instrument(network="visa", type="credit"),
        amount_paise=250_000,
        attempt_no=1,
        error=ErrorObj(
            code="BAD_REQUEST",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",
            description="Payment authorization failed at card network",
        ),
    )

    cohort = ingest(conn, pf, seed=42, rules=rules, now=clock.now())
    assert cohort in (Cohort.TREATED, Cohort.HOLDOUT)

    # Verify ingestion audit events
    events = events_for(conn, pf.case_id)
    event_types = [e["event_type"] for e in events]
    assert "SIGNAL_RECEIVED" in event_types
    assert "COHORT_ASSIGNED" in event_types

    # 2. REASONING & 3. POLICY & 4. EXECUTION & 5. STATE & 6. AUDIT
    trace = process_case(
        conn,
        pf.case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=diagnosis,
        executor=executor,
    )

    assert trace.case_id == pf.case_id
    assert trace.final_state in ("RECOVERED", "FAILED_ATTEMPT", "HOLDOUT_CLOSED", "ABANDONED", "QUARANTINED")

    # Verify cryptographic audit chain integrity
    assert verify_chain(conn) is True

    # Verify unified terminal audit event
    updated_events = events_for(conn, pf.case_id)
    updated_types = [e["event_type"] for e in updated_events]
    assert "TRIAGE_RESULT" in updated_types
    assert "POLICY_VERDICT" in updated_types
    assert "DECISION_RECORDED" in updated_types

    # 7. METRICS
    metrics = compute_dashboard_metrics(conn)
    assert metrics["total_cases"] == 1
    assert metrics["revenue_at_risk_rupees"] == 2500.0
    assert metrics["recovery_rate_pct"] >= 0.0
    assert metrics["actions_executed"] >= 0
    assert metrics["ai_confidence_pct"] >= 0.0
    assert metrics["failure_rate_pct"] >= 0.0

    # 8. UI & API
    summary = get_transactions_summary(conn, search="e2e_case_001")
    assert summary["total"] == 1
    tx = summary["transactions"][0]
    assert tx["case_id"] == "e2e_case_001"
    assert tx["amount_rupees"] == 2500.0
    assert tx["error_reason"] == "payment_failed"

    detail = get_transaction_detail(conn, pf.case_id)
    assert detail["case_id"] == pf.case_id
    assert detail["event"]["amount_rupees"] == 2500.0
    assert detail["audit_trail"]["chain_valid"] is True
    assert len(detail["audit_trail"]["timeline"]) == len(updated_events)


def test_quarantine_reconciliation_integration(full_system):
    conn, rules, downtime, clock = full_system

    # Create a case that times out and gets quarantined
    pf = PaymentFailure(
        case_id="e2e_timeout_001",
        customer_id="cust_timeout",
        order_id="order_timeout",
        created_at=clock.now(),
        method=Method.UPI,
        instrument=Instrument(vpa="user@okhdfcbank"),
        amount_paise=100_000,
        attempt_no=1,
        error=ErrorObj(
            code="TIMEOUT",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",
            description="Gateway timeout",
        ),
    )

    timeout_executor = SimulatedExecutor(
        conn,
        clock,
        outcome_fn=lambda v: 1.0,
        rng=random.Random(42),
        timeout_fn=lambda v: True,
    )

    ingest(conn, pf, seed=42, rules=rules, now=clock.now())
    # Force treated cohort to test timeout path
    conn.execute("UPDATE cases SET cohort = 'TREATED' WHERE case_id = 'e2e_timeout_001'")

    process_case(
        conn,
        pf.case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=StubDiagnosis(),
        executor=timeout_executor,
    )

    # Verify quarantined
    row = conn.execute("SELECT state FROM cases WHERE case_id = 'e2e_timeout_001'").fetchone()
    assert row["state"] == "QUARANTINED"

    # Run real reconciliation
    reconciled = reconcile(conn, clock=clock, order_status_fn=lambda oid: "SUCCESS")
    assert "e2e_timeout_001" in reconciled
    assert reconciled["e2e_timeout_001"] == "RECOVERED"

    # Verify final landing state
    row_after = conn.execute("SELECT state FROM cases WHERE case_id = 'e2e_timeout_001'").fetchone()
    assert row_after["state"] == "RECOVERED"
    assert verify_chain(conn) is True


def test_all_demo_scenarios_integration(full_system):
    conn, rules, downtime, clock = full_system

    scenarios = ["duplicate_event", "invalid_ai_output", "policy_rejection", "execution_timeout"]
    for sc in scenarios:
        res = run_demo_scenario(conn, sc, clock=clock, rules=rules, downtime=downtime)
        assert res["scenario"] == sc
        assert res["case_id"] is not None
        assert res["detail"]["audit_trail"]["chain_valid"] is True

    # Verify global chain verification after running all demo scenarios
    assert verify_chain(conn) is True
    metrics = compute_dashboard_metrics(conn)
    assert metrics["total_cases"] >= 4
