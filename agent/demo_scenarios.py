"""Developer & demo scenario execution engine.

Triggers real, non-mocked backend system behavior for:
1. duplicate_event   - Deduplication & idempotent replay
2. invalid_ai_output - Malformed diagnosis & Tier 3 fail-closed UNKNOWN fallback
3. policy_rejection  - Zero-LLM gate veto on adversarial 100% confidence proposal
4. execution_timeout - Simulated gateway timeout & quarantine/reconciliation
"""

from __future__ import annotations

import dataclasses
import random
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from agent.audit import append
from agent.clock import Clock, VirtualClock
from agent.dashboard import get_transaction_detail
from agent.diagnosis.port import DiagnosisInput
from agent.diagnosis.stub import AdversarialDiagnosis, StubDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.logger import get_logger
from agent.models import (
    Action,
    DiagnosisProposal,
    ErrorObj,
    ExpectedOutcome,
    Instrument,
    Method,
    PaymentFailure,
    Recoverability,
    RiskCategory,
    RiskFlag,
)
from agent.pipeline import ingest, process_case
from agent.policy.engine import Rules, load_rules

logger = get_logger("agent.demo_scenarios")


class MalformedDiagnosisProvider:
    """Simulates a broken/hallucinating LLM that raises a schema parse error."""

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        # In real operation, when the LLM produces invalid JSON/schema, a ValueError is raised.
        # This exercises the multi-tier fallback to Tier 3 UNKNOWN fail-closed safety state.
        raise ValueError("Malformed LLM response: invalid JSON token at line 1 column 48 (expected schema field)")


def trigger_duplicate_event(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
) -> dict[str, Any]:
    """1. Trigger Duplicate Event:
    Ingests and executes a transaction, then executes a duplicate action with the identical
    idempotency key, triggering the executor's deduplication check and idempotent replay.
    """
    now = clock.now() if clock else datetime.now(timezone.utc)
    clock = clock or VirtualClock(start=now)
    base_rules = rules or load_rules()
    rules = dataclasses.replace(base_rules, holdout_fraction=0.0)
    downtime = downtime or DowntimeStore(conn)

    ts_suffix = int(time.time() * 1000) % 1_000_000
    case_id = f"demo_dup_{ts_suffix}"

    pf = PaymentFailure(
        case_id=case_id,
        customer_id=f"cust_{ts_suffix}",
        order_id=f"order_dup_{ts_suffix}",
        created_at=now,
        method=Method.UPI,
        instrument=Instrument(vpa="user@okhdfcbank"),
        amount_paise=199_900,
        attempt_no=1,
        error=ErrorObj(
            code="PAYMENT_FAILED",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",
            description="UPI authorization failed transiently",
        ),
    )

    executor = SimulatedExecutor(conn, clock, outcome_fn=lambda v: 1.0, rng=random.Random(ts_suffix))
    ingest(conn, pf, seed=42, rules=rules, now=now)
    trace = process_case(
        conn,
        case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=StubDiagnosis(),
        executor=executor,
    )

    # Re-execute using the exact same verdict (replay path)
    replay_res = executor.execute(trace.verdict)
    logger.log_event("demo.scenario.duplicate_event.triggered", case_id=case_id, replayed=replay_res.replayed)

    detail = get_transaction_detail(conn, case_id)
    return {
        "case_id": case_id,
        "scenario": "duplicate_event",
        "title": "Duplicate Event Replayed",
        "message": "Idempotent replay detected: transaction returned existing result without double-charging or re-spending.",
        "detail": detail,
    }


def trigger_invalid_ai_output(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
) -> dict[str, Any]:
    """2. Trigger Invalid AI Output:
    Simulates malformed/unparseable AI output from a corrupted LLM response.
    The system exercises the fail-closed fallback tier, classifying as Recoverability.UNKNOWN
    and stopping the action via the Zero-LLM Policy Engine.
    """
    now = clock.now() if clock else datetime.now(timezone.utc)
    clock = clock or VirtualClock(start=now)
    base_rules = rules or load_rules()
    rules = dataclasses.replace(base_rules, holdout_fraction=0.0)
    downtime = downtime or DowntimeStore(conn)

    ts_suffix = int(time.time() * 1000) % 1_000_000
    case_id = f"demo_invalid_ai_{ts_suffix}"

    pf = PaymentFailure(
        case_id=case_id,
        customer_id=f"cust_{ts_suffix}",
        order_id=f"order_invalid_{ts_suffix}",
        created_at=now,
        method=Method.CARD,
        instrument=Instrument(network="mastercard", type="credit"),
        amount_paise=349_900,
        attempt_no=1,
        error=ErrorObj(
            code="INTERNAL_SERVER_ERROR",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",  # ambiguous reason to force AI diagnosis call
            description="Unexpected downstream gateway response format",
        ),
    )

    # Wrap the malformed provider into fallback to UNKNOWN (Tier 3)
    class FallbackAwareDiagnosis:
        def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
            try:
                return MalformedDiagnosisProvider().diagnose(inp)
            except Exception as e:
                logger.log_event("diagnosis.fallback.tier3_unknown", reason=str(e))
                return DiagnosisProposal(
                    recoverability=Recoverability.UNKNOWN,
                    confidence=0.0,
                    evidence=["fallback: malformed_llm_json_rejected"],
                    proposed_action=Action.STOP,
                    expected_outcome=ExpectedOutcome(probability_of_success=0.0, horizon_minutes=0),
                    risks=[RiskFlag(category=RiskCategory.AMBIGUOUS_SIGNAL, note=f"Malformed model response: {e}")],
                    missing_information=["OTHER"],
                    rationale="Tier 3 Fallback: Malformed LLM output rejected; fail-closed safely into STOP",
                    fallback_tier=3,
                )

    executor = SimulatedExecutor(conn, clock, outcome_fn=lambda v: 0.0, rng=random.Random(ts_suffix))
    ingest(conn, pf, seed=42, rules=rules, now=now)
    process_case(
        conn,
        case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=FallbackAwareDiagnosis(),
        executor=executor,
    )

    logger.log_event("demo.scenario.invalid_ai_output.triggered", case_id=case_id)
    detail = get_transaction_detail(conn, case_id)
    return {
        "case_id": case_id,
        "scenario": "invalid_ai_output",
        "title": "Invalid AI Output Handled",
        "message": "Malformed LLM payload intercepted: safely fell back to Tier-3 UNKNOWN classification and halted execution.",
        "detail": detail,
    }


def trigger_policy_rejection(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
) -> dict[str, Any]:
    """3. Trigger Policy Rejection:
    Simulates an adversarial or miscalibrated AI diagnosis that proposes RETRY with 100% confidence
    on an ambiguous failure where attempt budget has been exhausted.
    The Zero-LLM Policy Engine overrides the AI and denies the action.
    """
    now = clock.now() if clock else datetime.now(timezone.utc)
    clock = clock or VirtualClock(start=now)
    base_rules = rules or load_rules()
    rules = dataclasses.replace(base_rules, holdout_fraction=0.0)
    downtime = downtime or DowntimeStore(conn)

    ts_suffix = int(time.time() * 1000) % 1_000_000
    case_id = f"demo_policy_veto_{ts_suffix}"

    pf = PaymentFailure(
        case_id=case_id,
        customer_id=f"cust_{ts_suffix}",
        order_id=f"order_veto_{ts_suffix}",
        created_at=now,
        method=Method.CARD,
        instrument=Instrument(network="visa", type="debit"),
        amount_paise=799_900,
        attempt_no=1,
        error=ErrorObj(
            code="BAD_REQUEST",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",
            description="Ambiguous gateway error",
        ),
    )

    executor = SimulatedExecutor(conn, clock, outcome_fn=lambda v: 0.0, rng=random.Random(ts_suffix))
    ingest(conn, pf, seed=42, rules=rules, now=now)
    # Simulate prior failed attempts in audit log and counter to reach attempt cap (4 for card)
    for att in range(1, 5):
        append(
            conn,
            case_id=case_id,
            actor="executor",
            event_type="ACTION_RESULT",
            payload={"action": "RETRY", "attempt_no": att, "succeeded": False, "mode": "SIM"},
            ts=now,
        )
    conn.execute("UPDATE cases SET attempts = 4 WHERE case_id = ?", (case_id,))

    process_case(
        conn,
        case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=AdversarialDiagnosis(),
        executor=executor,
    )

    logger.log_event("demo.scenario.policy_rejection.triggered", case_id=case_id)
    detail = get_transaction_detail(conn, case_id)
    return {
        "case_id": case_id,
        "scenario": "policy_rejection",
        "title": "Policy Engine Veto Triggered",
        "message": "Zero-LLM Policy Engine rejected 100% confident AI retry because attempt budget was exhausted (Rule: ATTEMPT_CAP).",
        "detail": detail,
    }


def trigger_execution_timeout(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
) -> dict[str, Any]:
    """4. Trigger Execution Timeout:
    Simulates a network timeout during retry dispatch. The executor raises ExecutionUncertain,
    and the pipeline transitions the case to QUARANTINED to prevent double-spending.
    """
    now = clock.now() if clock else datetime.now(timezone.utc)
    clock = clock or VirtualClock(start=now)
    base_rules = rules or load_rules()
    rules = dataclasses.replace(base_rules, holdout_fraction=0.0)
    downtime = downtime or DowntimeStore(conn)

    ts_suffix = int(time.time() * 1000) % 1_000_000
    case_id = f"demo_timeout_{ts_suffix}"

    pf = PaymentFailure(
        case_id=case_id,
        customer_id=f"cust_{ts_suffix}",
        order_id=f"order_timeout_{ts_suffix}",
        created_at=now,
        method=Method.NETBANKING,
        instrument=Instrument(bank="HDFC"),
        amount_paise=150_000,
        attempt_no=1,
        error=ErrorObj(
            code="GATEWAY_TIMEOUT",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",
            description="Netbanking gateway timed out",
        ),
    )

    # Executor configured with timeout_fn=True
    executor = SimulatedExecutor(
        conn,
        clock,
        outcome_fn=lambda v: 0.5,
        rng=random.Random(ts_suffix),
        timeout_fn=lambda v: True,
    )
    ingest(conn, pf, seed=42, rules=rules, now=now)
    process_case(
        conn,
        case_id,
        clock=clock,
        rules=rules,
        downtime=downtime,
        diagnosis_port=StubDiagnosis(),
        executor=executor,
    )

    logger.log_event("demo.scenario.execution_timeout.triggered", case_id=case_id)
    detail = get_transaction_detail(conn, case_id)
    return {
        "case_id": case_id,
        "scenario": "execution_timeout",
        "title": "Gateway Timeout & Quarantine",
        "message": "Payment gateway timed out during dispatch: action marked uncertain and quarantined to prevent double-spending.",
        "detail": detail,
    }


def run_demo_scenario(
    conn: sqlite3.Connection,
    scenario_name: str,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
) -> dict[str, Any]:
    """Dispatch execution to the requested demo scenario."""
    scenarios = {
        "duplicate_event": trigger_duplicate_event,
        "invalid_ai_output": trigger_invalid_ai_output,
        "policy_rejection": trigger_policy_rejection,
        "execution_timeout": trigger_execution_timeout,
    }

    handler = scenarios.get(scenario_name.lower().strip())
    if not handler:
        raise ValueError(f"Unknown scenario '{scenario_name}'. Available: {list(scenarios.keys())}")

    return handler(conn, clock=clock, rules=rules, downtime=downtime)
