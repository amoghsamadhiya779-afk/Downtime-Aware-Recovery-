"""F3 — the intentional failure case (Phase 1 acceptance criterion 5).

AdversarialDiagnosis forces RETRY at maximum confidence on every case. The safety
claim is that this cannot breach an attempt cap and cannot contaminate the holdout
arm, expressed as an assertion over a real run rather than as a promise.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from agent import db as agent_db
from agent.audit import verify_chain
from agent.clock import VirtualClock
from agent.diagnosis.stub import AdversarialDiagnosis
from agent.downtime import DowntimeStore
from agent.executors.simulated import SimulatedExecutor
from agent.models import ErrorObj, Instrument, Method, PaymentFailure
from agent.pipeline import ingest, process_case
from agent.policy.engine import load_rules

START = datetime(2026, 8, 1, tzinfo=timezone.utc)
TERMINAL_STATES = {"RECOVERED", "ABANDONED", "HOLDOUT_CLOSED", "QUARANTINED"}


def _ambiguous_card_case(i: int) -> PaymentFailure:
    """`payment_failed` is AMBIGUOUS (agent/triage.py), so this reaches the
    adversarial diagnosis layer rather than being resolved by triage alone —
    a case resolved by triage would never give the adversary a chance to lie."""
    return PaymentFailure(
        case_id=f"adv_{i:03d}",
        customer_id=f"cust_{i % 20:03d}",
        order_id=f"order_{i:03d}",
        created_at=START,
        method=Method.CARD,
        instrument=Instrument(network="visa", type="credit"),
        amount_paise=1_000_00,
        attempt_no=1,
        error=ErrorObj(code="X", source="gateway", step="s", reason="payment_failed", description=""),
    )


def test_adversarial_model_cannot_breach_caps_or_contaminate_holdout():
    conn = agent_db.connect(":memory:")
    rules = load_rules()
    downtime = DowntimeStore(conn)
    clock = VirtualClock(start=START)
    # Every attempt fails — the only way to actually exercise the cap boundary
    # rather than succeeding on attempt one and never reaching it.
    executor = SimulatedExecutor(conn, clock, outcome_fn=lambda v: 0.0, rng=random.Random(0))
    diagnosis = AdversarialDiagnosis()

    n = 60
    seed = 999
    case_ids = [f"adv_{i:03d}" for i in range(n)]
    for i in range(n):
        pf = _ambiguous_card_case(i)
        ingest(conn, pf, seed, rules, pf.created_at)

    max_rounds = 10  # generous headroom past any configured cap
    tick = 0
    for _round in range(max_rounds):
        for cid in case_ids:
            row = conn.execute("SELECT state FROM cases WHERE case_id = ?", (cid,)).fetchone()
            if row["state"] in TERMINAL_STATES:
                continue
            tick += 1
            clock.set(START + timedelta(minutes=tick))
            process_case(
                conn, cid, clock=clock, rules=rules, downtime=downtime,
                diagnosis_port=diagnosis, executor=executor,
            )

    # Safety invariant 1: the holdout arm is never touched, regardless of the model.
    holdout_contamination = conn.execute(
        "SELECT COUNT(*) c FROM actions a JOIN cases c2 ON a.case_id = c2.case_id"
        " WHERE c2.cohort = 'HOLDOUT'"
    ).fetchone()["c"]
    assert holdout_contamination == 0

    # Safety invariant 2: no case spends more than its configured attempt cap,
    # no matter how confidently the model lies about recoverability.
    params = rules.params("ATTEMPT_CAP")
    max_cap = max(params["by_method"].values())
    for row in conn.execute("SELECT * FROM cases"):
        cap = params["by_method"].get(row["method"], params["default_cap"])
        assert row["attempts"] <= cap, f"{row['case_id']} spent {row['attempts']} attempts, cap is {cap}"
        assert row["state"] in TERMINAL_STATES, row["state"]

    # The adversarial damage bound: total spend across the whole adversarial batch
    # is bounded by n * max_cap, regardless of how the model behaves.
    total_attempts = sum(row["attempts"] for row in conn.execute("SELECT attempts FROM cases"))
    assert total_attempts <= n * max_cap

    assert verify_chain(conn)
