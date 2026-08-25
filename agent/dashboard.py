"""Dashboard data aggregation and transaction-level traceability engine.

Computes the 7 core operational metrics and provides audit-trace extraction
with cryptographic hash-chain verification.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from agent.audit import events_for, verify_chain
from agent.logger import get_logger, sanitize_data

logger = get_logger("agent.dashboard")


def compute_dashboard_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute the 7 core dashboard metrics directly from the operational database.
    
    1. Revenue at Risk (INR)
    2. Recovered Value (INR)
    3. Recovery Rate (%)
    4. Actions Executed (count)
    5. Actions Blocked (count)
    6. AI Confidence (%)
    7. Failure Rate (%)
    """
    cursor = conn.cursor()

    # Total cases & revenue
    row_cases = cursor.execute(
        """
        SELECT COUNT(*) AS total_cases,
               COALESCE(SUM(amount_paise), 0) AS total_paise
          FROM cases
        """
    ).fetchone()
    total_cases = row_cases["total_cases"] if row_cases else 0
    total_paise = row_cases["total_paise"] if row_cases else 0
    revenue_at_risk_rupees = round(total_paise / 100.0, 2)

    # Recovered cases & value
    row_recovered = cursor.execute(
        """
        SELECT COUNT(*) AS recovered_count,
               COALESCE(SUM(amount_paise), 0) AS recovered_paise
          FROM cases
         WHERE state = 'RECOVERED'
        """
    ).fetchone()
    recovered_count = row_recovered["recovered_count"] if row_recovered else 0
    recovered_paise = row_recovered["recovered_paise"] if row_recovered else 0
    recovered_value_rupees = round(recovered_paise / 100.0, 2)

    # Recovery rate percentage (value-based)
    if revenue_at_risk_rupees > 0:
        recovery_rate_pct = round((recovered_value_rupees / revenue_at_risk_rupees) * 100.0, 2)
    else:
        recovery_rate_pct = 0.0

    # Actions executed (dispatched and ran)
    row_actions = cursor.execute(
        """
        SELECT COUNT(*) AS executed_count
          FROM actions
         WHERE executed_at IS NOT NULL
        """
    ).fetchone()
    actions_executed = row_actions["executed_count"] if row_actions else 0

    # Actions blocked (vetoed by policy or closed as holdout / terminal)
    row_blocked = cursor.execute(
        """
        SELECT COUNT(*) AS blocked_count
          FROM audit_events
         WHERE event_type = 'POLICY_VERDICT'
           AND (json_extract(payload, '$.decision') IN ('DENY', 'REVIEW')
                OR json_extract(payload, '$.action') = 'STOP')
        """
    ).fetchone()
    actions_blocked = row_blocked["blocked_count"] if row_blocked else 0

    # AI Average Confidence (%)
    row_ai = cursor.execute(
        """
        SELECT AVG(json_extract(payload, '$.confidence')) AS avg_conf,
               COUNT(*) AS diag_count
          FROM audit_events
         WHERE event_type = 'DIAGNOSIS_RETURNED'
        """
    ).fetchone()
    avg_conf = row_ai["avg_conf"] if row_ai and row_ai["avg_conf"] is not None else 0.0
    ai_confidence_pct = round(avg_conf * 100.0, 1)

    # Failure rate (% of cases not recovered: abandoned, quarantined, or failed attempt)
    unrecovered_count = total_cases - recovered_count
    if total_cases > 0:
        failure_rate_pct = round((unrecovered_count / total_cases) * 100.0, 2)
    else:
        failure_rate_pct = 0.0

    # Cohort breakdown for context
    cohort_rows = cursor.execute(
        """
        SELECT cohort,
               COUNT(*) AS count,
               COALESCE(SUM(amount_paise), 0) AS paise,
               SUM(CASE WHEN state = 'RECOVERED' THEN 1 ELSE 0 END) AS recovered
          FROM cases
         GROUP BY cohort
        """
    ).fetchall()
    cohort_summary = {
        r["cohort"]: {
            "cases": r["count"],
            "amount_rupees": round(r["paise"] / 100.0, 2),
            "recovered": r["recovered"],
        }
        for r in cohort_rows
    }

    # Method breakdown
    method_rows = cursor.execute(
        """
        SELECT method,
               COUNT(*) AS total,
               SUM(CASE WHEN state = 'RECOVERED' THEN 1 ELSE 0 END) AS recovered,
               COALESCE(SUM(amount_paise), 0) AS paise,
               COALESCE(SUM(CASE WHEN state = 'RECOVERED' THEN amount_paise ELSE 0 END), 0) AS rec_paise
          FROM cases
         GROUP BY method
        """
    ).fetchall()
    methods_summary = {
        r["method"]: {
            "total": r["total"],
            "recovered": r["recovered"],
            "amount_rupees": round(r["paise"] / 100.0, 2),
            "recovered_rupees": round(r["rec_paise"] / 100.0, 2),
            "recovery_rate_pct": round((r["recovered"] / r["total"] * 100.0), 1) if r["total"] > 0 else 0.0,
        }
        for r in method_rows
    }

    # Error reason breakdown
    error_rows = cursor.execute(
        """
        SELECT json_extract(error, '$.reason') AS reason,
               COUNT(*) AS total,
               SUM(CASE WHEN state = 'RECOVERED' THEN 1 ELSE 0 END) AS recovered
          FROM cases
         GROUP BY json_extract(error, '$.reason')
         ORDER BY total DESC
         LIMIT 6
        """
    ).fetchall()
    error_summary = [
        {
            "reason": r["reason"] or "unknown",
            "total": r["total"],
            "recovered": r["recovered"],
        }
        for r in error_rows
    ]

    # State distribution
    state_rows = cursor.execute(
        """
        SELECT state, COUNT(*) AS count
          FROM cases
         GROUP BY state
        """
    ).fetchall()
    state_distribution = {r["state"]: r["count"] for r in state_rows}

    metrics = {
        "revenue_at_risk_rupees": revenue_at_risk_rupees,
        "recovered_value_rupees": recovered_value_rupees,
        "recovery_rate_pct": recovery_rate_pct,
        "actions_executed": actions_executed,
        "actions_blocked": actions_blocked,
        "ai_confidence_pct": ai_confidence_pct,
        "failure_rate_pct": failure_rate_pct,
        "total_cases": total_cases,
        "recovered_cases": recovered_count,
        "cohorts": cohort_summary,
        "methods": methods_summary,
        "errors": error_summary,
        "states": state_distribution,
    }

    logger.log_event("dashboard.metrics.computed", data=metrics)
    return metrics


def get_transactions_summary(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
    cohort_filter: str | None = None,
    method_filter: str | None = None,
    state_filter: str | None = None,
) -> dict[str, Any]:
    """Fetch paginated transaction-level summaries with error, diagnosis, and decision details."""
    query = """
        SELECT c.case_id,
               c.customer_id,
               c.order_id,
               c.created_at,
               c.method,
               c.amount_paise,
               c.is_recurring,
               c.attempts,
               c.cohort,
               c.state,
               c.error,
               c.instrument
          FROM cases c
         WHERE 1=1
    """
    params: list[Any] = []

    if search:
        search_pattern = f"%{search.strip()}%"
        query += " AND (c.case_id LIKE ? OR c.order_id LIKE ? OR c.customer_id LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern])

    if cohort_filter and cohort_filter.upper() != "ALL":
        query += " AND c.cohort = ?"
        params.append(cohort_filter.upper())

    if method_filter and method_filter.upper() != "ALL":
        query += " AND c.method = ?"
        params.append(method_filter.lower())

    if state_filter and state_filter.upper() != "ALL":
        query += " AND c.state = ?"
        params.append(state_filter.upper())

    # Count total matching rows
    count_query = f"SELECT COUNT(*) AS total FROM ({query})"
    total_matching = conn.execute(count_query, params).fetchone()["total"]

    # Order and paginate
    query += " ORDER BY c.created_at DESC, c.case_id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    transactions = []

    for r in rows:
        case_id = r["case_id"]
        error_data = json.loads(r["error"]) if r["error"] else {}
        instrument_data = json.loads(r["instrument"]) if r["instrument"] else {}

        # Extract latest AI diagnosis and Policy verdict from audit events
        diag_row = conn.execute(
            """
            SELECT payload
              FROM audit_events
             WHERE case_id = ? AND event_type = 'DIAGNOSIS_RETURNED'
             ORDER BY seq DESC LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        diag_payload = json.loads(diag_row["payload"]) if diag_row else None

        policy_row = conn.execute(
            """
            SELECT payload
              FROM audit_events
             WHERE case_id = ? AND event_type = 'POLICY_VERDICT'
             ORDER BY seq DESC LIMIT 1
            """,
            (case_id,),
        ).fetchone()
        policy_payload = json.loads(policy_row["payload"]) if policy_row else None

        exec_row = conn.execute(
            """
            SELECT action, executed_at, succeeded
              FROM actions
             WHERE case_id = ?
             ORDER BY scheduled_at DESC LIMIT 1
            """,
            (case_id,),
        ).fetchone()

        transactions.append(
            sanitize_data(
                {
                    "case_id": case_id,
                    "order_id": r["order_id"],
                    "customer_id": r["customer_id"],
                    "created_at": r["created_at"],
                    "method": r["method"],
                    "amount_paise": r["amount_paise"],
                    "amount_rupees": round(r["amount_paise"] / 100.0, 2),
                    "is_recurring": bool(r["is_recurring"]),
                    "attempts": r["attempts"],
                    "cohort": r["cohort"],
                    "state": r["state"],
                    "error_reason": error_data.get("reason", "unknown"),
                    "error_code": error_data.get("code", ""),
                    "instrument_type": instrument_data.get("type") or instrument_data.get("network") or instrument_data.get("bank") or "standard",
                    "ai_recoverability": diag_payload.get("recoverability") if diag_payload else "N/A",
                    "ai_confidence": round(diag_payload.get("confidence", 0.0) * 100, 1) if diag_payload else None,
                    "ai_proposed_action": diag_payload.get("proposed_action") if diag_payload else None,
                    "policy_decision": policy_payload.get("decision") if policy_payload else "N/A",
                    "policy_action": policy_payload.get("action") if policy_payload else None,
                    "policy_reason": policy_payload.get("reason") if policy_payload else None,
                    "fired_rules": policy_payload.get("fired_rules", []) if policy_payload else [],
                    "action_executed": bool(exec_row["executed_at"]) if exec_row else False,
                    "action_succeeded": bool(exec_row["succeeded"]) if exec_row and exec_row["executed_at"] else None,
                }
            )
        )

    return {
        "total": total_matching,
        "limit": limit,
        "offset": offset,
        "transactions": transactions,
    }


def get_transaction_trace(conn: sqlite3.Connection, case_id: str) -> dict[str, Any]:
    """Retrieve full end-to-end audit trail and cryptographic hash-chain verification for a transaction."""
    case_row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if not case_row:
        raise KeyError(f"Case {case_id} not found")

    events = events_for(conn, case_id)
    chain_valid = verify_chain(conn)

    parsed_events = []
    for e in events:
        payload = json.loads(e["payload"]) if e["payload"] else {}
        parsed_events.append(
            {
                "seq": e["seq"],
                "actor": e["actor"],
                "event_type": e["event_type"],
                "timestamp": e["ts"],
                "hash": e["hash"],
                "prev_hash": e["prev_hash"],
                "payload": sanitize_data(payload),
            }
        )

    error_data = json.loads(case_row["error"]) if case_row["error"] else {}
    instrument_data = json.loads(case_row["instrument"]) if case_row["instrument"] else {}

    return {
        "case_id": case_id,
        "order_id": case_row["order_id"],
        "customer_id": case_row["customer_id"],
        "created_at": case_row["created_at"],
        "method": case_row["method"],
        "amount_rupees": round(case_row["amount_paise"] / 100.0, 2),
        "cohort": case_row["cohort"],
        "state": case_row["state"],
        "attempts": case_row["attempts"],
        "error": sanitize_data(error_data),
        "instrument": sanitize_data(instrument_data),
        "chain_valid": chain_valid,
        "event_count": len(parsed_events),
        "timeline": parsed_events,
    }


def get_transaction_detail(conn: sqlite3.Connection, case_id: str) -> dict[str, Any]:
    """Extract the complete 9-phase transaction journey from real backend database state.

    1. Event (ingested error signal and metadata)
    2. Context (downtime state, attempt number, recurring mandate, cohort)
    3. AI Diagnosis (recoverability, confidence, fallback tier, rationale)
    4. Evidence (grounded cited field paths, risk categories, missing information)
    5. Proposed Action (proposed action, delay minutes, expected outcome)
    6. Policy Result (zero-LLM gate decision, fired rules, reason, version, execute_at)
    7. Execution (idempotency key, execution mode, dispatch timestamps, replay flag)
    8. Outcome (succeeded, outcome status, target/final state, error detail)
    9. Audit Trail (cryptographic SHA-256 event chain with hash verification)
    """
    case_row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if not case_row:
        raise KeyError(f"Case {case_id} not found")

    events = events_for(conn, case_id)
    chain_valid = verify_chain(conn)

    # Index audit events by event_type for fast extraction
    events_by_type: dict[str, Any] = {}
    parsed_events = []
    for e in events:
        payload = json.loads(e["payload"]) if e["payload"] else {}
        sanitized_payload = sanitize_data(payload)
        evt_obj = {
            "seq": e["seq"],
            "actor": e["actor"],
            "event_type": e["event_type"],
            "timestamp": e["ts"],
            "hash": e["hash"],
            "prev_hash": e["prev_hash"],
            "payload": sanitized_payload,
        }
        parsed_events.append(evt_obj)
        events_by_type[e["event_type"]] = sanitized_payload

    # Extract associated action record if exists
    action_row = conn.execute(
        "SELECT * FROM actions WHERE case_id = ? ORDER BY scheduled_at DESC LIMIT 1",
        (case_id,),
    ).fetchone()

    # 1. Event
    error_data = sanitize_data(json.loads(case_row["error"])) if case_row["error"] else {}
    instrument_data = sanitize_data(json.loads(case_row["instrument"])) if case_row["instrument"] else {}
    amount_paise = case_row["amount_paise"]
    amount_rupees = round(amount_paise / 100.0, 2)

    phase_event = {
        "case_id": case_id,
        "order_id": case_row["order_id"],
        "customer_id": case_row["customer_id"],
        "created_at": case_row["created_at"],
        "method": case_row["method"],
        "instrument": instrument_data,
        "amount_paise": amount_paise,
        "amount_rupees": amount_rupees,
        "is_recurring": bool(case_row["is_recurring"]),
        "mandate_id": case_row["mandate_id"],
        "error_code": error_data.get("code", "UNKNOWN"),
        "error_source": error_data.get("source", "unknown"),
        "error_step": error_data.get("step", "unknown"),
        "error_reason": error_data.get("reason", "unknown"),
        "error_description": error_data.get("description", ""),
    }

    # 2. Context
    triage_payload = events_by_type.get("TRIAGE_RESULT", {})
    cohort_payload = events_by_type.get("COHORT_ASSIGNED", {})
    phase_context = {
        "cohort": case_row["cohort"],
        "seed": cohort_payload.get("seed"),
        "attempt_no": case_row["attempts"] + 1,
        "prior_failures_count": case_row["attempts"],
        "is_recurring": bool(case_row["is_recurring"]),
        "triage_matched": triage_payload.get("matched", "unknown"),
        "triage_is_ambiguous": triage_payload.get("is_ambiguous", False),
        "triage_recoverability": triage_payload.get("recoverability", "UNKNOWN"),
    }

    # 3. AI Diagnosis
    diag_payload = events_by_type.get("DIAGNOSIS_RETURNED", {})
    conf = diag_payload.get("confidence")
    phase_diagnosis = {
        "recoverability": diag_payload.get("recoverability", triage_payload.get("recoverability", "UNKNOWN")),
        "confidence": conf,
        "confidence_pct": round(conf * 100, 1) if conf is not None else None,
        "fallback_tier": diag_payload.get("fallback_tier", 0),
        "rationale": diag_payload.get("rationale", "No rationale recorded"),
        "is_ambiguous": triage_payload.get("is_ambiguous", False),
    }

    # 4. Evidence
    phase_evidence = {
        "cited_fields": diag_payload.get("evidence", []),
        "risks": diag_payload.get("risks", []),
        "missing_information": diag_payload.get("missing_information", []),
        "is_grounded": bool(diag_payload.get("evidence")),
    }

    # 5. Proposed Action
    exp_outcome = diag_payload.get("expected_outcome", {})
    phase_proposal = {
        "proposed_action": diag_payload.get("proposed_action", "STOP"),
        "proposed_delay_minutes": diag_payload.get("proposed_delay_minutes", 0),
        "expected_success_probability": exp_outcome.get("probability_of_success"),
        "expected_success_probability_pct": round(exp_outcome.get("probability_of_success", 0.0) * 100, 1) if exp_outcome.get("probability_of_success") is not None else None,
        "expected_horizon_minutes": exp_outcome.get("horizon_minutes", 0),
    }

    # 6. Policy Result
    policy_payload = events_by_type.get("POLICY_VERDICT", {})
    decision_val = policy_payload.get("decision", "DENY")
    phase_policy = {
        "policy_decision": decision_val,
        "decision": decision_val,
        "authorized_action": policy_payload.get("action", "STOP"),
        "action": policy_payload.get("action", "STOP"),
        "fired_rules": policy_payload.get("fired_rules", []),
        "reason": policy_payload.get("reason", "No reason provided"),
        "policy_version": policy_payload.get("rules_version", 2),
        "rules_version": policy_payload.get("rules_version", 2),
        "execute_at": policy_payload.get("execute_at"),
        "is_executable": decision_val in ("ALLOW", "DEFER") and policy_payload.get("action") != "STOP",
    }

    # 7. Execution
    refusal_payload = events_by_type.get("ACTION_REFUSED", {})
    uncertain_payload = events_by_type.get("ACTION_UNCERTAIN", {})
    result_payload = events_by_type.get("ACTION_RESULT", {})
    dispatched_payload = events_by_type.get("ACTION_DISPATCHED", {})

    idempotency_key = (
        action_row["idempotency_key"] if action_row else
        uncertain_payload.get("idempotency_key") or
        result_payload.get("idempotency_key")
    )

    phase_execution = {
        "is_dispatched": bool(dispatched_payload or action_row or refusal_payload or uncertain_payload),
        "idempotency_key": idempotency_key,
        "execution_mode": action_row["mode"] if action_row else "sim",
        "scheduled_at": action_row["scheduled_at"] if action_row else dispatched_payload.get("execute_at"),
        "executed_at": action_row["executed_at"] if action_row else (result_payload.get("executed_at") or None),
        "replayed": bool(result_payload.get("replayed", False)),
    }

    # 8. Outcome
    final_state = case_row["state"]
    if final_state == "RECOVERED":
        outcome_status = "SUCCEEDED"
        succeeded = True
    elif final_state == "FAILED_ATTEMPT":
        outcome_status = "FAILED"
        succeeded = False
    elif final_state == "QUARANTINED":
        outcome_status = "UNCERTAIN" if uncertain_payload else "QUARANTINED_FOR_REVIEW"
        succeeded = None
    elif final_state in ("ABANDONED", "HOLDOUT_CLOSED"):
        outcome_status = "BLOCKED_BY_POLICY"
        succeeded = None
    else:
        outcome_status = final_state
        succeeded = None

    phase_outcome = {
        "final_state": final_state,
        "outcome_status": outcome_status,
        "succeeded": succeeded,
        "abandon_reason": case_row["abandon_reason"],
        "error_code": refusal_payload.get("code") or uncertain_payload.get("code") or None,
        "error_detail": refusal_payload.get("detail") or uncertain_payload.get("detail") or None,
        "retryable": refusal_payload.get("retryable"),
    }

    # 9. Audit Trail
    decision_record = events_by_type.get("DECISION_RECORDED", {})
    phase_audit = {
        "chain_valid": chain_valid,
        "chain_verified": chain_valid,
        "total_events": len(parsed_events),
        "decision_record": decision_record,
        "timeline": parsed_events,
    }

    phases_dict = {
        "event": phase_event,
        "context": phase_context,
        "diagnosis": phase_diagnosis,
        "ai_diagnosis": phase_diagnosis,
        "evidence": phase_evidence,
        "proposal": phase_proposal,
        "proposed_action": phase_proposal,
        "policy_result": phase_policy,
        "policy_verdict": phase_policy,
        "execution": phase_execution,
        "outcome": phase_outcome,
        "audit_trail": phase_audit,
    }

    detail = {
        "case_id": case_id,
        "phases": phases_dict,
        "event": phase_event,
        "context": phase_context,
        "ai_diagnosis": phase_diagnosis,
        "evidence": phase_evidence,
        "proposed_action": phase_proposal,
        "policy_result": phase_policy,
        "execution": phase_execution,
        "outcome": phase_outcome,
        "audit_trail": phase_audit,
    }

    logger.log_event("dashboard.transaction_detail.retrieved", case_id=case_id)
    return detail

