import pytest
from datetime import datetime, timezone

from agent.clock import VirtualClock
from agent.db import reset
from agent.demo_scenarios import (
    run_demo_scenario,
    trigger_duplicate_event,
    trigger_execution_timeout,
    trigger_invalid_ai_output,
    trigger_policy_rejection,
)
from agent.downtime import DowntimeStore
from agent.policy.engine import load_rules


@pytest.fixture
def setup():
    conn = reset(":memory:")
    rules = load_rules()
    downtime = DowntimeStore(conn)
    clock = VirtualClock(datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))
    return conn, rules, downtime, clock


def test_trigger_duplicate_event(setup):
    conn, rules, downtime, clock = setup

    res = trigger_duplicate_event(conn, clock=clock, rules=rules, downtime=downtime)

    assert res["scenario"] == "duplicate_event"
    assert res["case_id"].startswith("demo_dup_")
    assert "detail" in res

    detail = res["detail"]
    assert detail["event"]["method"] == "upi"
    assert detail["outcome"]["final_state"] == "RECOVERED"
    assert detail["audit_trail"]["chain_valid"] is True

    # Verify action was recorded with idempotency key
    action_row = conn.execute("SELECT * FROM actions WHERE case_id = ?", (res["case_id"],)).fetchone()
    assert action_row is not None
    assert action_row["executed_at"] is not None


def test_trigger_invalid_ai_output(setup):
    conn, rules, downtime, clock = setup

    res = trigger_invalid_ai_output(conn, clock=clock, rules=rules, downtime=downtime)

    assert res["scenario"] == "invalid_ai_output"
    assert res["case_id"].startswith("demo_invalid_ai_")

    detail = res["detail"]
    # AI Diagnosis safely fell back to Tier 3 UNKNOWN
    assert detail["ai_diagnosis"]["recoverability"] == "UNKNOWN"
    assert detail["ai_diagnosis"]["fallback_tier"] == 3
    assert detail["proposed_action"]["proposed_action"] == "STOP"

    # Zero-LLM Policy rejected retry and safely halted
    assert detail["policy_result"]["policy_decision"] == "DENY"
    assert detail["outcome"]["final_state"] == "ABANDONED"
    assert detail["execution"]["is_dispatched"] is False
    assert detail["audit_trail"]["chain_valid"] is True


def test_trigger_policy_rejection(setup):
    conn, rules, downtime, clock = setup

    res = trigger_policy_rejection(conn, clock=clock, rules=rules, downtime=downtime)

    assert res["scenario"] == "policy_rejection"
    assert res["case_id"].startswith("demo_policy_veto_")

    detail = res["detail"]
    # Adversarial model claimed 100% confidence RETRY
    assert detail["ai_diagnosis"]["confidence_pct"] == 100.0
    assert detail["proposed_action"]["proposed_action"] == "RETRY"

    # Zero-LLM Policy Gate vetoed
    assert detail["policy_result"]["policy_decision"] == "DENY"
    assert "ATTEMPT_CAP" in detail["policy_result"]["fired_rules"]
    assert detail["outcome"]["final_state"] == "ABANDONED"
    assert detail["execution"]["is_dispatched"] is False
    assert detail["audit_trail"]["chain_valid"] is True


def test_trigger_execution_timeout(setup):
    conn, rules, downtime, clock = setup

    res = trigger_execution_timeout(conn, clock=clock, rules=rules, downtime=downtime)

    assert res["scenario"] == "execution_timeout"
    assert res["case_id"].startswith("demo_timeout_")

    detail = res["detail"]
    # Action was authorized and dispatched
    assert detail["policy_result"]["policy_decision"] == "ALLOW"
    assert detail["execution"]["is_dispatched"] is True

    # But encountered gateway timeout and quarantined
    assert detail["outcome"]["final_state"] == "QUARANTINED"
    assert detail["outcome"]["outcome_status"] == "UNCERTAIN"
    assert detail["audit_trail"]["chain_valid"] is True


def test_run_demo_scenario_dispatcher(setup):
    conn, rules, downtime, clock = setup

    # Valid dispatch
    res = run_demo_scenario(conn, "duplicate_event", clock=clock, rules=rules, downtime=downtime)
    assert res["scenario"] == "duplicate_event"

    # Live proof dispatch
    res_live = run_demo_scenario(conn, "live_proof", clock=clock, rules=rules, downtime=downtime)
    assert res_live["scenario"] == "live_proof"
    assert res_live["case_id"].startswith("demo_live_")

    # Invalid scenario name raises ValueError
    with pytest.raises(ValueError):
        run_demo_scenario(conn, "invalid_nonexistent_scenario", clock=clock, rules=rules, downtime=downtime)
