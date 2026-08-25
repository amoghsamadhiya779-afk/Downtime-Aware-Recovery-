"""Wires the five layers together: ingest -> triage -> diagnose -> policy -> execute,
with every step appended to the audit log (ARCHITECTURE §3).

This is the ONE code path (invariant 1). Live and replay differ only in which Clock
and ExecutorPort are injected here — nothing in this file branches on mode.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from agent.audit import append
from agent.clock import Clock
from agent.diagnosis.port import DiagnosisInput, DiagnosisPort
from agent.downtime import DowntimeStore
from agent.executors.port import ExecutorPort
from agent.ledger import assign_cohort
from agent.models import (
    Action,
    CaseState,
    CaseView,
    Cohort,
    DiagnosisProposal,
    PaymentFailure,
    Recoverability,
    Verdict,
)
from agent.policy.engine import Rules, evaluate
from agent.state import create_case, get_case, to_payment_failure, transition


@dataclass
class DecisionTrace:
    """Everything a stranger needs to follow one case end to end (acceptance
    criterion 8) — this is exactly what `make demo` prints."""

    case_id: str
    cohort: Cohort
    triage_class: str
    triage_ambiguous: bool
    diagnosis: DiagnosisProposal | None
    verdict: Verdict
    action_succeeded: bool | None
    final_state: str


def ingest(conn: sqlite3.Connection, pf: PaymentFailure, seed: int, rules: Rules, now) -> Cohort:
    cohort = assign_cohort(pf.case_id, seed, rules.holdout_fraction)
    create_case(conn, pf, cohort)
    append(
        conn,
        case_id=pf.case_id,
        actor="ingest",
        event_type="SIGNAL_RECEIVED",
        payload={"order_id": pf.order_id, "method": pf.method.value, "attempt_no": pf.attempt_no},
        ts=now,
    )
    append(
        conn,
        case_id=pf.case_id,
        actor="ledger",
        event_type="COHORT_ASSIGNED",
        payload={"cohort": cohort.value, "seed": seed},
        ts=now,
    )
    return cohort


def process_case(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    clock: Clock,
    rules: Rules,
    downtime: DowntimeStore,
    diagnosis_port: DiagnosisPort,
    executor: ExecutorPort,
) -> DecisionTrace:
    """Run one case through triage -> diagnose -> policy -> execute -> audit.

    Every branch appends an audit event before returning, so a partial run is always
    replayable rather than silently lost.
    """
    from agent.triage import triage as run_triage

    row = get_case(conn, case_id)
    pf = to_payment_failure(row)
    now = clock.now()

    tr = run_triage(pf.error.reason)
    append(conn, case_id=case_id, actor="triage", event_type="TRIAGE_RESULT", payload=tr.as_payload(), ts=now)

    dctx = downtime.context_at(pf.method, pf.instrument, now)

    if tr.is_ambiguous:
        inp = DiagnosisInput(
            method=pf.method,
            error=pf.error,
            amount_paise=pf.amount_paise,
            attempt_no=pf.attempt_no,
            prior_failures=row["attempts"],
            downtime=dctx,
        )
        proposal = diagnosis_port.diagnose(inp)
    elif tr.matched == "clean":
        # A definite class the rules resolved on their own — never reaches the model.
        action = Action.STOP if tr.recoverability is Recoverability.TERMINAL else Action.RETRY
        proposal = DiagnosisProposal(
            recoverability=tr.recoverability,
            confidence=1.0,
            proposed_action=action,
            proposed_delay_minutes=15,
            rationale="triage: clean taxonomy match",
            evidence=[f"error.reason={pf.error.reason}"],
            fallback_tier=0,
        )
    else:
        # Unseen source x step x reason combination. Fail closed (invariant 6): a
        # queued/abandoned case, never a spent attempt.
        proposal = DiagnosisProposal(
            recoverability=Recoverability.UNKNOWN,
            confidence=0.0,
            proposed_action=Action.STOP,
            proposed_delay_minutes=0,
            rationale="triage: unseen combination — failing closed",
            evidence=[f"error.reason={pf.error.reason}"],
            fallback_tier=0,
        )

    append(
        conn,
        case_id=case_id,
        actor="diagnosis",
        event_type="DIAGNOSIS_RETURNED",
        payload=proposal.model_dump(mode="json"),
        ts=now,
    )
    transition(conn, case_id, "DIAGNOSED")
    append(
        conn,
        case_id=case_id,
        actor="pipeline",
        event_type="STATE_TRANSITION",
        payload={"to": "DIAGNOSED"},
        ts=now,
    )

    row = get_case(conn, case_id)
    view = CaseView(
        case_id=case_id,
        cohort=Cohort(row["cohort"]),
        attempts=row["attempts"],
        method=pf.method,
        instrument=pf.instrument,
        amount_paise=pf.amount_paise,
        is_recurring=pf.is_recurring,
        state=CaseState(row["state"]),
    )
    verdict = evaluate(proposal, view, rules, now, dctx)
    append(
        conn,
        case_id=case_id,
        actor="policy",
        event_type="POLICY_VERDICT",
        payload=verdict.model_dump(mode="json"),
        ts=now,
    )

    if not verdict.is_executable:
        if view.cohort is Cohort.HOLDOUT and "HOLDOUT_GUARD" in verdict.fired_rules:
            transition(conn, case_id, "HOLDOUT_CLOSED")
            final = "HOLDOUT_CLOSED"
        else:
            transition(conn, case_id, "ABANDONED", abandon_reason=verdict.reason)
            final = "ABANDONED"
        append(
            conn,
            case_id=case_id,
            actor="pipeline",
            event_type="STATE_TRANSITION",
            payload={"to": final, "reason": verdict.reason},
            ts=now,
        )
        return DecisionTrace(case_id, view.cohort, tr.recoverability.value, tr.is_ambiguous, proposal, verdict, None, final)

    # Executable: ALLOW or DEFER with action RETRY.
    transition(conn, case_id, "SCHEDULED")
    append(conn, case_id=case_id, actor="pipeline", event_type="STATE_TRANSITION", payload={"to": "SCHEDULED"}, ts=now)
    append(
        conn,
        case_id=case_id,
        actor="scheduler",
        event_type="ACTION_DISPATCHED",
        payload={"action": verdict.action.value, "execute_at": verdict.execute_at.isoformat() if verdict.execute_at else None},
        ts=now,
    )
    transition(conn, case_id, "EXECUTING")
    result = executor.execute(verdict)
    append(
        conn,
        case_id=case_id,
        actor="executor",
        event_type="ACTION_RESULT",
        payload=result.model_dump(mode="json"),
        ts=clock.now(),
    )
    final = "RECOVERED" if result.succeeded else "FAILED_ATTEMPT"
    transition(
        conn,
        case_id,
        final,
        increment_attempt=True,
        last_attempt_at=clock.now(),
    )
    append(conn, case_id=case_id, actor="pipeline", event_type="STATE_TRANSITION", payload={"to": final}, ts=clock.now())

    return DecisionTrace(case_id, view.cohort, tr.recoverability.value, tr.is_ambiguous, proposal, verdict, result.succeeded, final)
