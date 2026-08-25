"""Schema and connection. Plain stdlib sqlite3 — no ORM serves a requirement here,
and raw SQL keeps the immutability triggers visible rather than buried in a mapper.

Two invariants are enforced by the database rather than by application code, because
application code is exactly what a long build session tends to erode:
  * `cases.cohort` cannot be updated once written (invariant 4)
  * `audit_events` rows cannot be updated or deleted (append-only)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cases (
    case_id        TEXT PRIMARY KEY,
    customer_id    TEXT NOT NULL,
    order_id       TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    method         TEXT NOT NULL,
    instrument     TEXT NOT NULL,      -- json
    amount_paise   INTEGER NOT NULL,
    is_recurring   INTEGER NOT NULL DEFAULT 0,
    mandate_id     TEXT,
    error          TEXT NOT NULL,      -- json
    cohort         TEXT NOT NULL,
    state          TEXT NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    abandon_reason TEXT,
    version        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS actions (
    idempotency_key TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(case_id),
    action          TEXT NOT NULL,
    scheduled_at    TEXT NOT NULL,
    executed_at     TEXT,
    succeeded       INTEGER,
    mode            TEXT NOT NULL DEFAULT 'SIM',
    detail          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS actions_due ON actions(executed_at, scheduled_at);

CREATE TABLE IF NOT EXISTS audit_events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT,
    ts          TEXT NOT NULL,
    actor       TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL,        -- canonical json
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_by_case ON audit_events(case_id, seq);

CREATE TABLE IF NOT EXISTS downtime_windows (
    id          TEXT PRIMARY KEY,
    method      TEXT NOT NULL,
    instrument  TEXT NOT NULL,        -- json
    begin       TEXT NOT NULL,
    end         TEXT,                 -- null = recovery time unknown
    status      TEXT NOT NULL,
    scheduled   INTEGER NOT NULL DEFAULT 0,
    severity    TEXT NOT NULL DEFAULT 'medium',
    flow        TEXT                  -- UPI-specific: collect | intent | in_app, else null
);

-- Invariant 4. Cohort assignment is the foundation of the primary KPI; if it can be
-- rewritten mid-run the incrementality claim is worthless, so the database refuses.
CREATE TRIGGER IF NOT EXISTS cohort_is_immutable
BEFORE UPDATE OF cohort ON cases
FOR EACH ROW WHEN OLD.cohort IS NOT NEW.cohort
BEGIN
    SELECT RAISE(ABORT, 'cohort is immutable');
END;

-- The audit log is append-only or it is not an audit log.
CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def reset(path: str | Path) -> sqlite3.Connection:
    """Drop and recreate. Used by `make gen` so runs are reproducible from a seed."""
    p = Path(path)
    if p.exists():
        p.unlink()
    p.parent.mkdir(parents=True, exist_ok=True)
    return connect(p)
