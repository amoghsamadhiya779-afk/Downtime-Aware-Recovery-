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

import os
import time

from agent.diagnosis import prompting
from agent.diagnosis.port import DiagnosisInput
from agent.logger import get_logger
from agent.models import DiagnosisProposal

logger = get_logger("agent.diagnosis.claude")

MODEL = "claude-sonnet-5"
TIMEOUT_SECONDS = 8
MAX_TOKENS = 600  # schema grew this session (expected_outcome, risks[], missing_information[]) — 400 was already tight


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
            max_tokens=MAX_TOKENS,
            system=prompting.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal:
        prompt = prompting.build_prompt(inp)
        fields = prompting.evidence_fields(inp)

        last_error: str | None = None
        for attempt in range(2):  # tier 1: try, then one repair
            t0 = time.perf_counter()
            try:
                raw = self._call(prompt if attempt == 0 else prompt + prompting.REPAIR_SUFFIX)
                latency_ms = (time.perf_counter() - t0) * 1000
                proposal = prompting.validate(raw, fields)
                logger.log_event(
                    "diagnosis.llm.completed",
                    model=MODEL,
                    attempt=attempt + 1,
                    latency_ms=latency_ms,
                    recoverability=proposal.recoverability.value,
                    confidence=proposal.confidence,
                )
                return proposal
            except Exception as e:
                latency_ms = (time.perf_counter() - t0) * 1000
                last_error = f"{type(e).__name__}: {e}"
                logger.log_event(
                    "diagnosis.llm.attempt_failed",
                    level="warning",
                    model=MODEL,
                    attempt=attempt + 1,
                    latency_ms=latency_ms,
                    error=last_error,
                )
                continue

        fallback = prompting.tier2_fallback(inp, last_error)
        if fallback is not None:
            logger.log_event(
                "diagnosis.fallback.tier2",
                fallback_tier=2,
                recoverability=fallback.recoverability.value,
                last_error=last_error,
            )
            return fallback
        logger.log_event(
            "diagnosis.fallback.tier3",
            level="warning",
            fallback_tier=3,
            last_error=last_error,
        )
        return prompting.tier3_fallback(inp, last_error)
