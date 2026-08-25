"""The six required policy-engine scenarios, plus the four-field decision record.

One test per named scenario — valid action, excessive action, low confidence,
duplicate action, economic failure, missing required state — asserting both the
decision and which rule produced it. Asserting only the decision would pass even
if the right answer came from the wrong rule, which is the failure mode that
matters when rule order is the safety argument.

Like tests/test_policy.py, this file imports no provider SDK: the gate must be
provable with no model present at all.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
    Method,
    Recoverability,
    idempotency_key,
)
from agent.policy.engine import evaluate, load_rules

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
RULES = load_rules()
NO_DOWNTIME = DowntimeContext()

# Comfortably above EV_FLOOR so that rule never fires incidentally in tests that
# are about something else.
HEALTHY_AMOUNT_PAISE = 500_00


def _case(**overrides) -> CaseView:
    defaults = dict(
        case_id="c1",
        cohort=Cohort.TREATED,
        attempts=0,
        method=Method.UPI,
        instrument=Instrument(vpa_handle="oksbi"),
        amount_paise=HEALTHY_AMOUNT_PAISE,
        is_recurring=False,
        state=CaseState.DIAGNOSED,
    )
    defaults.update(overrides)
    return CaseView(**defaults)


def _proposal(**overrides) -> DiagnosisProposal:
    defaults = dict(
        recoverability=Recoverability.TRANSIENT_INFRA,
        confidence=0.8,
        evidence=["error.reason"],
        proposed_action=Action.RETRY,
        proposed_delay_minutes=15,
        expected_outcome=ExpectedOutcome(probability_of_success=0.6, horizon_minutes=15),
        risks=[],
        missing_information=[],
        rationale="test",
    )
    defaults.update(overrides)
    return DiagnosisProposal(**defaults)


# ---------------------------------------------------------------------------
# Every decision carries rule, reason, policy version, timestamp
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case,proposal,rules", [
    (_case(), _proposal(), RULES),                                  # ALLOW
    (_case(attempts=99), _proposal(), RULES),                       # DENY
    (_case(), _proposal(confidence=0.01), RULES),                   # REVIEW
])
def test_every_decision_carries_the_four_required_fields(case, proposal, rules):
    v = evaluate(proposal, case, rules, NOW, NO_DOWNTIME)
    assert v.reason, "every decision must state a reason"
    assert v.rules_version == rules.version
    assert v.decided_at == NOW
    # ALLOW on a clean path legitimately fires no gate; every non-ALLOW must name
    # the rule that produced it.
    if v.decision is not Decision.ALLOW:
        assert v.fired_rules, f"{v.decision} must name the rule responsible"


# ---------------------------------------------------------------------------
# 1. Valid action
# ---------------------------------------------------------------------------

def test_valid_action_is_allowed():
    v = evaluate(_proposal(), _case(), RULES, NOW, NO_DOWNTIME)
    assert v.decision is Decision.ALLOW
    assert v.action is Action.RETRY
    assert v.is_executable
    assert v.execute_at is not None and v.execute_at > NOW


# ---------------------------------------------------------------------------
# 2. Excessive action
# ---------------------------------------------------------------------------

def test_excessive_action_denied_by_attempt_cap():
    cap = RULES.params("ATTEMPT_CAP")["by_method"]["upi"]
    v = evaluate(_proposal(), _case(attempts=cap), RULES, NOW, NO_DOWNTIME)
    assert v.decision is Decision.DENY
    assert "ATTEMPT_CAP" in v.fired_rules
    assert not v.is_executable


def test_cap_binds_even_at_maximum_confidence():
    """The adversarial guarantee: confidence cannot buy past the budget."""
    cap = RULES.params("ATTEMPT_CAP")["by_method"]["upi"]
    v = evaluate(_proposal(confidence=1.0), _case(attempts=cap), RULES, NOW, NO_DOWNTIME)
    assert v.decision is Decision.DENY
    assert "ATTEMPT_CAP" in v.fired_rules


# ---------------------------------------------------------------------------
# 3. Low confidence
# ---------------------------------------------------------------------------

def test_low_confidence_routes_to_review_not_deny():
    floor = RULES.params("CONFIDENCE_FLOOR")["min_calibrated_confidence"]
    v = evaluate(_proposal(confidence=floor - 0.1), _case(), RULES, NOW, NO_DOWNTIME)
    assert v.decision is Decision.REVIEW
    assert "CONFIDENCE_FLOOR" in v.fired_rules
    assert not v.is_executable  # REVIEW is not an authorization


def test_confidence_floor_reads_the_calibrated_value_not_the_raw_one():
    """Invariant 5: policy must gate on calibrated confidence. A high raw number
    must not rescue a low calibrated one."""
    floor = RULES.params("CONFIDENCE_FLOOR")["min_calibrated_confidence"]
    v = evaluate(
        _proposal(confidence=0.99), _case(), RULES, NOW, NO_DOWNTIME,
        calibrated_confidence=floor - 0.1,
    )
    assert v.decision is Decision.REVIEW
    assert "CONFIDENCE_FLOOR" in v.fired_rules


def test_a_deny_beats_a_review():
    """Rule order is the safety argument: a terminal case with low confidence must
    DENY, not land in a human queue as though it were merely uncertain."""
    floor = RULES.params("CONFIDENCE_FLOOR")["min_calibrated_confidence"]
    v = evaluate(
        _proposal(recoverability=Recoverability.TERMINAL, proposed_action=Action.STOP,
                  confidence=floor - 0.1),
        _case(), RULES, NOW, NO_DOWNTIME,
    )
    assert v.decision is Decision.DENY
    assert "TERMINAL_CLASS" in v.fired_rules


# ---------------------------------------------------------------------------
# 4. Duplicate action
# ---------------------------------------------------------------------------

def test_duplicate_action_denied():
    case = _case(attempts=0)
    already_ran = idempotency_key(case.case_id, Action.RETRY, 1)
    v = evaluate(
        _proposal(), _case(attempts=0, executed_action_keys=frozenset({already_ran})),
        RULES, NOW, NO_DOWNTIME,
    )
    assert v.decision is Decision.DENY
    assert "DUPLICATE_ACTION" in v.fired_rules


def test_a_different_attempt_is_not_a_duplicate():
    """Idempotency is scoped to (case, action, attempt_no) — attempt 2 is a new
    action, not a replay of attempt 1."""
    case_id = "c1"
    attempt_one = idempotency_key(case_id, Action.RETRY, 1)
    v = evaluate(
        _proposal(), _case(attempts=1, executed_action_keys=frozenset({attempt_one})),
        RULES, NOW, NO_DOWNTIME,
    )
    assert v.decision is Decision.ALLOW
    assert "DUPLICATE_ACTION" not in v.fired_rules


# ---------------------------------------------------------------------------
# 5. Economic failure
# ---------------------------------------------------------------------------

def test_economically_worthless_action_denied():
    params = RULES.params("EV_FLOOR")
    cost, p = params["action_cost_paise"], params["assumed_success_rate"]
    break_even = cost / p
    v = evaluate(_proposal(), _case(amount_paise=int(break_even) - 1), RULES, NOW, NO_DOWNTIME)
    assert v.decision is Decision.DENY
    assert "EV_FLOOR" in v.fired_rules


def test_ev_floor_ignores_the_models_own_success_estimate():
    """The model must not be able to inflate its way past a financial control by
    claiming a higher chance of success — EV_FLOOR uses a rules.yaml constant."""
    params = RULES.params("EV_FLOOR")
    below_break_even = int(params["action_cost_paise"] / params["assumed_success_rate"]) - 1
    v = evaluate(
        _proposal(expected_outcome=ExpectedOutcome(probability_of_success=1.0, horizon_minutes=5)),
        _case(amount_paise=below_break_even), RULES, NOW, NO_DOWNTIME,
    )
    assert v.decision is Decision.DENY
    assert "EV_FLOOR" in v.fired_rules


# ---------------------------------------------------------------------------
# 6. Missing required state
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state", [
    CaseState.RECOVERED,
    CaseState.ABANDONED,
    CaseState.HOLDOUT_CLOSED,
    CaseState.QUARANTINED,
    CaseState.DETECTED,   # not yet diagnosed — nothing to authorize against
])
def test_non_actionable_state_denied(state):
    v = evaluate(_proposal(), _case(state=state), RULES, NOW, NO_DOWNTIME)
    assert v.decision is Decision.DENY
    assert "REQUIRED_STATE" in v.fired_rules


def test_required_state_is_checked_before_anything_else():
    """A terminal-state case is a system bug; it must be refused on those grounds
    rather than incidentally caught by whichever business rule happens to match."""
    v = evaluate(
        _proposal(recoverability=Recoverability.TERMINAL),
        _case(state=CaseState.RECOVERED, attempts=99), RULES, NOW, NO_DOWNTIME,
    )
    assert v.fired_rules == ["REQUIRED_STATE"]


# ---------------------------------------------------------------------------
# LLM-controlled delay cannot crash or escape the gate
# ---------------------------------------------------------------------------

def test_absurd_proposed_delay_is_clamped_not_crashed():
    """proposed_delay_minutes is an unbounded LLM-controlled integer flowing into
    timedelta(); unclamped, a large enough value raises OverflowError and takes
    the policy function down with it."""
    max_delay = RULES.params("DOWNTIME_DEFER")["max_delay_minutes"]
    v = evaluate(_proposal(proposed_delay_minutes=10**15), _case(), RULES, NOW, NO_DOWNTIME)
    assert v.decision is Decision.ALLOW
    assert v.execute_at is not None
    assert (v.execute_at - NOW).total_seconds() / 60 <= max_delay


def test_proposed_delay_can_only_push_later_never_earlier():
    min_delay = RULES.params("DOWNTIME_DEFER")["min_delay_minutes"]
    v = evaluate(_proposal(proposed_delay_minutes=0), _case(), RULES, NOW, NO_DOWNTIME)
    assert (v.execute_at - NOW).total_seconds() / 60 >= min_delay
