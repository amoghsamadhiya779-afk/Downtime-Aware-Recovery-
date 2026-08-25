"""Case persistence and the transaction/recovery state machine.

    DETECTED ─┬─> DIAGNOSED ─┬─> SCHEDULED ─┬─> EXECUTING ─┬─> RECOVERED    (terminal)
              │              │      ▲        │             ├─> FAILED_ATTEMPT
              │              │      └────────┼─────────────┘      │
              │              │  (retryable refusal)               │
              │              ├─> HOLDOUT_CLOSED (terminal)        │
              │              ├─> QUARANTINED    (terminal)  <─────┤ (terminal refusal)
              │              └─> ABANDONED      (terminal)  <─────┘ (gave up)
              ├─> ABANDONED   (terminal)
              └─> QUARANTINED (terminal)

`VALID_TRANSITIONS` is the ONE source of truth: terminality is derived from it
(a state with no outgoing edges is terminal) rather than being listed separately.
Three copies of "which states are terminal" previously existed — an unused
constant in agent/models.py, the empty sets here, and a hand-written set in
tests/test_adversarial.py — which is three chances to drift. See DECISIONS.md ADR-020.

Counters (`attempts`, `last_attempt_at`) are denormalised onto the row for the policy
engine's convenience; `agent/audit.py:replay()` reconstructs the same numbers from the
event stream alone, and the eval harness asserts the two agree (ARCHITECTURE §6).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from agent.models import CaseState, Cohort, ErrorObj, Instrument, Method, PaymentFailure

S = CaseState

VALID_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    # Signal ingested, nothing decided yet.
    S.DETECTED: frozenset({S.DIAGNOSED, S.ABANDONED, S.QUARANTINED}),
    # Classified. Diagnosis runs even on holdout cases (they traverse triage and
    # diagnosis and are denied only at the policy step — HOLDOUT_GUARD), so
    # HOLDOUT_CLOSED is reached from here, not directly from DETECTED (ADR-006).
    S.DIAGNOSED: frozenset({S.SCHEDULED, S.ABANDONED, S.HOLDOUT_CLOSED, S.QUARANTINED}),
    # Authorized and queued, not yet handed to an executor.
    S.SCHEDULED: frozenset({S.EXECUTING, S.ABANDONED}),
    # Dispatched. The two refusal edges below are what keep a refused command
    # from stranding a case here: an executor that raises ActionRefused leaves
    # EXECUTING with no other way out, and EXECUTING is not terminal (ADR-020).
    S.EXECUTING: frozenset(
        {
            S.RECOVERED,  # attempt succeeded
            S.FAILED_ATTEMPT,  # attempt ran and failed
            S.ABANDONED,  # cancelled
            S.SCHEDULED,  # retryable refusal — back to the queue for re-dispatch
            S.QUARANTINED,  # terminal refusal — needs a human
        }
    ),
    # Attempt ran and did not recover. Either re-diagnose for the next attempt or
    # retry the same diagnosis; the attempt cap is what bounds this loop, not the
    # state machine.
    S.FAILED_ATTEMPT: frozenset({S.DIAGNOSED, S.SCHEDULED, S.ABANDONED}),
    # --- terminal: no outgoing edges -------------------------------------------
    S.RECOVERED: frozenset(),
    S.ABANDONED: frozenset(),
    S.HOLDOUT_CLOSED: frozenset(),
    # Semantically "awaiting review / reconciliation". Previously terminal because
    # no resolution path was implemented. Reconciliation now provides one: after
    # verifying the actual outcome of an uncertain execution, a quarantined case
    # transitions to the correct state. Terminality is derived, so adding these
    # edges automatically stops QUARANTINED from being terminal (ADR-020).
    S.QUARANTINED: frozenset({S.RECOVERED, S.FAILED_ATTEMPT, S.DIAGNOSED, S.ABANDONED}),
}

TERMINAL_STATES: frozenset[CaseState] = frozenset(
    state for state, allowed in VALID_TRANSITIONS.items() if not allowed
)


class IllegalTransition(RuntimeError):
    pass


def is_terminal(state: CaseState | str) -> bool:
    return CaseState(state) in TERMINAL_STATES


def allowed_transitions(state: CaseState | str) -> frozenset[CaseState]:
    return VALID_TRANSITIONS[CaseState(state)]


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
            S.DETECTED.value,
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
    to_state: CaseState | str,
    *,
    increment_attempt: bool = False,
    abandon_reason: str | None = None,
    last_attempt_at: datetime | None = None,
) -> None:
    """Move a case to `to_state`, or raise IllegalTransition.

    `to_state` is coerced to CaseState first, so a typo raises a ValueError naming
    the bad value rather than an IllegalTransition, which would have been a
    misleading diagnosis — the transition isn't illegal, the state doesn't exist.
    """
    target = CaseState(to_state)
    row = get_case(conn, case_id)
    current = CaseState(row["state"])

    allowed = VALID_TRANSITIONS[current]
    if target not in allowed:
        detail = "state is terminal" if not allowed else f"allowed: {sorted(s.value for s in allowed)}"
        raise IllegalTransition(f"{current.value} -> {target.value} is not permitted ({detail})")

    sets = ["state = ?", "version = version + 1"]
    params: list[object] = [target.value]
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
