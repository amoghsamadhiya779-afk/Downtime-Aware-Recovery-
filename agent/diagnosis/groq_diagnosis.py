"""AI-1 via Groq's free tier (no per-token cost, rate-limited only — no credit
card required as of the check backing DECISIONS.md ADR-011).

Structurally identical to ClaudeDiagnosis: same prompt, same evidence-groundedness
validation, same fail-closed fallback ladder, all shared via
agent/diagnosis/prompting.py. This file supplies only the API call, using Groq's
OpenAI-compatible chat completions interface. Swappable with ClaudeDiagnosis with
no change to agent/pipeline.py — that interchangeability is exactly what the
DiagnosisPort Protocol exists for.

Default model is openai/gpt-oss-120b — confirmed live against the real API this
session via GET /openai/v1/models after llama-3.3-70b-versatile (an earlier
choice) came back 404 model_not_found; Groq had deprecated their Llama chat
models in favor of the gpt-oss line. Groq's free-model lineup changes over time;
if this model 404s as unavailable, list current models with:
    from groq import Groq; [m.id for m in Groq(api_key=...).models.list().data]
and update MODEL — this is a live external dependency, not a fixed fact.
"""

from __future__ import annotations

import os

from agent.diagnosis import prompting
from agent.diagnosis.port import DiagnosisInput
from agent.models import DiagnosisProposal

MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 8


class GroqDiagnosis:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("GROQ_API_KEY")

    def _call(self, prompt: str) -> str:
        # Imported lazily, matching ClaudeDiagnosis — this module (and the policy
        # suite) must stay importable without the groq package installed.
        from groq import Groq

        client = Groq(api_key=self._api_key, timeout=TIMEOUT_SECONDS)
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=400,
            messages=[
                {"role": "system", "content": prompting.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content

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
