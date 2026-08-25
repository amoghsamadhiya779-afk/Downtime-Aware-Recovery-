"""AI-1 via Claude Sonnet 5. Structured output, fail-closed fallback ladder.

Tier 1: ask, validate strictly, one repair retry on schema violation.
Tier 2: second failure or timeout -> deterministic taxonomy prior, confidence marked low.
Tier 3: combination genuinely unseen -> UNKNOWN, STOP. Never fails open (invariant 6).

Prompt construction, validation, and the fallback ladder are shared with every
other DiagnosisPort implementation via agent/diagnosis/prompting.py — this file
only supplies the actual API call. No tool use, no conversation history, no
customer free text (invariants 2-3): the prompt is built entirely from
`DiagnosisInput`'s enum/numeric fields.

See also agent/diagnosis/groq_diagnosis.py — a free-tier alternative behind the
same DiagnosisPort interface (DECISIONS.md ADR-011).
"""

from __future__ import annotations

import os

from agent.diagnosis import prompting
from agent.diagnosis.port import DiagnosisInput
from agent.models import DiagnosisProposal

MODEL = "claude-sonnet-5"
TIMEOUT_SECONDS = 8


class ClaudeDiagnosis:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def _call(self, prompt: str) -> str:
        # Imported lazily so this module is importable (and the policy suite runnable)
        # without the anthropic package installed — see CLAUDE.md invariant re: SDK.
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key, timeout=TIMEOUT_SECONDS)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=prompting.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        prompt = prompting.build_prompt(inp)
        fields = prompting.evidence_fields(inp)

        for attempt in range(2):  # tier 1: try, then one repair
            try:
                raw = self._call(prompt if attempt == 0 else prompt + prompting.REPAIR_SUFFIX)
                return prompting.validate(raw, fields)
            except Exception:
                continue

        fallback = prompting.tier2_fallback(inp)
        if fallback is not None:
            return fallback
        return prompting.tier3_fallback(inp)
