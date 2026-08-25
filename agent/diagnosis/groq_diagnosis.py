"""AI-1 via Groq's API with adaptive rate-limiting, backoff retries, and fallback ladders.

Structurally identical to ClaudeDiagnosis: same prompt, same evidence-groundedness
validation, same fail-closed fallback ladder, all shared via
agent/diagnosis/prompting.py. Swappable with ClaudeDiagnosis or StubDiagnosis with
no change to agent/pipeline.py (DiagnosisPort Protocol).
"""

from __future__ import annotations

import os
import time
from typing import Any

from agent.diagnosis import prompting
from agent.diagnosis.port import DiagnosisInput
from agent.logger import get_logger
from agent.models import DiagnosisProposal

logger = get_logger("agent.diagnosis.groq")

MODEL = "openai/gpt-oss-20b"
FALLBACK_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 10
MAX_TOKENS = 600
REASONING_EFFORT = "low"

_LAST_CALL_TS: float = 0.0
_MIN_REQUEST_INTERVAL: float = 0.5  # Pace requests to comply with free-tier RPM limit


class GroqDiagnosis:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("GROQ_API_KEY")

    def _call(self, prompt: str) -> str:
        global _LAST_CALL_TS

        from groq import Groq

        # Pace requests to prevent bursting
        now = time.time()
        elapsed = now - _LAST_CALL_TS
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

        _LAST_CALL_TS = time.time()
        client = Groq(api_key=self._api_key, timeout=TIMEOUT_SECONDS)

        # Call primary model
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": prompting.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            # If error is a rate limit or failure and fallback model is available, try fallback
            err_str = str(e).lower()
            if "rate_limit" in err_str or "429" in err_str or "overloaded" in err_str:
                logger.log_event("diagnosis.groq.rate_limit", level="warning", error=str(e))
                time.sleep(2.0)
                try:
                    resp = client.chat.completions.create(
                        model=FALLBACK_MODEL,
                        max_tokens=MAX_TOKENS,
                        reasoning_effort=REASONING_EFFORT,
                        messages=[
                            {"role": "system", "content": prompting.SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                    )
                    return resp.choices[0].message.content or ""
                except Exception as e2:
                    logger.log_event("diagnosis.groq.fallback_failed", level="warning", error=str(e2))
            raise

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
