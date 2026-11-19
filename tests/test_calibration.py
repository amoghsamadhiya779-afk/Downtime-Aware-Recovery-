"""Tests for Phase 3 confidence calibration, ECE, and pipeline gating."""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from agent import db as agent_db
from agent.calibration import BinnedCalibrator, expected_calibration_error
from agent.clock import VirtualClock
from agent.diagnosis.port import DiagnosisInput, DiagnosisPort
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.models import (
    Action,
    Cohort,
    Decision,
    DiagnosisProposal,
    ErrorObj,
    ExpectedOutcome,
    Instrument,
    Method,
    PaymentFailure,
    Recoverability,
)
from agent.pipeline import ingest, process_case
from agent.policy.engine import load_rules

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def test_binned_calibrator_and_ece_math() -> None:
    confs = [0.22, 0.28, 0.90, 0.90]
    outcomes = [True, False, False, False]
    assert expected_calibration_error(confs, outcomes, num_bins=10) == pytest.approx(0.575)

    cal = BinnedCalibrator(num_bins=10, alpha=1.0).fit(confs, outcomes)
    assert cal.calibrate(0.95) == pytest.approx(0.25)  # (0 + 1) / (2 + 2)
    assert cal.calibrate(0.75) == pytest.approx(0.50)  # Empty bin prior: (0 + 1) / (0 + 2)

    cal_confs = [cal.calibrate(c) for c in confs]
    assert expected_calibration_error(cal_confs, outcomes, num_bins=10) < 0.575


def test_pipeline_gates_on_calibrated_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    monkeypatch.setattr("agent.pipeline.assign_cohort", lambda *_: Cohort.TREATED)
    clock = VirtualClock(start=NOW)
    downtime = DowntimeStore(conn)
    executor = SimulatedExecutor(conn, clock, outcome_fn=lambda v: 1.0, rng=random.Random(0))

    class OverconfidentDiagnosis(DiagnosisPort):
        def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
            return DiagnosisProposal(
                recoverability=Recoverability.TRANSIENT_INFRA,
                confidence=0.95,  # Raw looks high; empirical bin 9 is below 0.40!
                evidence=["error.reason=payment_failed"],
                proposed_action=Action.RETRY,
                proposed_delay_minutes=15,
                expected_outcome=ExpectedOutcome(probability_of_success=0.9, horizon_minutes=15),
                risks=[],
                missing_information=[],
                rationale="stub overconfident",
                fallback_tier=0,
            )

    pf = PaymentFailure(
        case_id="cal_case_01",
        customer_id="cust_01",
        order_id="ord_01",
        created_at=NOW,
        method=Method.UPI,
        instrument=Instrument(vpa_handle="oksbi"),
        amount_paise=1_000_00,
        attempt_no=1,
        error=ErrorObj(code="E1", source="gateway", step="auth", reason="payment_failed", description=""),
    )
    ingest(conn, pf, 42, rules, clock.now())
    cal = BinnedCalibrator(num_bins=10, alpha=1.0).fit([0.91, 0.95, 0.98, 0.92], [True, False, False, False])

    trace = process_case(
        conn, pf.case_id, clock=clock, rules=rules, downtime=downtime,
        diagnosis_port=OverconfidentDiagnosis(), executor=executor, calibrator=cal,
    )
    assert trace.verdict.decision is Decision.REVIEW
    assert "CONFIDENCE_FLOOR" in trace.verdict.fired_rules
    assert trace.final_state == "QUARANTINED"
    conn.close()