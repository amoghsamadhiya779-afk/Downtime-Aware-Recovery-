"""Reconciliation: the ONLY safe path out of execution uncertainty.

When an executor times out or reports an indeterminate status, the pipeline
quarantines the case rather than blindly retrying.  This module resolves
those cases once the actual outcome has been verified.

In Phase 1 (simulation), the caller supplies the verified outcome directly.
In Phase 2 (live), a reconciliation job would query the payment provider's API
and feed the result here.

Design invariant: reconciliation is explicit.  No code path may transition an
uncertain case without first calling `reconcile()` — this is what "do not blindly
retry" means in practice.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from agent.audit import append
from agent.models import ActionOutcome, CaseState
from agent.state import get_case, transition


def find_uncertain_cases(conn: sqlite3.Connection) -> list[dict]:
    """Find quarantined cases whose last executor event is ACTION_UNCERTAIN.

    Returns a list of dicts with `case_id`, `idempotency_key`, and the
    uncertainty `code` — enough for a reconciliation job to query the provider
    and verify the outcome.
    """
    rows = conn.execute(
        """
        SELECT ae.case_id,
               json_extract(ae.payload, '$.idempotency_key') AS idempotency_key,
               json_extract(ae.payload, '$.code')            AS code
          FROM audit_events ae
          JOIN cases c ON ae.case_id = c.case_id
         WHERE ae.event_type = 'ACTION_UNCERTAIN'
           AND c.state = 'QUARANTINED'
           -- Not already reconciled: no RECONCILIATION_RESOLVED event follows.
           AND NOT EXISTS (
               SELECT 1
                 FROM audit_events later
                WHERE later.case_id = ae.case_id
                  AND later.event_type = 'RECONCILIATION_RESOLVED'
                  AND later.seq > ae.seq
           )
         ORDER BY ae.seq ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


class ReconciliationError(RuntimeError):
    """Raised when a reconciliation precondition is violated."""

    pass


def reconcile(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    actual_outcome: ActionOutcome | None,
    ts: datetime,
) -> str:
    """Resolve a quarantined-uncertain case based on verified outcome.

    Parameters
    ----------
    actual_outcome:
        ``ActionOutcome.SUCCEEDED`` — the action did complete and succeeded
            → transition to RECOVERED, increment attempt count.
        ``ActionOutcome.FAILED`` — the action did complete but failed
            → transition to FAILED_ATTEMPT, increment attempt count.
        ``None`` — the action never actually ran (e.g. provider confirms no
            transaction)
            → transition to DIAGNOSED, can be reprocessed from scratch.

    Returns
    -------
    The new state value (e.g. "RECOVERED", "FAILED_ATTEMPT", "DIAGNOSED").

    Raises
    ------
    ReconciliationError
        If the case is not in QUARANTINED state, or was not uncertain.
    """
    # --- guard: case must be QUARANTINED ---
    row = get_case(conn, case_id)
    if CaseState(row["state"]) is not CaseState.QUARANTINED:
        raise ReconciliationError(
            f"case {case_id} is in state {row['state']}, not QUARANTINED"
        )

    # --- guard: case must have an unresolved ACTION_UNCERTAIN event ---
    uncertain_event = conn.execute(
        """
        SELECT ae.seq,
               json_extract(ae.payload, '$.idempotency_key') AS idempotency_key
          FROM audit_events ae
         WHERE ae.case_id = ?
           AND ae.event_type = 'ACTION_UNCERTAIN'
           AND NOT EXISTS (
               SELECT 1
                 FROM audit_events later
                WHERE later.case_id = ae.case_id
                  AND later.event_type = 'RECONCILIATION_RESOLVED'
                  AND later.seq > ae.seq
           )
         ORDER BY ae.seq DESC
         LIMIT 1
        """,
        (case_id,),
    ).fetchone()
    if uncertain_event is None:
        raise ReconciliationError(
            f"case {case_id} has no unresolved ACTION_UNCERTAIN event"
        )

    # --- determine target state ---
    if actual_outcome is ActionOutcome.SUCCEEDED:
        target = "RECOVERED"
        increment = True
    elif actual_outcome is ActionOutcome.FAILED:
        target = "FAILED_ATTEMPT"
        increment = True
    elif actual_outcome is None:
        # Action never ran — back to DIAGNOSED for reprocessing.
        target = "DIAGNOSED"
        increment = False
    else:
        raise ReconciliationError(f"unexpected actual_outcome: {actual_outcome}")

    # --- transition ---
    transition(conn, case_id, target, increment_attempt=increment, last_attempt_at=ts if increment else None)

    # --- audit ---
    append(
        conn,
        case_id=case_id,
        actor="reconciliation",
        event_type="RECONCILIATION_RESOLVED",
        payload={
            "actual_outcome": actual_outcome.value if actual_outcome else None,
            "target_state": target,
            "idempotency_key": uncertain_event["idempotency_key"],
            "attempt_counted": increment,
        },
        ts=ts,
    )
    append(
        conn,
        case_id=case_id,
        actor="reconciliation",
        event_type="STATE_TRANSITION",
        payload={"to": target, "reason": f"reconciled: {actual_outcome.value if actual_outcome else 'never_ran'}"},
        ts=ts,
    )

    return target
