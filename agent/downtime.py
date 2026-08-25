"""Downtime lookup over the documented Razorpay Payment Downtime entity (EVIDENCE.md E6).

Razorpay ships detection and then, per its own docs (E8), leaves the merchant to
"plan the remediation steps accordingly". This module is the first half of that plan:
answering "was this instrument degraded at time T?".

The second half — what to do about it — belongs to the policy engine, never here.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from agent.models import DowntimeContext, DowntimeWindow, Instrument, Method

ACTIVE_STATUSES = frozenset({"started", "updated", "scheduled"})


def _parse(row: sqlite3.Row) -> DowntimeWindow:
    return DowntimeWindow(
        id=row["id"],
        method=Method(row["method"]),
        instrument=Instrument(**json.loads(row["instrument"])),
        begin=datetime.fromisoformat(row["begin"]),
        end=datetime.fromisoformat(row["end"]) if row["end"] else None,
        status=row["status"],
        scheduled=bool(row["scheduled"]),
        severity=row["severity"],
        flow=row["flow"],
    )


class DowntimeStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, w: DowntimeWindow) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO downtime_windows"
            " (id, method, instrument, begin, end, status, scheduled, severity, flow)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                w.id,
                w.method.value,
                json.dumps(w.instrument.model_dump(exclude_none=True), sort_keys=True),
                w.begin.isoformat(),
                w.end.isoformat() if w.end else None,
                w.status,
                int(w.scheduled),
                w.severity,
                w.flow,
            ),
        )

    def active_at(
        self, method: Method, instrument: Instrument, when: datetime
    ) -> DowntimeWindow | None:
        """Most severe window covering this instrument at `when`, or None.

        `end is None` means recovery time unknown, so the window is treated as still
        open — the conservative reading, and the one that keeps us from retrying into
        an outage we cannot see the end of.
        """
        rows = self._conn.execute(
            "SELECT * FROM downtime_windows WHERE method = ?", (method.value,)
        ).fetchall()

        severity_rank = {"high": 3, "medium": 2, "low": 1}
        best: DowntimeWindow | None = None
        for row in rows:
            w = _parse(row)
            if w.status not in ACTIVE_STATUSES:
                continue
            if not (w.begin <= when and (w.end is None or when < w.end)):
                continue
            if not instrument.matches(w.instrument):
                continue
            if best is None or severity_rank.get(w.severity, 0) > severity_rank.get(best.severity, 0):
                best = w
        return best

    def context_at(
        self, method: Method, instrument: Instrument, when: datetime
    ) -> DowntimeContext:
        w = self.active_at(method, instrument, when)
        if w is None:
            return DowntimeContext()
        return DowntimeContext(
            active=True,
            severity=w.severity,
            scheduled=w.scheduled,
            instrument_match=True,
            expected_end=w.end,
            window_id=w.id,
        )
