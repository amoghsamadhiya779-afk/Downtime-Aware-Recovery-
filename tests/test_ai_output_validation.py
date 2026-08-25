"""Explicit proof for each category of invalid AI output this system must handle:
malformed output, missing fields, invalid enum values, impossible confidence, and
unsupported actions — plus the actual "fails safely" property, checked at both the
diagnosis layer (agent/diagnosis/prompting.py) and, for unsupported actions, the
policy layer (agent/policy/engine.py) as an independent second line of defense.

Most of "missing fields" / "invalid enum values" / "impossible confidence" is
Pydantic doing its job on DiagnosisProposal's field constraints — these tests exist
so that claim is demonstrated, not just assumed true because the types look right.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent.diagnosis import prompting
from agent.models import (
    Action,
    CaseState,
    CaseView,
    Cohort,
    Decision,
    DiagnosisProposal,
    DowntimeContext,
    Instrument,
    Method,
    Recoverability,
)
from agent.policy.engine import evaluate, load_rules

ALLOWED = {"error.reason", "downtime.active"}


def _valid_payload(**overrides) -> dict:
    payload = {
        "recoverability": "TRANSIENT_INFRA",
        "confidence": 0.8,
        "evidence": ["error.reason", "downtime.active"],
        "proposed_action": "RETRY",
        "proposed_delay_minutes": 30,
        "expected_outcome": {"probability_of_success": 0.6, "horizon_minutes": 30},
        "risks": [],
        "missing_information": [],
        "rationale": "issuer looks degraded",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1. Malformed output
# ---------------------------------------------------------------------------

def test_non_json_text_rejected():
    with pytest.raises(json.JSONDecodeError):
        prompting.validate("this is not json at all", ALLOWED)


def test_truncated_json_rejected():
    raw = json.dumps(_valid_payload())[:40]  # cut mid-object
    with pytest.raises(json.JSONDecodeError):
        prompting.validate(raw, ALLOWED)


def test_markdown_fenced_json_still_parses():
    """Models frequently wrap JSON in ```json ... ``` despite instructions not to
    — that's formatting noise, not malformed content, and shouldn't be rejected
    once the fence is stripped. Every field is still fully validated afterward."""
    fenced = "```json\n" + json.dumps(_valid_payload()) + "\n```"
    proposal = prompting.validate(fenced, ALLOWED)
    assert proposal.recoverability == Recoverability.TRANSIENT_INFRA


# ---------------------------------------------------------------------------
# 2. Missing fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "recoverability", "confidence", "evidence", "proposed_action",
    "expected_outcome", "risks", "missing_information", "rationale",
])
def test_missing_required_field_rejected(field):
    payload = _valid_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        prompting.validate(json.dumps(payload), ALLOWED)


def test_missing_nested_field_in_expected_outcome_rejected():
    payload = _valid_payload(expected_outcome={"probability_of_success": 0.5})  # no horizon_minutes
    with pytest.raises(ValidationError):
        prompting.validate(json.dumps(payload), ALLOWED)


# ---------------------------------------------------------------------------
# 3. Invalid enum values
# ---------------------------------------------------------------------------

def test_invalid_recoverability_value_rejected():
    payload = _valid_payload(recoverability="NOT_A_REAL_CLASS")
    with pytest.raises(ValidationError):
        prompting.validate(json.dumps(payload), ALLOWED)


def test_invalid_action_string_rejected():
    payload = _valid_payload(proposed_action="rm -rf /")
    with pytest.raises(ValidationError):
        prompting.validate(json.dumps(payload), ALLOWED)


def test_invalid_nested_risk_category_rejected():
    """Proves nested-model enum validation works, not just the top-level fields."""
    payload = _valid_payload(risks=[{"category": "MADE_UP_CATEGORY", "note": "x"}])
    with pytest.raises(ValidationError):
        prompting.validate(json.dumps(payload), ALLOWED)


def test_invalid_missing_information_value_rejected():
    payload = _valid_payload(missing_information=["SOMETHING_NOT_IN_THE_ENUM"])
    with pytest.raises(ValidationError):
        prompting.validate(json.dumps(payload), ALLOWED)


# ---------------------------------------------------------------------------
# 4. Impossible confidence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_confidence", [1.5, -0.1, 2.0, -1.0])
def test_confidence_out_of_range_rejected(bad_confidence):
    payload = _valid_payload(confidence=bad_confidence)
    with pytest.raises(ValidationError):
        prompting.validate(json.dumps(payload), ALLOWED)


@pytest.mark.parametrize("bad_prob", [1.5, -0.2])
def test_expected_outcome_probability_out_of_range_rejected(bad_prob):
    payload = _valid_payload(expected_outcome={"probability_of_success": bad_prob, "horizon_minutes": 10})
    with pytest.raises(ValidationError):
        prompting.validate(json.dumps(payload), ALLOWED)


def test_negative_horizon_minutes_rejected():
    payload = _valid_payload(expected_outcome={"probability_of_success": 0.5, "horizon_minutes": -5})
    with pytest.raises(ValidationError):
        prompting.validate(json.dumps(payload), ALLOWED)


def test_confident_with_zero_evidence_rejected():
    """Impossible in a different sense: the number is in-range but unsupported —
    a stated confidence with nothing behind it."""
    payload = _valid_payload(confidence=0.9, evidence=[])
    with pytest.raises(ValueError, match="zero evidence"):
        prompting.validate(json.dumps(payload), ALLOWED)


# ---------------------------------------------------------------------------
# 5. Unsupported actions
# ---------------------------------------------------------------------------

def test_recovery_link_rejected_at_diagnosis_layer():
    """RECOVERY_LINK is a real, schema-valid Action enum member (reserved for a
    future phase) — Pydantic alone would accept it. The diagnosis layer must
    reject it anyway, because nothing downstream implements it."""
    payload = _valid_payload(proposed_action="RECOVERY_LINK")
    with pytest.raises(ValueError, match="not yet supported"):
        prompting.validate(json.dumps(payload), ALLOWED)


def test_policy_fails_safely_on_unsupported_action_defense_in_depth():
    """Second, independent line of defense: even a DiagnosisProposal constructed
    directly (bypassing prompting.validate() entirely) must not let an
    unsupported action fall through to a silent RETRY at the policy layer."""
    proposal = DiagnosisProposal(**{**_valid_payload(), "proposed_action": Action.RETRY})
    proposal = proposal.model_copy(update={"proposed_action": Action.RECOVERY_LINK})

    case = CaseView(
        case_id="c1", cohort=Cohort.TREATED, attempts=0, method=Method.UPI,
        instrument=Instrument(vpa_handle="oksbi"), amount_paise=10000,
        is_recurring=False, state=CaseState.DIAGNOSED,
    )
    rules = load_rules()
    verdict = evaluate(proposal, case, rules, datetime.now(timezone.utc), DowntimeContext())

    assert verdict.decision == Decision.DENY
    assert verdict.action == Action.STOP  # not RETRY — the whole point of this test
    assert "SUPPORTED_ACTION" in verdict.fired_rules


# ---------------------------------------------------------------------------
# Fails safely, end to end — total exhaustion never crashes and never opens
# ---------------------------------------------------------------------------

class _AlwaysBrokenPort:
    """Simulates a provider whose every response is invalid, without needing a
    real client — exercises the same validate()/fallback path any real provider
    goes through, via the public diagnose() contract."""

    def __init__(self, last_error_substring: str) -> None:
        self._marker = last_error_substring

    def diagnose(self, inp):
        from agent.diagnosis import prompting as p

        try:
            p.validate("not json", set())
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        fallback = p.tier2_fallback(inp, last_error)
        if fallback is not None:
            return fallback
        return p.tier3_fallback(inp, last_error)


def test_fails_safely_on_total_exhaustion_no_clean_prior():
    """Reason has no CLEAN taxonomy entry, so tier2 can't help either — must land
    on tier3: UNKNOWN, STOP, never a guessed RETRY, and never an exception
    escaping to the caller."""
    from agent.diagnosis.port import DiagnosisInput
    from agent.models import ErrorObj

    inp = DiagnosisInput(
        method=Method.UPI,
        error=ErrorObj(code="X", source="gateway", step="s", reason="payment_failed"),
        amount_paise=1000, attempt_no=1, prior_failures=0,
        downtime=DowntimeContext(),
    )
    proposal = _AlwaysBrokenPort("boom").diagnose(inp)

    assert proposal.recoverability == Recoverability.UNKNOWN
    assert proposal.proposed_action == Action.STOP
    assert proposal.fallback_tier == 3


def test_last_error_surfaces_in_fallback_rationale():
    """The audit trail should show WHY a fallback fired, not just that it did."""
    from agent.diagnosis.port import DiagnosisInput
    from agent.models import ErrorObj

    inp = DiagnosisInput(
        method=Method.CARD,
        error=ErrorObj(code="X", source="gateway", step="s", reason="card_expired"),  # CLEAN -> tier2 available
        amount_paise=1000, attempt_no=1, prior_failures=0,
        downtime=DowntimeContext(),
    )
    proposal = prompting.tier2_fallback(inp, "JSONDecodeError: boom")
    assert "boom" in proposal.rationale
