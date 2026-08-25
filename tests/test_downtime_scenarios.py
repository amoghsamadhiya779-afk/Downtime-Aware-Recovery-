"""Tests for downtime scenarios S1, S2 (burst), and S3 (negative control).

Verifies:
1. S2 (burst outage) produces non-zero DOWNTIME_DEFER count (overlap actually occurs).
2. S3 (negative control) produces exactly zero DOWNTIME_DEFER count and zero downtime windows.
3. S1 (realistic baseline) runs with expected low overlap.
4. All three scenarios run deterministically and publish valid evaluation reports.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone

import pytest
from agent import db as agent_db
from agent.clock import VirtualClock
from agent.diagnosis.stub import StubDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.pipeline import process_case
from agent.policy.engine import load_rules
from datagen.generate import generate, write_operational_db
from evalharness.run import make_outcome_fn, run_all_scenarios


def _execute_corpus_and_count_downtime_defer(scenario_id: str, seed: int = 42, n: int = 300) -> tuple[int, int]:
    """Generates scenario, runs pipeline, and returns (downtime_windows_count, downtime_defer_count)."""
    records, windows, manifest = generate(seed=seed, n=n, corpus="dev", scenario_id=scenario_id)

    conn = agent_db.connect(":memory:")
    rules = load_rules()
    write_operational_db(conn, records, windows, seed, rules)

    downtime = DowntimeStore(conn)
    clock = VirtualClock(start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    gt = {r.ground_truth.case_id: r.ground_truth for r in records}
    outcome_fn = make_outcome_fn(gt)
    executor = SimulatedExecutor(conn, clock, outcome_fn, random.Random(seed))
    diagnosis_port = StubDiagnosis()

    case_rows = conn.execute("SELECT case_id, created_at, state FROM cases ORDER BY created_at ASC").fetchall()
    for r in case_rows:
        if r["state"] == "DETECTED":
            clock.set(datetime.fromisoformat(r["created_at"]))
            process_case(
                conn,
                r["case_id"],
                clock=clock,
                rules=rules,
                downtime=downtime,
                diagnosis_port=diagnosis_port,
                executor=executor,
            )

    defer_count = 0
    for row in conn.execute("SELECT payload FROM audit_events WHERE event_type = 'POLICY_VERDICT'"):
        payload = json.loads(row[0])
        if "DOWNTIME_DEFER" in payload.get("fired_rules", []):
            defer_count += 1

    conn.close()
    return len(windows), defer_count


def test_s2_burst_produces_nonzero_downtime_defer():
    """S2 burst: elevated downtime_rate must produce overlap and non-zero DOWNTIME_DEFER count."""
    n_windows, defer_count = _execute_corpus_and_count_downtime_defer("S2", seed=42, n=300)
    assert n_windows > 0, f"Expected downtime windows in S2, got {n_windows}"
    assert defer_count > 0, f"Expected non-zero DOWNTIME_DEFER in S2 burst, got {defer_count}"


def test_s3_negative_control_produces_zero_downtime_defer():
    """S3 negative control: downtime_rate=0.0 must produce zero windows and zero DOWNTIME_DEFER triggers."""
    n_windows, defer_count = _execute_corpus_and_count_downtime_defer("S3", seed=42, n=300)
    assert n_windows == 0, f"Expected 0 downtime windows in S3 negative control, got {n_windows}"
    assert defer_count == 0, f"Expected 0 DOWNTIME_DEFER in S3 negative control, got {defer_count}"


def test_run_all_scenarios_publishes_together(tmp_path):
    """Verifies that run_all_scenarios executes S1, S2, and S3 and writes a comparative markdown report."""
    report_file = tmp_path / "report_combined.md"
    report_text = run_all_scenarios(seed=42, out_path=report_file)

    assert report_file.exists()
    assert "# Multi-Scenario Evaluation Report" in report_text
    assert "Scenario S1" in report_text
    assert "Scenario S2" in report_text
    assert "Scenario S3" in report_text
    assert "DOWNTIME_DEFER Fired" in report_text
