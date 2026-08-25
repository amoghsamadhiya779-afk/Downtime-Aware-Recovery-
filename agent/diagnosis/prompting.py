"""Shared prompt construction, response validation, and fallback logic for every
LLM-backed DiagnosisPort implementation (ClaudeDiagnosis, GroqDiagnosis, ...).

Kept in exactly one place so the schema, the system prompt, and the
evidence-groundedness rule cannot drift between providers — CLAUDE.md's "one fact,
one home." A provider implementation only needs to supply `_call(prompt) -> str`;
everything else (what goes in the prompt, what counts as a valid response, what
happens when the model fails twice) is shared and therefore identically safe
regardless of which model is behind it.
"""

from __future__ import annotations

import json

from agent.diagnosis.port import DiagnosisInput
from agent.diagnosis.stub import UnknownDiagnosis
from agent.models import Action, DiagnosisProposal, MissingInfoCategory, Recoverability, RiskCategory

_RISK_CATEGORIES = " | ".join(c.value for c in RiskCategory)
_MISSING_CATEGORIES = " | ".join(c.value for c in MissingInfoCategory)

SYSTEM_PROMPT = f"""You classify why a payment failed. You NEVER decide whether money moves —
you only propose. Respond with a single JSON object matching this schema exactly:

{{"recoverability": "TRANSIENT_INFRA|CUSTOMER_FIXABLE|INSTRUMENT_INVALID|TERMINAL",
 "confidence": <0.0-1.0>,
 "evidence": ["<input field path>", ...],
 "proposed_action": "RETRY|STOP",
 "proposed_delay_minutes": <integer>=0>,
 "expected_outcome": {{"probability_of_success": <0.0-1.0>, "horizon_minutes": <integer>=0>}},
 "risks": [{{"category": "{_RISK_CATEGORIES}", "note": "<=140 chars"}}, ...],
 "missing_information": ["{_MISSING_CATEGORIES}", ...],
 "rationale": "<=280 chars"}}

Every entry in evidence[] must be a field path drawn from the input you were given
(e.g. "error.reason", "downtime.active") — never invent a fact not present in the input.
The input also includes is_recurring (this failure is on a recurring mandate, not
a one-off checkout) and downtime.instrument_match (whether the active downtime
actually affects THIS payment's specific instrument, not just its method) — use
both when they bear on the diagnosis.

confidence is how sure you are about the DIAGNOSIS (the classification).
expected_outcome.probability_of_success is how likely your PROPOSED ACTION is to
actually succeed — a different question; you can be confident in the diagnosis
while still expecting a retry to fail.

Three rules a response must satisfy or it will be rejected and you will be asked
to answer again:
  1. confidence >= 0.7 requires at least one evidence[] entry — do not state a
     confident conclusion without pointing at what it's based on.
  2. confidence >= 0.85 requires an empty missing_information[] — do not claim
     near-certainty while also flagging that relevant information is unavailable.
     Lower your confidence instead, or resolve the contradiction.
  3. recoverability=TERMINAL requires proposed_action=STOP — never propose a
     retry for something you have just classified as unrecoverable.
When genuinely uncertain, report LOWER confidence rather than omitting evidence
or missing_information to satisfy these rules artificially.

risks and missing_information use ONLY the categories listed above — pick the
closest fit, or OTHER. Include both keys even when there is nothing to report:
use an empty list, never omit the key.

proposed_action is RETRY or STOP only — never a command, a shell instruction, or
any text outside this enum. No markdown, no prose outside the JSON object."""

REPAIR_SUFFIX = (
    "\n\nYour previous reply was invalid JSON, cited unresolvable evidence, or "
    "violated one of the three rules above (confident with no evidence, "
    "near-certain with missing information outstanding, or TERMINAL paired with "
    "RETRY). Reply again with ONLY the JSON object, resolving the issue rather "
    "than just restating the same answer."
)


def build_prompt(inp: DiagnosisInput) -> str:
    payload = {
        "method": inp.method.value,
        "error": {
            "source": inp.error.source,
            "step": inp.error.step,
            "reason": inp.error.reason,
        },
        "amount_paise": inp.amount_paise,
        "attempt_no": inp.attempt_no,
        "prior_failures": inp.prior_failures,
        "is_recurring": inp.is_recurring,
        "downtime": {
            "active": inp.downtime.active,
            "severity": inp.downtime.severity,
            "scheduled": inp.downtime.scheduled,
            "expected_end": inp.downtime.expected_end.isoformat() if inp.downtime.expected_end else None,
            # Was computed by DowntimeStore and simply never sent — the model was
            # being told an outage exists without being told whether it actually
            # affects THIS payment's instrument, the one piece of downtime context
            # that most changes what the right answer is.
            "instrument_match": inp.downtime.instrument_match,
        },
        "contact_count_7d": inp.contact_count_7d,
    }
    return json.dumps(payload, sort_keys=True)


def evidence_fields(inp: DiagnosisInput) -> set[str]:
    return {
        "method", "error.source", "error.step", "error.reason",
        "amount_paise", "attempt_no", "prior_failures", "is_recurring",
        "downtime.active", "downtime.severity", "downtime.scheduled",
        "downtime.expected_end", "downtime.instrument_match",
        "contact_count_7d",
    }


# Thresholds for the "avoid unsupported conclusions" checks below. Deliberately
# NOT in agent/policy/rules.yaml — these are response-quality gates on the
# diagnosis layer's own output, not policy thresholds, and this file was told not
# to touch policy. A response that fails one of these is treated exactly like
# malformed JSON: it raises, the caller's existing repair-retry loop catches it,
# and un-repaired it falls through to the same tier-2/tier-3 fallback that
# handles every other validation failure — no new code path, just a stricter gate
# on the existing one.
MIN_CONFIDENCE_REQUIRING_EVIDENCE = 0.7
MAX_CONFIDENCE_WITH_MISSING_INFO = 0.85

# The system prompt only teaches the model RETRY|STOP. Action.RECOVERY_LINK is a
# real, schema-valid enum member (agent/models.py) reserved for a future phase —
# nothing implements it anywhere: no executor branch, no policy branch. Without
# this check a model proposing it would pass Pydantic validation (it's a real
# enum value) and then fall through agent/policy/engine.py's final `return
# verdict(decision, Action.RETRY, ...)`, which is a bare fallthrough, not an
# explicit RETRY check — so an unsupported-but-valid action would have been
# silently reinterpreted as RETRY rather than rejected. That is not failing
# safely, it's failing silently wrong, so it's rejected here at the source in
# addition to being hardened at the policy layer (agent/policy/engine.py) as a
# second, independent line of defense.
SUPPORTED_ACTIONS = frozenset({Action.RETRY, Action.STOP})


def _strip_code_fence(raw: str) -> str:
    """Models frequently wrap JSON in ```json ... ``` despite being told not to —
    a formatting habit, not a content problem. Stripped before parsing so a
    fenced-but-otherwise-valid response isn't treated as malformed; every field is
    still fully validated afterward, so this makes parsing more tolerant without
    making validation more permissive."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def validate(raw: str, allowed_evidence: set[str]) -> DiagnosisProposal:
    data = json.loads(_strip_code_fence(raw))
    proposal = DiagnosisProposal(**data)

    unresolvable = [e for e in proposal.evidence if e not in allowed_evidence]
    if unresolvable:
        raise ValueError(f"unresolvable evidence entries: {unresolvable}")

    if proposal.proposed_action not in SUPPORTED_ACTIONS:
        raise ValueError(
            f"proposed_action={proposal.proposed_action.value!r} is not yet "
            f"supported (only {[a.value for a in SUPPORTED_ACTIONS]} are implemented)"
        )

    # A conclusion is "supported" if it points at something. Confidence with zero
    # evidence is a bare assertion, not a diagnosis.
    if proposal.confidence >= MIN_CONFIDENCE_REQUIRING_EVIDENCE and not proposal.evidence:
        raise ValueError(
            f"confidence={proposal.confidence} with zero evidence entries — "
            f"a confident conclusion must cite what it's confident about"
        )

    # Claiming near-certainty while admitting relevant information is missing is
    # an internal contradiction, not a nuanced position.
    if proposal.confidence >= MAX_CONFIDENCE_WITH_MISSING_INFO and proposal.missing_information:
        raise ValueError(
            f"confidence={proposal.confidence} but missing_information="
            f"{[m.value for m in proposal.missing_information]} — cannot be "
            f"near-certain while flagging relevant information as unavailable"
        )

    # A TERMINAL diagnosis paired with RETRY contradicts itself regardless of what
    # policy would separately do with it — nothing recoverable should ever be
    # proposed for retry by the model that just called it unrecoverable.
    if proposal.recoverability is Recoverability.TERMINAL and proposal.proposed_action is Action.RETRY:
        raise ValueError("recoverability=TERMINAL but proposed_action=RETRY — internally inconsistent")

    return proposal


def tier2_fallback(inp: DiagnosisInput, last_error: str | None = None) -> DiagnosisProposal | None:
    """Deterministic taxonomy prior at reduced confidence. Returns None when the
    reason has no CLEAN entry — caller must fall through to tier3 in that case.

    `last_error` is the actual validation failure from the final attempt — malformed
    JSON, a missing field, an out-of-range confidence, an unsupported action,
    whatever it was. Recorded in the rationale so the audit trail shows *why* the
    model's answer was discarded, not just that it was."""
    from agent.models import ExpectedOutcome, RiskFlag
    from agent.triage import CLEAN

    prior = CLEAN.get(inp.error.reason)
    if prior is None:
        return None
    action = Action.STOP if prior is Recoverability.TERMINAL else Action.RETRY
    reason_note = f" ({last_error})" if last_error else ""
    return DiagnosisProposal(
        recoverability=prior,
        confidence=0.3,
        evidence=[],
        proposed_action=action,
        proposed_delay_minutes=60,
        expected_outcome=ExpectedOutcome(probability_of_success=0.3, horizon_minutes=60),
        risks=[RiskFlag(
            category=RiskCategory.LOW_SAMPLE_CONFIDENCE,
            note="model unavailable; taxonomy prior used, no case-specific reasoning",
        )],
        missing_information=[],
        rationale=(f"tier-2 fallback: model output invalid, using taxonomy prior{reason_note}")[:280],
        fallback_tier=2,
    )


def tier3_fallback(inp: DiagnosisInput, last_error: str | None = None) -> DiagnosisProposal:
    """Genuinely unseen combination. Fails closed (invariant 6) — never open."""
    result = UnknownDiagnosis().diagnose(inp)
    rationale = result.rationale
    if last_error:
        rationale = f"{rationale} ({last_error})"[:280]
    return result.model_copy(update={"fallback_tier": 3, "rationale": rationale})
