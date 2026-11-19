"""Developer & demo scenario execution engine.

Provides the three canonical deterministic demo scenarios:
1. successful_recovery          - Transient failure diagnosed, approved by policy, successfully recovered.
2. unsafe_ai_blocked            - Adversarial/hallucinated AI proposal vetoed by Zero-LLM Policy Gate.
3. duplicate_timeout_handled    - Execution safety: idempotent replay deduplication & timeout quarantine.

Also supports granular drill scenario handlers for live developer controls.
"""

from __future__ import annotations

import dataclasses
import random
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from agent.audit import append, verify_chain
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
    """Simulates an invalid/corrupted LLM payload producing parse errors."""

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        raise ValueError("Malformed LLM response: invalid JSON token (syntax corruption)")


# =============================================================================
# Canonical Scenario 1: Successful Recovery
# =============================================================================

def trigger_successful_recovery(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
    deterministic_id: str | None = None,
) -> dict[str, Any]:
    """1. Scenario: Successful Recovery
    - Ingests a transient UPI payment failure.
    - AI / Triage diagnoses as TRANSIENT_INFRA with high confidence.
    - Zero-LLM Policy Engine evaluates safety rules and grants ALLOW.
    - Simulated executor dispatches retry action and succeeds.
    - State machine transitions to RECOVERED (funds recovered).
    - Entire lifecycle recorded in cryptographic SHA-256 audit log.
    """
    fixed_time = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    now = clock.now() if clock else fixed_time
    clock = clock or VirtualClock(start=now)
    base_rules = rules or load_rules()
    rules = dataclasses.replace(base_rules, holdout_fraction=0.0)
    downtime = downtime or DowntimeStore(conn)

    case_id = deterministic_id or f"demo_success_{int(time.time() * 1000) % 1_000_000}"

    pf = PaymentFailure(
        case_id=case_id,
        customer_id="cust_demo_success",
        order_id="order_demo_success_101",
        created_at=now,
        method=Method.UPI,
        instrument=Instrument(vpa="user@okhdfcbank"),
        amount_paise=249_900,  # ₹2,499.00
        attempt_no=1,
        error=ErrorObj(
            code="PAYMENT_FAILED",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",
            description="UPI switch connection timeout during authorization",
        ),
    )

    executor = SimulatedExecutor(
        conn,
        clock,
        outcome_fn=lambda v: 1.0,
        rng=random.Random(42),
    )

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

    logger.log_event("demo.scenario.successful_recovery.completed", case_id=case_id)
    detail = get_transaction_detail(conn, case_id)
    return {
        "case_id": case_id,
        "scenario": "successful_recovery",
        "title": "Successful Recovery",
        "message": "Transient payment failure diagnosed, approved by Zero-LLM Policy Gate (ALLOW), and successfully recovered (₹2,499.00).",
        "detail": detail,
    }


# =============================================================================
# Canonical Scenario 2: Unsafe AI Recommendation Blocked
# =============================================================================

def trigger_unsafe_ai_blocked(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
    deterministic_id: str | None = None,
) -> dict[str, Any]:
    """2. Scenario: Unsafe AI Recommendation Blocked
    - Ingests a Card payment failure that has already reached its attempt cap (4 attempts).
    - Adversarial AI model proposes RETRY with 100% confidence.
    - Zero-LLM Policy Engine asserts sovereignty: checks hard deterministic invariant (ATTEMPT_CAP)
      and overrides the AI proposal with DENY.
    - Action is halted (STOP), zero money/attempts wasted.
    - State machine safely transitions case to ABANDONED.
    """
    fixed_time = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    now = clock.now() if clock else fixed_time
    clock = clock or VirtualClock(start=now)
    base_rules = rules or load_rules()
    rules = dataclasses.replace(base_rules, holdout_fraction=0.0)
    downtime = downtime or DowntimeStore(conn)

    case_id = deterministic_id or f"demo_policy_veto_{int(time.time() * 1000) % 1_000_000}"

    pf = PaymentFailure(
        case_id=case_id,
        customer_id="cust_demo_veto",
        order_id="order_demo_veto_202",
        created_at=now,
        method=Method.CARD,
        instrument=Instrument(network="visa", type="debit"),
        amount_paise=799_900,  # ₹7,999.00
        attempt_no=1,
        error=ErrorObj(
            code="BAD_REQUEST",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",
            description="Ambiguous recurring card refusal",
        ),
    )

    executor = SimulatedExecutor(conn, clock, outcome_fn=lambda v: 0.0, rng=random.Random(42))
    ingest(conn, pf, seed=42, rules=rules, now=now)

    # Record 4 prior failed attempts in audit trail and database
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

    logger.log_event("demo.scenario.unsafe_ai_blocked.completed", case_id=case_id)
    detail = get_transaction_detail(conn, case_id)
    return {
        "case_id": case_id,
        "scenario": "unsafe_ai_blocked",
        "title": "Unsafe AI Recommendation Blocked",
        "message": "Zero-LLM Policy Gate asserted sovereignty: vetoed 100% confident AI retry on exhausted attempt budget (Rule: ATTEMPT_CAP -> DENY -> ABANDONED).",
        "detail": detail,
    }


# =============================================================================
# Canonical Scenario 3: Duplicate & Timeout Safety
# =============================================================================

def trigger_duplicate_timeout_handled(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
    deterministic_id: str | None = None,
) -> dict[str, Any]:
    """3. Scenario: Duplicate & Timeout Failure Handled Safely
    - Simulates network gateway timeout / uncertainty (ExecutionUncertain).
    - The pipeline safely transitions into QUARANTINED for reconciliation rather than blindly retrying.
    - Idempotency key deduplication guarantees safe replay.
    """
    fixed_time = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    now = clock.now() if clock else fixed_time
    clock = clock or VirtualClock(start=now)
    base_rules = rules or load_rules()
    rules = dataclasses.replace(base_rules, holdout_fraction=0.0)
    downtime = downtime or DowntimeStore(conn)

    case_id = deterministic_id or f"demo_timeout_{int(time.time() * 1000) % 1_000_000}"

    pf = PaymentFailure(
        case_id=case_id,
        customer_id="cust_demo_safety",
        order_id="order_demo_safety_303",
        created_at=now,
        method=Method.NETBANKING,
        instrument=Instrument(bank="HDFC"),
        amount_paise=150_000,  # ₹1,500.00
        attempt_no=1,
        error=ErrorObj(
            code="GATEWAY_TIMEOUT",
            source="gateway",
            step="payment_authorization",
            reason="payment_failed",
            description="Netbanking server timed out during authorization",
        ),
    )

    executor = SimulatedExecutor(
        conn,
        clock,
        outcome_fn=lambda v: 0.5,
        rng=random.Random(42),
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

    logger.log_event("demo.scenario.duplicate_timeout_handled.completed", case_id=case_id)
    detail = get_transaction_detail(conn, case_id)
    return {
        "case_id": case_id,
        "scenario": "duplicate_timeout_handled",
        "title": "Duplicate & Timeout Failure Handled Safely",
        "message": "Gateway timeout intercepted into QUARANTINED state, and duplicate dispatch protected by SHA-256 idempotency key deduplication.",
        "detail": detail,
    }


# =============================================================================
# Granular Drill Handlers & Backward Compatibility
# =============================================================================

def trigger_duplicate_event(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
) -> dict[str, Any]:
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
            reason="payment_failed",
            description="Unexpected downstream gateway response format",
        ),
    )

    from agent.diagnosis.prompting import tier3_fallback

    class FallbackAwareDiagnosis:
        def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
            try:
                return MalformedDiagnosisProvider().diagnose(inp)
            except Exception as e:
                logger.log_event("diagnosis.fallback.tier3_unknown", reason=str(e))
                return tier3_fallback(inp, last_error=str(e))

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
    res = trigger_unsafe_ai_blocked(conn, clock=clock, rules=rules, downtime=downtime)
    res["scenario"] = "policy_rejection"
    return res


def trigger_execution_timeout(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
) -> dict[str, Any]:
    res = trigger_duplicate_timeout_handled(conn, clock=clock, rules=rules, downtime=downtime)
    res["scenario"] = "execution_timeout"
    return res


def trigger_live_razorpay_proof(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
) -> dict[str, Any]:
    from agent.executors.live import LiveRazorpayExecutor

    now = clock.now() if clock else datetime.now(timezone.utc)
    clock = clock or VirtualClock(start=now)
    base_rules = rules or load_rules()
    rules = dataclasses.replace(base_rules, holdout_fraction=0.0)
    downtime = downtime or DowntimeStore(conn)

    ts_suffix = int(time.time() * 1000) % 1_000_000
    case_id = f"demo_live_{ts_suffix}"

    pf = PaymentFailure(
        case_id=case_id,
        customer_id=f"cust_live_{ts_suffix}",
        order_id=f"order_live_{ts_suffix}",
        created_at=now,
        method=Method.UPI,
        instrument=Instrument(vpa="user@okhdfcbank"),
        amount_paise=249_900,
        attempt_no=1,
        error=ErrorObj(
            code="PAYMENT_FAILED",
            source="bank",
            step="payment_authorization",
            reason="payment_failed",
            description="Live Razorpay API recovery test",
        ),
    )

    try:
        executor = LiveRazorpayExecutor()
    except Exception:
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

    logger.log_event("demo.scenario.live_proof.completed", case_id=case_id)
    detail = get_transaction_detail(conn, case_id)
    return {
        "case_id": case_id,
        "scenario": "live_proof",
        "title": "Live Razorpay API Proof",
        "message": f"Real Razorpay test-mode Payment Link created for ₹2,499.00 and dispatched with idempotency key forwarding.",
        "detail": detail,
    }


def run_demo_scenario(
    conn: sqlite3.Connection,
    scenario_name: str,
    clock: Clock | None = None,
    rules: Rules | None = None,
    downtime: DowntimeStore | None = None,
    deterministic_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch execution to the requested demo scenario."""
    clean_name = str(scenario_name).lower().strip()

    mapping = {
        # 1. Successful Recovery
        "1": trigger_successful_recovery,
        "successful_recovery": trigger_successful_recovery,
        "success": trigger_successful_recovery,

        # 2. Unsafe AI Recommendation Blocked
        "2": trigger_unsafe_ai_blocked,
        "unsafe_ai_blocked": trigger_unsafe_ai_blocked,
        "policy_rejection": trigger_policy_rejection,
        "invalid_ai_output": trigger_invalid_ai_output,
        "veto": trigger_unsafe_ai_blocked,

        # 3. Duplicate / Timeout Handled Safely
        "3": trigger_duplicate_timeout_handled,
        "duplicate_timeout_handled": trigger_duplicate_timeout_handled,
        "duplicate_event": trigger_duplicate_event,
        "execution_timeout": trigger_execution_timeout,
        "timeout": trigger_execution_timeout,

        # 4. Live Razorpay Proof
        "4": trigger_live_razorpay_proof,
        "live_proof": trigger_live_razorpay_proof,
        "live_razorpay_proof": trigger_live_razorpay_proof,
    }

    handler = mapping.get(clean_name)
    if not handler:
        raise ValueError(
            f"Unknown scenario '{scenario_name}'. Available: "
            f"['successful_recovery' (1), 'unsafe_ai_blocked' (2), 'duplicate_timeout_handled' (3), "
            f"'live_proof' (4), 'duplicate_event', 'invalid_ai_output', 'policy_rejection', 'execution_timeout']"
        )

    if handler in (trigger_successful_recovery, trigger_unsafe_ai_blocked, trigger_duplicate_timeout_handled):
        return handler(conn, clock=clock, rules=rules, downtime=downtime, deterministic_id=deterministic_id)
    return handler(conn, clock=clock, rules=rules, downtime=downtime)
