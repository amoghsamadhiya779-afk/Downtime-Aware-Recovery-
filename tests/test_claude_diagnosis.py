"""ClaudeDiagnosis fallback ladder (Phase 1 review FIX #4).

Zero network calls: `anthropic.Anthropic` is monkeypatched with a fake client that
returns canned text, so tier-1 repair, tier-2 taxonomy prior, tier-3 fail-closed,
and evidence-groundedness rejection are all exercised without needing an API key or
the real network — required before Day 2 depends on any of this being correct.
"""

from __future__ import annotations

import json

from agent.diagnosis.claude import ClaudeDiagnosis
from agent.diagnosis.port import DiagnosisInput
from agent.models import Action, DowntimeContext, ErrorObj, Method, Recoverability


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, responses: list[str]) -> None:
        # Deliberately NOT `list(responses)` — a fresh anthropic.Anthropic() client
        # (and therefore a fresh _FakeMessages) is constructed on every _call(), so
        # copying here would hand attempt 2 a brand-new, undrained list instead of
        # continuing to drain the one shared across attempts within one diagnose().
        self._responses = responses
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if not self._responses:
            raise RuntimeError("fake client ran out of canned responses")
        return _FakeResponse(self._responses.pop(0))


class _FakeAnthropicClient:
    def __init__(self, responses: list[str], **kwargs) -> None:
        self.messages = _FakeMessages(responses)


def _install_fake(monkeypatch, responses: list[str]) -> None:
    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: _FakeAnthropicClient(responses, **kw))


def _input_with_reason(reason: str) -> DiagnosisInput:
    return DiagnosisInput(
        method=Method.UPI,
        error=ErrorObj(code="X", source="gateway", step="s", reason=reason, description="d"),
        amount_paise=1000,
        attempt_no=1,
        prior_failures=0,
        downtime=DowntimeContext(),
    )


def _ambiguous_input() -> DiagnosisInput:
    return _input_with_reason("payment_failed")  # AMBIGUOUS — not in agent/triage.py's CLEAN dict


def _valid_json(**overrides) -> str:
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
    return json.dumps(payload)


def test_tier1_valid_response_used_directly(monkeypatch):
    _install_fake(monkeypatch, [_valid_json()])
    diag = ClaudeDiagnosis(api_key="test")
    proposal = diag.diagnose(_ambiguous_input())
    assert proposal.recoverability == Recoverability.TRANSIENT_INFRA
    assert proposal.fallback_tier == 0


def test_tier1_repairs_after_invalid_json(monkeypatch):
    _install_fake(monkeypatch, ["not json at all", _valid_json(rationale="repaired")])
    diag = ClaudeDiagnosis(api_key="test")
    proposal = diag.diagnose(_ambiguous_input())
    assert proposal.rationale == "repaired"


def test_evidence_groundedness_rejected_and_triggers_repair(monkeypatch):
    """An invented evidence field path must be treated as invalid, not accepted —
    the first response cites a field that was never in the input."""
    bad_evidence = _valid_json(evidence=["customer.previous_complaint_history"], rationale="hallucinated")
    good = _valid_json(rationale="grounded")
    _install_fake(monkeypatch, [bad_evidence, good])
    diag = ClaudeDiagnosis(api_key="test")
    proposal = diag.diagnose(_ambiguous_input())
    assert proposal.rationale == "grounded"


def test_tier2_taxonomy_prior_when_model_unavailable(monkeypatch):
    """Both attempts fail, but the reason is CLEAN-mapped — deterministic prior
    used at reduced confidence rather than nothing."""
    _install_fake(monkeypatch, ["nope", "still nope"])
    diag = ClaudeDiagnosis(api_key="test")
    proposal = diag.diagnose(_input_with_reason("card_expired"))  # CLEAN -> INSTRUMENT_INVALID
    assert proposal.fallback_tier == 2
    assert proposal.recoverability == Recoverability.INSTRUMENT_INVALID
    assert proposal.proposed_action == Action.RETRY
    assert proposal.confidence < 0.5


def test_tier3_fails_closed_on_genuinely_unseen_reason(monkeypatch):
    """Both attempts fail AND the reason has no taxonomy prior — must fail closed
    to STOP, never open to an unbounded retry (invariant 6)."""
    _install_fake(monkeypatch, ["nope", "still nope"])
    diag = ClaudeDiagnosis(api_key="test")
    proposal = diag.diagnose(_ambiguous_input())  # "payment_failed" has no CLEAN entry
    assert proposal.fallback_tier == 3
    assert proposal.recoverability == Recoverability.UNKNOWN
    assert proposal.proposed_action == Action.STOP
