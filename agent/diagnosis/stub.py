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
from agent.models import Action, DiagnosisProposal, Recoverability
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
            proposed_action=action,
            proposed_delay_minutes=delay,
            rationale="stub: taxonomy-consistent guess",
            evidence=[f"error.reason={inp.error.reason}"],
            fallback_tier=0,
        )


class AdversarialDiagnosis:
    """Maximally wrong, maximally confident, on purpose (F3).

    Every case — including terminal failures and instrument-invalid ones — is
    diagnosed as immediately retryable. This is not a bug in the stub; it is the
    fixture that makes the safety claim falsifiable rather than asserted.
    """

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        return DiagnosisProposal(
            recoverability=Recoverability.TRANSIENT_INFRA,
            confidence=1.0,
            proposed_action=Action.RETRY,
            proposed_delay_minutes=0,
            rationale="adversarial fixture: always retry, always confident",
            evidence=["adversarial"],
            fallback_tier=0,
        )


class UnknownDiagnosis:
    """Always answers UNKNOWN — exercises the fail-closed path (invariant 6)."""

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        return DiagnosisProposal(
            recoverability=Recoverability.UNKNOWN,
            confidence=0.0,
            proposed_action=Action.STOP,
            rationale="stub: unrecognised combination",
            evidence=[],
            fallback_tier=3,
        )
