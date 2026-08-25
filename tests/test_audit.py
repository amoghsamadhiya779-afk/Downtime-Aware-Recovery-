"""Audit-log integrity (ARCHITECTURE §7): append-only, hash-chained, replayable."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from agent import db as agent_db
from agent.audit import append, replay, verify_chain
from agent.models import Cohort, ErrorObj, Instrument, Method, PaymentFailure
from agent.state import create_case, transition

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_chain_verifies_on_clean_run():
    conn = agent_db.connect(":memory:")
    append(conn, case_id="c1", actor="test", event_type="SIGNAL_RECEIVED", payload={"a": 1}, ts=NOW)
    append(conn, case_id="c1", actor="test", event_type="COHORT_ASSIGNED", payload={"cohort": "TREATED"}, ts=NOW)
    assert verify_chain(conn) is True


def test_append_only_trigger_blocks_update():
    conn = agent_db.connect(":memory:")
    append(conn, case_id="c1", actor="test", event_type="SIGNAL_RECEIVED", payload={"a": 1}, ts=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE audit_events SET payload = '{}' WHERE seq = 1")


def test_append_only_trigger_blocks_delete():
    conn = agent_db.connect(":memory:")
    append(conn, case_id="c1", actor="test", event_type="SIGNAL_RECEIVED", payload={"a": 1}, ts=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM audit_events WHERE seq = 1")


def test_chain_detects_single_byte_tamper_even_if_trigger_bypassed():
    """Defense in depth: if the append-only trigger is ever bypassed (e.g. schema-level
    access), the hash chain independently catches a single altered byte."""
    conn = agent_db.connect(":memory:")
    append(conn, case_id="c1", actor="test", event_type="SIGNAL_RECEIVED", payload={"a": 1}, ts=NOW)
    append(conn, case_id="c1", actor="test", event_type="COHORT_ASSIGNED", payload={"cohort": "TREATED"}, ts=NOW)
    assert verify_chain(conn) is True

    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit_events SET payload = ? WHERE seq = 1", ('{"a": 2}',))
    assert verify_chain(conn) is False


def test_replay_matches_state_store():
    conn = agent_db.connect(":memory:")
    pf = PaymentFailure(
        case_id="c1", customer_id="cust1", order_id="o1", created_at=NOW,
        method=Method.UPI, instrument=Instrument(vpa_handle="oksbi"), amount_paise=1000,
        attempt_no=1, error=ErrorObj(code="X", source="gateway", step="s", reason="payment_failed"),
    )
    create_case(conn, pf, Cohort.TREATED)
    append(conn, case_id="c1", actor="ingest", event_type="SIGNAL_RECEIVED", payload={}, ts=NOW)
    append(conn, case_id="c1", actor="ledger", event_type="COHORT_ASSIGNED", payload={"cohort": "TREATED"}, ts=NOW)
    transition(conn, "c1", "DIAGNOSED")
    append(conn, case_id="c1", actor="pipeline", event_type="STATE_TRANSITION", payload={"to": "DIAGNOSED"}, ts=NOW)
    transition(conn, "c1", "ABANDONED", abandon_reason="test reason")
    append(
        conn, case_id="c1", actor="pipeline", event_type="STATE_TRANSITION",
        payload={"to": "ABANDONED", "reason": "test reason"}, ts=NOW,
    )

    replayed = replay(conn, "c1")
    row = conn.execute("SELECT * FROM cases WHERE case_id = 'c1'").fetchone()
    assert replayed["state"] == row["state"] == "ABANDONED"
    assert replayed["cohort"] == row["cohort"] == "TREATED"
    assert replayed["attempts"] == row["attempts"] == 0
    assert replayed["abandon_reason"] == "test reason"
