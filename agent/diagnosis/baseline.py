"""The non-AI baseline for the core decision problem.

This is the A1 arm in the ablation design (`eval/PREREGISTRATION.md`): the thing
the AI-assisted system has to actually beat, or the AI isn't earning its place.

It is a `DiagnosisPort` like every other implementation, so swapping it in changes
exactly one component. Triage, policy, executor, ledger, and audit all stay
identical, which is what makes the comparison isolate the diagnosis layer's
contribution rather than measuring some other difference between two pipelines.

## What it does

Nothing. Deliberately.

Every ambiguous case gets the same answer: TRANSIENT_INFRA, retry once, fixed
delay. No branching on error reason, no reading downtime, no per-case logic at
all — because that is precisely what blind fixed-schedule retry does in
production today. Razorpay's own shipped Subscriptions retry (EVIDENCE.md E5)
fires on a fixed T+3 schedule without ever asking *why* a payment failed; it only
knows *that* it did. This class is that behaviour, expressed as a DiagnosisPort.

## Why it isn't smarter than this

A tempting "better baseline" would branch on `error.reason` — but that is exactly
what `agent/triage.py` already does, deterministically, for the ~70% CLEAN
majority. Those cases never reach a DiagnosisPort at all. Re-implementing
reason-based lookup here would mean the baseline arm silently benefits from the
same taxonomy the AI arm uses, and `A3 - A1` would then measure "LLM vs. lookup
table on the residual" rather than "does asking why help at all?".

Keeping the baseline genuinely context-blind is what makes the comparison honest.
It should lose on wasted-attempt rate — that is the hypothesis under test, not a
flaw in the fixture. If it doesn't lose, the AI arm has not justified itself and
`eval/report.md` is required to say so (plan: ablation arms are first-class).

## Not the same as StubDiagnosis

`StubDiagnosis` (agent/diagnosis/stub.py) consults the CLEAN taxonomy and
correctly proposes STOP on terminals — a plausible *stand-in for a model*, used so
tests can run without a network. This is a stand-in for *having no model*. They
are different fixtures answering different questions, and conflating them would
make the ablation meaningless.
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

# The fixed retry delay, in minutes. One number, no per-case variation — that is
# the entire point. Policy still applies its own floor (DOWNTIME_DEFER's
# min_delay_minutes) and every cap, exactly as it does for the AI arm.
FIXED_DELAY_MINUTES = 60


class BaselineDiagnosis:
    """Context-blind fixed retry. The A1 ablation arm."""

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        return DiagnosisProposal(
            recoverability=Recoverability.TRANSIENT_INFRA,
            # 0.5 is not a hedge, it's an honest statement: this arm has no basis
            # for a view. It stays below MIN_CONFIDENCE_REQUIRING_EVIDENCE (0.7)
            # precisely because it cites no evidence — the same rule that governs
            # the AI arm's output applies here, and this arm cannot satisfy it.
            confidence=0.5,
            evidence=[],
            proposed_action=Action.RETRY,
            proposed_delay_minutes=FIXED_DELAY_MINUTES,
            expected_outcome=ExpectedOutcome(
                probability_of_success=0.5,
                horizon_minutes=FIXED_DELAY_MINUTES,
            ),
            risks=[
                RiskFlag(
                    category=RiskCategory.LOW_SAMPLE_CONFIDENCE,
                    note="baseline arm: no case-specific reasoning performed",
                )
            ],
            # Every field the AI arm gets to use is, from this arm's perspective,
            # information it is structurally unable to act on. Recorded honestly
            # rather than left empty, so the audit trail shows a blind decision
            # was made blind, not that nothing was missing.
            missing_information=[],
            rationale="baseline: fixed retry, no diagnosis performed",
            fallback_tier=0,
        )
