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
    Method,
    Recoverability,
    RiskCategory,
    RiskFlag,
)
from agent.triage import AMBIGUOUS, CLEAN, triage


class StubDiagnosis:
    """Approximates a competent model: branches on downtime.active, is_recurring,
    amount band, error reason, and payment method to produce grounded recoverability
    diagnoses with calibrated confidence."""

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        # 1. Clean deterministic errors (if ever passed directly)
        if inp.error.reason in CLEAN:
            guess = CLEAN[inp.error.reason]
            action = Action.STOP if guess in (Recoverability.TERMINAL, Recoverability.INSTRUMENT_INVALID) else Action.RETRY
            delay = 60 if inp.downtime.active else 15
            prob = 0.0 if action == Action.STOP else (0.75 if inp.downtime.active else 0.55)
            return DiagnosisProposal(
                recoverability=guess,
                confidence=0.85,
                evidence=[f"error.reason={inp.error.reason}"],
                proposed_action=action,
                proposed_delay_minutes=delay,
                expected_outcome=ExpectedOutcome(probability_of_success=prob, horizon_minutes=delay),
                risks=[],
                missing_information=[],
                rationale="stub: deterministic clean classification",
                fallback_tier=0,
            )

        # 2. Active Downtime: transient infrastructure issue
        if inp.downtime.active:
            delay = 60
            return DiagnosisProposal(
                recoverability=Recoverability.TRANSIENT_INFRA,
                confidence=0.85,
                evidence=[f"error.reason={inp.error.reason}", "downtime.active=True"],
                proposed_action=Action.RETRY,
                proposed_delay_minutes=delay,
                expected_outcome=ExpectedOutcome(probability_of_success=0.75, horizon_minutes=delay),
                risks=[],
                missing_information=[],
                rationale="stub: diagnosed as transient infrastructure failure during active provider downtime",
                fallback_tier=0,
            )

        # 3. Recurring Mandates / Subscriptions (is_recurring=True)
        if inp.is_recurring:
            if inp.method == Method.CARD:
                return DiagnosisProposal(
                    recoverability=Recoverability.INSTRUMENT_INVALID,
                    confidence=0.80,
                    evidence=[f"error.reason={inp.error.reason}", "is_recurring=True", f"method={inp.method.value}"],
                    proposed_action=Action.STOP,
                    proposed_delay_minutes=0,
                    expected_outcome=ExpectedOutcome(probability_of_success=0.0, horizon_minutes=0),
                    risks=[],
                    missing_information=[],
                    rationale="stub: recurring card auto-debit failure; instrument invalid or blocked",
                    fallback_tier=0,
                )
            return DiagnosisProposal(
                recoverability=Recoverability.TERMINAL,
                confidence=0.85,
                evidence=[f"error.reason={inp.error.reason}", "is_recurring=True"],
                proposed_action=Action.STOP,
                proposed_delay_minutes=0,
                expected_outcome=ExpectedOutcome(probability_of_success=0.0, horizon_minutes=0),
                risks=[],
                missing_information=[],
                rationale="stub: recurring mandate terminal refusal without user intervention",
                fallback_tier=0,
            )

        # 4. Amount Band: High Amount (> ₹10,000 / 1,000,000 paise)
        if inp.amount_paise > 1_000_000 and inp.error.reason == "transaction_limit_exceeded":
            return DiagnosisProposal(
                recoverability=Recoverability.TERMINAL,
                confidence=0.85,
                evidence=[f"error.reason={inp.error.reason}", f"amount_paise={inp.amount_paise}"],
                proposed_action=Action.STOP,
                proposed_delay_minutes=0,
                expected_outcome=ExpectedOutcome(probability_of_success=0.0, horizon_minutes=0),
                risks=[],
                missing_information=[],
                rationale="stub: high-value transaction exceeded hard account limit",
                fallback_tier=0,
            )

        # 5. Method & Reason specific interactive branch
        if inp.error.reason == "authentication_failed":
            return DiagnosisProposal(
                recoverability=Recoverability.CUSTOMER_FIXABLE,
                confidence=0.80,
                evidence=[f"error.reason={inp.error.reason}"],
                proposed_action=Action.RETRY,
                proposed_delay_minutes=15,
                expected_outcome=ExpectedOutcome(probability_of_success=0.65, horizon_minutes=15),
                risks=[],
                missing_information=[],
                rationale="stub: authentication failure; customer OTP mistype or session drop",
                fallback_tier=0,
            )

        if inp.error.reason == "collect_request_expired":
            return DiagnosisProposal(
                recoverability=Recoverability.CUSTOMER_FIXABLE,
                confidence=0.75,
                evidence=[f"error.reason={inp.error.reason}", f"method={inp.method.value}"],
                proposed_action=Action.RETRY,
                proposed_delay_minutes=15,
                expected_outcome=ExpectedOutcome(probability_of_success=0.55, horizon_minutes=15),
                risks=[],
                missing_information=[],
                rationale="stub: collect request expired without response; customer retryable",
                fallback_tier=0,
            )

        # Default interactive ambiguous (payment_failed, payment_declined_by_bank)
        return DiagnosisProposal(
            recoverability=Recoverability.TRANSIENT_INFRA,
            confidence=0.70,
            evidence=[f"error.reason={inp.error.reason}"],
            proposed_action=Action.RETRY,
            proposed_delay_minutes=15,
            expected_outcome=ExpectedOutcome(probability_of_success=0.5, horizon_minutes=15),
            risks=[],
            missing_information=[],
            rationale="stub: transient payment failure; proceed with scheduled retry",
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
