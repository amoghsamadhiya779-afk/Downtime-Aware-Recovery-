"""Tests for the three canonical deterministic demo scenarios."""

from __future__ import annotations

import sqlite3
from agent import db as agent_db
from agent.audit import verify_chain
from agent.demo_scenarios import (
    trigger_duplicate_timeout_handled,
    trigger_successful_recovery,
    trigger_unsafe_ai_blocked,
)
from agent.downtime import DowntimeStore
from agent.policy.engine import load_rules
from agent.state import verify_counters


def test_scenario_1_successful_recovery_clean_state():
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    downtime = DowntimeStore(conn)

    res = trigger_successful_recovery(conn, rules=rules, downtime=downtime, deterministic_id="demo_test_01")
    assert res["scenario"] == "successful_recovery"
    assert res["case_id"] == "demo_test_01"

    detail = res["detail"]
    assert detail["phases"]["policy_result"]["policy_decision"] == "ALLOW"
    assert detail["phases"]["outcome"]["final_state"] == "RECOVERED"
    assert detail["phases"]["outcome"]["succeeded"] is True
    assert detail["phases"]["event"]["amount_rupees"] == 2499.0
    assert detail["phases"]["audit_trail"]["chain_valid"] is True
    assert verify_chain(conn) is True
    assert verify_counters(conn, "demo_test_01") is True


def test_scenario_2_unsafe_ai_blocked_clean_state():
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    downtime = DowntimeStore(conn)

    res = trigger_unsafe_ai_blocked(conn, rules=rules, downtime=downtime, deterministic_id="demo_test_02")
    assert res["scenario"] == "unsafe_ai_blocked"
    assert res["case_id"] == "demo_test_02"

    detail = res["detail"]
    assert detail["phases"]["policy_result"]["policy_decision"] == "DENY"
    assert "ATTEMPT_CAP" in detail["phases"]["policy_result"]["fired_rules"]
    assert detail["phases"]["outcome"]["final_state"] == "ABANDONED"
    assert detail["phases"]["outcome"]["outcome_status"] == "BLOCKED_BY_POLICY"
    assert detail["phases"]["audit_trail"]["chain_valid"] is True
    assert verify_chain(conn) is True
    assert verify_counters(conn, "demo_test_02") is True


def test_scenario_3_duplicate_timeout_handled_clean_state():
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    downtime = DowntimeStore(conn)

    res = trigger_duplicate_timeout_handled(conn, rules=rules, downtime=downtime, deterministic_id="demo_test_03")
    assert res["scenario"] == "duplicate_timeout_handled"
    assert res["case_id"] == "demo_test_03"

    detail = res["detail"]
    assert detail["phases"]["outcome"]["final_state"] == "QUARANTINED"
    assert detail["phases"]["outcome"]["outcome_status"] == "UNCERTAIN"
    assert detail["phases"]["audit_trail"]["chain_valid"] is True
    assert verify_chain(conn) is True
    assert verify_counters(conn, "demo_test_03") is True
