"""Property tests for the deterministic policy gate.

Must pass with the Anthropic SDK entirely uninstalled — this file never imports
agent.diagnosis.claude, and that is the standing proof invariant 2's isolation is
real, not aspirational.

    python -m pytest tests/test_policy.py -q
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings, strategies as st

from agent.models import (
    Action,
    CaseState,
    CaseView,
    Cohort,
    Decision,
    DiagnosisProposal,
    DowntimeContext,
    ExpectedOutcome,
    Instrument,
    Recoverability,
)
from agent.models import Method
from agent.policy.engine import evaluate, load_rules

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
RULES = load_rules()
NO_DOWNTIME = DowntimeContext()


def _case(cohort=Cohort.TREATED, attempts=0, method=Method.UPI, amount=100_00):
    return CaseView(
        case_id="c1",
        cohort=cohort,
        attempts=attempts,
        method=method,
        instrument=Instrument(vpa_handle="oksbi") if method is Method.UPI else Instrument(network="visa", type="credit"),
        amount_paise=amount,
        is_recurring=False,
        state=CaseState.DIAGNOSED,
    )


def _proposal(recoverability=Recoverability.TRANSIENT_INFRA, action=Action.RETRY, delay=15, confidence=0.7):
    return DiagnosisProposal(
        recoverability=recoverability,
        confidence=confidence,
        evidence=[],
        proposed_action=action,
        proposed_delay_minutes=delay,
        expected_outcome=ExpectedOutcome(probability_of_success=0.5, horizon_minutes=delay),
        risks=[],
        missing_information=[],
        rationale="test",
    )


recoverability_st = st.sampled_from(list(Recoverability))
action_st = st.sampled_from([Action.RETRY, Action.STOP])
attempts_st = st.integers(min_value=0, max_value=10)
confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


@given(rec=recoverability_st, act=action_st, attempts=attempts_st, conf=confidence_st)
@settings(max_examples=200)
def test_holdout_never_allowed(rec, act, attempts, conf):
    case = _case(cohort=Cohort.HOLDOUT, attempts=attempts)
    proposal = _proposal(recoverability=rec, action=act, confidence=conf)
    v = evaluate(proposal, case, RULES, NOW, NO_DOWNTIME)
    assert v.decision == Decision.DENY
    assert v.action == Action.STOP
    assert "HOLDOUT_GUARD" in v.fired_rules


@given(attempts=attempts_st, conf=confidence_st)
@settings(max_examples=200)
def test_attempt_cap_binds_regardless_of_confidence(attempts, conf):
    """Confidence cannot buy past the cap — the adversarial guarantee, in miniature."""
    cap = RULES.params("ATTEMPT_CAP")["by_method"]["upi"]
    case = _case(cohort=Cohort.TREATED, attempts=attempts, method=Method.UPI)
    proposal = _proposal(recoverability=Recoverability.TRANSIENT_INFRA, action=Action.RETRY, confidence=conf)
    v = evaluate(proposal, case, RULES, NOW, NO_DOWNTIME)
    if attempts >= cap:
        assert v.decision == Decision.DENY
        assert "ATTEMPT_CAP" in v.fired_rules


@given(rec=st.sampled_from([Recoverability.TERMINAL, Recoverability.UNKNOWN]), attempts=attempts_st)
@settings(max_examples=100)
def test_terminal_and_unknown_always_denied(rec, attempts):
    case = _case(cohort=Cohort.TREATED, attempts=attempts)
    proposal = _proposal(recoverability=rec, action=Action.RETRY)
    v = evaluate(proposal, case, RULES, NOW, NO_DOWNTIME)
    assert v.decision == Decision.DENY
    assert v.action == Action.STOP


def test_downtime_defer_schedules_strictly_after_end():
    case = _case(cohort=Cohort.TREATED, attempts=0)
    proposal = _proposal(delay=5)
    ctx = DowntimeContext(
        active=True, severity="high", scheduled=False, instrument_match=True,
        expected_end=NOW + timedelta(hours=1),
    )
    v = evaluate(proposal, case, RULES, NOW, ctx)
    # Deferral is an ALLOW with a later execute_at — the fact that it happened
    # lives in fired_rules, not in a separate decision value.
    assert v.decision == Decision.ALLOW
    assert "DOWNTIME_DEFER" in v.fired_rules
    assert v.execute_at is not None and v.execute_at > ctx.expected_end


def test_downtime_defer_applies_backoff_when_end_unknown():
    case = _case(cohort=Cohort.TREATED, attempts=0)
    proposal = _proposal(delay=5)
    ctx = DowntimeContext(active=True, severity="high", scheduled=False, instrument_match=True, expected_end=None)
    v = evaluate(proposal, case, RULES, NOW, ctx)
    assert v.decision == Decision.ALLOW
    assert "DOWNTIME_DEFER" in v.fired_rules
    backoff = RULES.params("DOWNTIME_DEFER")["unknown_end_backoff_minutes"]
    assert v.execute_at == NOW + timedelta(minutes=backoff)


def test_no_downtime_means_no_defer():
    case = _case(cohort=Cohort.TREATED, attempts=0)
    proposal = _proposal(delay=15)
    v = evaluate(proposal, case, RULES, NOW, NO_DOWNTIME)
    assert v.decision == Decision.ALLOW
    assert "DOWNTIME_DEFER" not in v.fired_rules


def test_kill_switch_denies_everything():
    rules = load_rules(kill_switch=True)
    v = evaluate(_proposal(), _case(), rules, NOW, NO_DOWNTIME)
    assert v.decision == Decision.DENY
    assert v.fired_rules == ["KILL_SWITCH"]


def test_model_proposed_stop_is_never_upgraded_to_an_attempt():
    """Nothing downstream of triage/diagnosis can turn a STOP proposal into spend."""
    case = _case(cohort=Cohort.TREATED, attempts=0)
    proposal = _proposal(recoverability=Recoverability.CUSTOMER_FIXABLE, action=Action.STOP)
    v = evaluate(proposal, case, RULES, NOW, NO_DOWNTIME)
    assert v.decision == Decision.DENY
    assert v.action == Action.STOP
