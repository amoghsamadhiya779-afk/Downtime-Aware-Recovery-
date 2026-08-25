"""Boundary correctness for the downtime lookup (agent/downtime.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent import db as agent_db
from agent.downtime import DowntimeStore
from agent.models import DowntimeWindow, Instrument, Method

BEGIN = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
END = BEGIN + timedelta(hours=2)


def _store() -> DowntimeStore:
    return DowntimeStore(agent_db.connect(":memory:"))


def test_active_within_window():
    store = _store()
    store.add(DowntimeWindow(id="d1", method=Method.UPI, instrument=Instrument(vpa_handle="oksbi"),
                              begin=BEGIN, end=END, status="started", scheduled=False, severity="high"))
    ctx = store.context_at(Method.UPI, Instrument(vpa_handle="oksbi"), BEGIN + timedelta(hours=1))
    assert ctx.active is True
    assert ctx.expected_end == END


def test_inactive_before_begin():
    store = _store()
    store.add(DowntimeWindow(id="d1", method=Method.UPI, instrument=Instrument(vpa_handle="oksbi"),
                              begin=BEGIN, end=END, status="started", scheduled=False, severity="high"))
    assert store.context_at(Method.UPI, Instrument(vpa_handle="oksbi"), BEGIN - timedelta(minutes=1)).active is False


def test_end_is_exclusive():
    store = _store()
    store.add(DowntimeWindow(id="d1", method=Method.UPI, instrument=Instrument(vpa_handle="oksbi"),
                              begin=BEGIN, end=END, status="started", scheduled=False, severity="high"))
    assert store.context_at(Method.UPI, Instrument(vpa_handle="oksbi"), END).active is False
    assert store.context_at(Method.UPI, Instrument(vpa_handle="oksbi"), END - timedelta(seconds=1)).active is True


def test_null_end_treated_as_still_open():
    """A window with no announced end must not be treated as resolved — otherwise a
    retry could be scheduled straight back into an ongoing outage."""
    store = _store()
    store.add(DowntimeWindow(id="d1", method=Method.NETBANKING, instrument=Instrument(bank="HDFC"),
                              begin=BEGIN, end=None, status="started", scheduled=False, severity="medium"))
    far_future = BEGIN + timedelta(days=10)
    ctx = store.context_at(Method.NETBANKING, Instrument(bank="HDFC"), far_future)
    assert ctx.active is True
    assert ctx.expected_end is None


def test_non_matching_instrument_not_active():
    store = _store()
    store.add(DowntimeWindow(id="d1", method=Method.NETBANKING, instrument=Instrument(bank="HDFC"),
                              begin=BEGIN, end=END, status="started", scheduled=False, severity="medium"))
    ctx = store.context_at(Method.NETBANKING, Instrument(bank="SBIN"), BEGIN + timedelta(minutes=30))
    assert ctx.active is False


def test_non_matching_method_not_active():
    store = _store()
    store.add(DowntimeWindow(id="d1", method=Method.UPI, instrument=Instrument(vpa_handle="oksbi"),
                              begin=BEGIN, end=END, status="started", scheduled=False, severity="high"))
    ctx = store.context_at(Method.CARD, Instrument(network="visa", type="credit"), BEGIN + timedelta(minutes=30))
    assert ctx.active is False


def test_resolved_status_not_active():
    store = _store()
    store.add(DowntimeWindow(id="d1", method=Method.UPI, instrument=Instrument(vpa_handle="oksbi"),
                              begin=BEGIN, end=END, status="resolved", scheduled=False, severity="high"))
    ctx = store.context_at(Method.UPI, Instrument(vpa_handle="oksbi"), BEGIN + timedelta(minutes=30))
    assert ctx.active is False
