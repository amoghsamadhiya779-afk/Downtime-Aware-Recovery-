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
from agent.models import Action, DiagnosisProposal, Recoverability

SYSTEM_PROMPT = """You classify why a payment failed. You NEVER decide whether money moves —
you only propose. Respond with a single JSON object matching this schema exactly:

{"recoverability": "TRANSIENT_INFRA|CUSTOMER_FIXABLE|INSTRUMENT_INVALID|TERMINAL",
 "confidence": <0.0-1.0>,
 "proposed_action": "RETRY|STOP",
 "proposed_delay_minutes": <integer>=0>,
 "rationale": "<=280 chars",
 "evidence": ["<input field path>", ...]}

Every entry in evidence[] must be a field path drawn from the input you were given
(e.g. "error.reason", "downtime.active") — never invent a fact not present in the input.
No markdown, no prose outside the JSON object."""

REPAIR_SUFFIX = (
    "\n\nYour previous reply was invalid JSON or cited unresolvable evidence. "
    "Reply again with ONLY the JSON object."
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
        "downtime": {
            "active": inp.downtime.active,
            "severity": inp.downtime.severity,
            "scheduled": inp.downtime.scheduled,
            "expected_end": inp.downtime.expected_end.isoformat() if inp.downtime.expected_end else None,
        },
        "contact_count_7d": inp.contact_count_7d,
    }
    return json.dumps(payload, sort_keys=True)


def evidence_fields(inp: DiagnosisInput) -> set[str]:
    return {
        "method", "error.source", "error.step", "error.reason",
        "amount_paise", "attempt_no", "prior_failures",
        "downtime.active", "downtime.severity", "downtime.scheduled", "downtime.expected_end",
        "contact_count_7d",
    }


def validate(raw: str, allowed_evidence: set[str]) -> DiagnosisProposal:
    data = json.loads(raw)
    proposal = DiagnosisProposal(**data)
    unresolvable = [e for e in proposal.evidence if e not in allowed_evidence]
    if unresolvable:
        raise ValueError(f"unresolvable evidence entries: {unresolvable}")
    return proposal


def tier2_fallback(inp: DiagnosisInput) -> DiagnosisProposal | None:
    """Deterministic taxonomy prior at reduced confidence. Returns None when the
    reason has no CLEAN entry — caller must fall through to tier3 in that case."""
    from agent.triage import CLEAN

    prior = CLEAN.get(inp.error.reason)
    if prior is None:
        return None
    action = Action.STOP if prior is Recoverability.TERMINAL else Action.RETRY
    return DiagnosisProposal(
        recoverability=prior,
        confidence=0.3,
        proposed_action=action,
        proposed_delay_minutes=60,
        rationale="tier-2 fallback: model unavailable, using taxonomy prior",
        evidence=[],
        fallback_tier=2,
    )


def tier3_fallback(inp: DiagnosisInput) -> DiagnosisProposal:
    """Genuinely unseen combination. Fails closed (invariant 6) — never open."""
    result = UnknownDiagnosis().diagnose(inp)
    return result.model_copy(update={"fallback_tier": 3})
