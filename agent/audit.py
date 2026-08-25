"""Append-only, hash-chained decision log.

Every layer writes here. The chain means a tampered history is detectable rather than
merely discouraged: altering one byte of one payload breaks every subsequent hash.

`replay()` rebuilds case state from events alone and is asserted equal to the state
store during evaluation — if the two ever disagree, the audit log is the truth.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any

GENESIS = "0" * 64

# Event vocabulary. Keep closed — an unrecognised event type means a layer is writing
# something the replayer does not understand.
EVENTS = frozenset(
    {
        "SIGNAL_RECEIVED",
        "COHORT_ASSIGNED",
        "TRIAGE_RESULT",
        "DIAGNOSIS_RETURNED",
        "POLICY_VERDICT",
        "ACTION_DISPATCHED",
        "ACTION_RESULT",
        # An executor refused to perform a dispatched action. Distinct from
        # ACTION_RESULT: a refusal means nothing ran and no attempt was consumed,
        # so conflating the two would corrupt the attempt-count replay.
        "ACTION_REFUSED",
        # The action was dispatched but the outcome is unknown — timeout or
        # indeterminate provider response. Distinct from both ACTION_RESULT and
        # ACTION_REFUSED: we don't know whether an attempt was consumed. The
        # case must not be blindly retried; reconciliation is the only safe path.
        "ACTION_UNCERTAIN",
        # Reconciliation has verified the actual outcome of a previously uncertain
        # action and transitioned the case accordingly.
        "RECONCILIATION_RESOLVED",
        "STATE_TRANSITION",
    }
)


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(prev_hash: str, body: str) -> str:
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def append(
    conn: sqlite3.Connection,
    *,
    case_id: str | None,
    actor: str,
    event_type: str,
    payload: dict[str, Any],
    ts: datetime,
) -> str:
    if event_type not in EVENTS:
        raise ValueError(f"unknown audit event type: {event_type}")

    row = conn.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    prev_hash = row["hash"] if row else GENESIS

    body = canonical(
        {
            "case_id": case_id,
            "ts": ts.isoformat(),
            "actor": actor,
            "event_type": event_type,
            "payload": payload,
        }
    )
    h = _digest(prev_hash, body)

    conn.execute(
        "INSERT INTO audit_events (case_id, ts, actor, event_type, payload, prev_hash, hash)"
        " VALUES (?,?,?,?,?,?,?)",
        (case_id, ts.isoformat(), actor, event_type, canonical(payload), prev_hash, h),
    )
    return h


def verify_chain(conn: sqlite3.Connection) -> bool:
    """True only if every link recomputes. Any mutation anywhere fails this."""
    prev_hash = GENESIS
    for row in conn.execute("SELECT * FROM audit_events ORDER BY seq ASC"):
        body = canonical(
            {
                "case_id": row["case_id"],
                "ts": row["ts"],
                "actor": row["actor"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload"]),
            }
        )
        if row["prev_hash"] != prev_hash or _digest(prev_hash, body) != row["hash"]:
            return False
        prev_hash = row["hash"]
    return True


def events_for(conn: sqlite3.Connection, case_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM audit_events WHERE case_id = ? ORDER BY seq ASC", (case_id,)
        )
    )


def replay(conn: sqlite3.Connection, case_id: str) -> dict[str, Any]:
    """Rebuild case state from the event stream alone — no reads of `cases`."""
    state: dict[str, Any] = {
        "case_id": case_id,
        "cohort": None,
        "state": None,
        "attempts": 0,
        "recovered": False,
        "abandon_reason": None,
    }
    for row in events_for(conn, case_id):
        payload = json.loads(row["payload"])
        et = row["event_type"]
        if et == "COHORT_ASSIGNED":
            state["cohort"] = payload["cohort"]
        elif et == "STATE_TRANSITION":
            state["state"] = payload["to"]
            if payload.get("reason") and payload["to"] == "ABANDONED":
                state["abandon_reason"] = payload["reason"]
        elif et == "ACTION_RESULT":
            state["attempts"] += 1
            if payload.get("succeeded"):
                state["recovered"] = True
    return state
