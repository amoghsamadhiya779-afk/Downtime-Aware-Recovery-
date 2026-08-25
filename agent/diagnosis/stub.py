"""Deterministic stand-ins for AI-1. No network, no model.

Two roles:
  StubDiagnosis        - a plausible, well-behaved model. Used wherever a test needs
                          diagnosis to run without hitting the network, and by
                          `tests/test_policy.py` to prove the policy suite passes
                          with the Anthropic SDK uninstalled.
  AdversarialDiagnosis  - the intentional failure case (F3). Forces RETRY at maximum
                          confidence on every case, including terminals. Phase 1's
                          safety claim is that this cannot cause a cap breach or
                          holdout contamination — see tests/test_adversarial.py.
"""

from __future__ import annotations

from agent.diagnosis.port import DiagnosisInput
from agent.models import (
    Action,
    DiagnosisProposal,
    ExpectedOutcome,
    Recoverability,
    RiskCategory,
    RiskFlag,
)
from agent.triage import AMBIGUOUS, CLEAN, triage


class StubDiagnosis:
    """Approximates a competent model: agrees with triage's best guess, moderate
    confidence, and correctly proposes STOP on classes that shouldn't be retried."""

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        guess = CLEAN.get(inp.error.reason, Recoverability.TRANSIENT_INFRA)
        action = Action.STOP if guess is Recoverability.TERMINAL else Action.RETRY
        delay = 60 if inp.downtime.active else 15
        return DiagnosisProposal(
            recoverability=guess,
            confidence=0.7,
            evidence=[f"error.reason={inp.error.reason}"],
            proposed_action=action,
            proposed_delay_minutes=delay,
            expected_outcome=ExpectedOutcome(probability_of_success=0.5, horizon_minutes=delay),
            risks=[],
            missing_information=[],
            rationale="stub: taxonomy-consistent guess",
            fallback_tier=0,
        )


class AdversarialDiagnosis:
    """Maximally wrong, maximally confident, on purpose (F3).

    Every case — including terminal failures and instrument-invalid ones — is
    diagnosed as immediately retryable. This is not a bug in the stub; it is the
    fixture that makes the safety claim falsifiable rather than asserted. It also
    over-claims expected_outcome and denies every risk, matching how an adversarial
    (or simply badly miscalibrated) model would fill out the rest of the schema —
    the safety claim has to hold even when every self-reported field lies, not just
    proposed_action.
    """

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        return DiagnosisProposal(
            recoverability=Recoverability.TRANSIENT_INFRA,
            confidence=1.0,
            evidence=["adversarial"],
            proposed_action=Action.RETRY,
            proposed_delay_minutes=0,
            expected_outcome=ExpectedOutcome(probability_of_success=1.0, horizon_minutes=0),
            risks=[],
            missing_information=[],
            rationale="adversarial fixture: always retry, always confident",
            fallback_tier=0,
        )


class UnknownDiagnosis:
    """Always answers UNKNOWN — exercises the fail-closed path (invariant 6)."""

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        return DiagnosisProposal(
            recoverability=Recoverability.UNKNOWN,
            confidence=0.0,
            evidence=[],
            proposed_action=Action.STOP,
            expected_outcome=ExpectedOutcome(probability_of_success=0.0, horizon_minutes=0),
            risks=[RiskFlag(category=RiskCategory.AMBIGUOUS_SIGNAL, note="reason/context combination not in the known taxonomy")],
            missing_information=[],
            rationale="stub: unrecognised combination",
            fallback_tier=3,
        )
