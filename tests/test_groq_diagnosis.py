"""GroqDiagnosis fallback ladder — mirrors tests/test_claude_diagnosis.py exactly,
because both implementations share the same prompting/validation/fallback logic
(agent/diagnosis/prompting.py) and only differ in which API they call. If these two
test files ever diverge in what they assert, that's a signal the two providers have
stopped being truly interchangeable.

Zero network calls: `groq.Groq` is monkeypatched with a fake client.
"""

from __future__ import annotations

import json

from agent.diagnosis.groq_diagnosis import GroqDiagnosis
from agent.diagnosis.port import DiagnosisInput
from agent.models import Action, DowntimeContext, ErrorObj, Method, Recoverability


class _FakeChoice:
    def __init__(self, text: str) -> None:
        self.message = type("Message", (), {"content": text})()


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.choices = [_FakeChoice(text)]


class _FakeCompletions:
    def __init__(self, responses: list[str]) -> None:
        # Deliberately NOT list(responses) — see the matching note in
        # tests/test_claude_diagnosis.py. A fresh Groq() client is constructed on
        # every _call(), so copying here would undo draining across attempts.
        self._responses = responses

    def create(self, **kwargs):
        if not self._responses:
            raise RuntimeError("fake client ran out of canned responses")
        return _FakeResponse(self._responses.pop(0))


class _FakeGroqClient:
    def __init__(self, responses: list[str], **kwargs) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(responses)})()


def _install_fake(monkeypatch, responses: list[str]) -> None:
    monkeypatch.setattr("groq.Groq", lambda **kw: _FakeGroqClient(responses, **kw))


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
    return _input_with_reason("payment_failed")


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
    diag = GroqDiagnosis(api_key="test")
    proposal = diag.diagnose(_ambiguous_input())
    assert proposal.recoverability == Recoverability.TRANSIENT_INFRA
    assert proposal.fallback_tier == 0


def test_tier1_repairs_after_invalid_json(monkeypatch):
    _install_fake(monkeypatch, ["not json at all", _valid_json(rationale="repaired")])
    diag = GroqDiagnosis(api_key="test")
    proposal = diag.diagnose(_ambiguous_input())
    assert proposal.rationale == "repaired"


def test_evidence_groundedness_rejected_and_triggers_repair(monkeypatch):
    bad_evidence = _valid_json(evidence=["customer.previous_complaint_history"], rationale="hallucinated")
    good = _valid_json(rationale="grounded")
    _install_fake(monkeypatch, [bad_evidence, good])
    diag = GroqDiagnosis(api_key="test")
    proposal = diag.diagnose(_ambiguous_input())
    assert proposal.rationale == "grounded"


def test_tier2_taxonomy_prior_when_model_unavailable(monkeypatch):
    _install_fake(monkeypatch, ["nope", "still nope"])
    diag = GroqDiagnosis(api_key="test")
    proposal = diag.diagnose(_input_with_reason("card_expired"))  # CLEAN -> INSTRUMENT_INVALID
    assert proposal.fallback_tier == 2
    assert proposal.recoverability == Recoverability.INSTRUMENT_INVALID
    assert proposal.proposed_action == Action.RETRY
    assert proposal.confidence < 0.5


def test_tier3_fails_closed_on_genuinely_unseen_reason(monkeypatch):
    _install_fake(monkeypatch, ["nope", "still nope"])
    diag = GroqDiagnosis(api_key="test")
    proposal = diag.diagnose(_ambiguous_input())  # "payment_failed" has no CLEAN entry
    assert proposal.fallback_tier == 3
    assert proposal.recoverability == Recoverability.UNKNOWN
    assert proposal.proposed_action == Action.STOP
