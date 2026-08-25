"""Case persistence and the state machine.

CaseState transitions:

    DETECTED -> DIAGNOSED -> SCHEDULED -> EXECUTING -+-> RECOVERED        (terminal)
                                              ^        +-> ABANDONED       (terminal)
                                              |        +-> FAILED_ATTEMPT -+
                                              +----------------------------+
    HOLDOUT_CLOSED (terminal, entered directly from DETECTED via HOLDOUT_GUARD)

Counters (`attempts`, `last_attempt_at`) are denormalised onto the row for the policy
engine's convenience; `agent/audit.py:replay()` reconstructs the same numbers from the
event stream alone, and the eval harness asserts the two agree (ARCHITECTURE §6).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from agent.models import Cohort, ErrorObj, Instrument, Method, PaymentFailure

VALID_TRANSITIONS: dict[str, set[str]] = {
    "DETECTED": {"DIAGNOSED", "ABANDONED", "QUARANTINED"},
    # Diagnosis runs even on holdout cases (they traverse triage/diagnosis and are
    # denied only at the policy step — HOLDOUT_GUARD), so HOLDOUT_CLOSED is reached
    # from DIAGNOSED, not directly from DETECTED.
    "DIAGNOSED": {"SCHEDULED", "ABANDONED", "HOLDOUT_CLOSED", "QUARANTINED"},
    "SCHEDULED": {"EXECUTING", "ABANDONED"},
    "EXECUTING": {"RECOVERED", "FAILED_ATTEMPT", "ABANDONED"},
    "FAILED_ATTEMPT": {"DIAGNOSED", "SCHEDULED", "ABANDONED"},
    "RECOVERED": set(),
    "ABANDONED": set(),
    "HOLDOUT_CLOSED": set(),
    "QUARANTINED": set(),
}


class IllegalTransition(RuntimeError):
    pass


def create_case(conn: sqlite3.Connection, pf: PaymentFailure, cohort: Cohort) -> None:
    conn.execute(
        "INSERT INTO cases (case_id, customer_id, order_id, created_at, method, instrument,"
        " amount_paise, is_recurring, mandate_id, error, cohort, state, attempts, version)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0)",
        (
            pf.case_id,
            pf.customer_id,
            pf.order_id,
            pf.created_at.isoformat(),
            pf.method.value,
            json.dumps(pf.instrument.model_dump(exclude_none=True), sort_keys=True),
            pf.amount_paise,
            int(pf.is_recurring),
            pf.mandate_id,
            json.dumps(pf.error.model_dump(), sort_keys=True),
            cohort.value,
            "DETECTED",
        ),
    )


def get_case(conn: sqlite3.Connection, case_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        raise KeyError(case_id)
    return row


def to_payment_failure(row: sqlite3.Row) -> PaymentFailure:
    return PaymentFailure(
        case_id=row["case_id"],
        customer_id=row["customer_id"],
        order_id=row["order_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        method=Method(row["method"]),
        instrument=Instrument(**json.loads(row["instrument"])),
        amount_paise=row["amount_paise"],
        is_recurring=bool(row["is_recurring"]),
        mandate_id=row["mandate_id"],
        attempt_no=row["attempts"] + 1,
        error=ErrorObj(**json.loads(row["error"])),
    )


def transition(
    conn: sqlite3.Connection,
    case_id: str,
    to_state: str,
    *,
    increment_attempt: bool = False,
    abandon_reason: str | None = None,
    last_attempt_at: datetime | None = None,
) -> None:
    row = get_case(conn, case_id)
    allowed = VALID_TRANSITIONS.get(row["state"], set())
    if to_state not in allowed:
        raise IllegalTransition(f"{row['state']} -> {to_state} is not permitted")

    sets = ["state = ?", "version = version + 1"]
    params: list[object] = [to_state]
    if increment_attempt:
        sets.append("attempts = attempts + 1")
    if abandon_reason is not None:
        sets.append("abandon_reason = ?")
        params.append(abandon_reason)
    if last_attempt_at is not None:
        sets.append("last_attempt_at = ?")
        params.append(last_attempt_at.isoformat())
    params.append(case_id)

    cur = conn.execute(
        f"UPDATE cases SET {', '.join(sets)} WHERE case_id = ? AND version = ?",
        (*params, row["version"]),
    )
    if cur.rowcount == 0:
        raise IllegalTransition(f"concurrent modification of case {case_id}")


def verify_counters(conn: sqlite3.Connection, case_id: str) -> bool:
    """Cross-check the denormalised counter against the audit-log replay. Used by
    the eval harness (ARCHITECTURE §6) — the two must always agree."""
    from agent.audit import replay

    row = get_case(conn, case_id)
    return row["attempts"] == replay(conn, case_id)["attempts"]
