"""Live Razorpay API Executor. Dispatches recovery actions to Razorpay gateway in test/live mode.

Accepts a `Verdict` and nothing else (invariant 8).
Idempotency: verdict.idempotency_key is forwarded in notes and receipt metadata
so duplicate invocations never trigger secondary charges.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from agent.config import ConfigurationError
from agent.executors.contracts import ActionErrorCode, ActionRefused, ExecutionUncertain, UncertaintyCode
from agent.executors.port import ExecutorPort
from agent.logger import get_logger
from agent.models import Action, ActionOutcome, ActionResult, ExecutionMode, Verdict

logger = get_logger("agent.executors.live")


class LiveRazorpayExecutor(ExecutorPort):
    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        base_url: str = "https://api.razorpay.com/v1",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._key_id = key_id or os.environ.get("RAZORPAY_KEY_ID")
        self._key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

        if not self._key_id or not self._key_secret:
            raise ConfigurationError(
                "LiveRazorpayExecutor requires RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET. "
                "Ensure both are set in .env."
            )

    def _client(self) -> httpx.Client:
        return httpx.Client(auth=(self._key_id, self._key_secret), timeout=self._timeout)

    def execute(
        self,
        verdict: Verdict,
        *,
        amount_paise: int = 100000,
        description: str = "Payment Recovery Retry",
    ) -> ActionResult:
        """Executes authorized recovery on Razorpay API or raises ActionRefused / ExecutionUncertain."""
        if not verdict.is_executable:
            raise ActionRefused(
                ActionErrorCode.NOT_AUTHORIZED,
                f"Verdict decision={verdict.decision.value}, action={verdict.action.value} is not executable",
            )

        if verdict.action is not Action.RETRY:
            raise ActionRefused(
                ActionErrorCode.ACTION_MISMATCH,
                f"LiveRazorpayExecutor only executes Action.RETRY, got {verdict.action.value}",
            )

        t0 = time.perf_counter()
        payload = {
            "amount": int(amount_paise),
            "currency": "INR",
            "accept_partial": False,
            "description": description,
            "reference_id": verdict.idempotency_key[:40],
            "notes": {
                "case_id": verdict.case_id,
                "idempotency_key": verdict.idempotency_key,
                "reason": verdict.reason,
            },
        }

        try:
            with self._client() as client:
                url = f"{self._base_url}/payment_links"
                resp = None
                for attempt in range(3):
                    resp = client.post(url, json=payload)
                    if resp.status_code == 429:
                        logger.log_event("razorpay.rate_limit_backoff", attempt=attempt + 1, case_id=verdict.case_id)
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    break

                latency_ms = (time.perf_counter() - t0) * 1000

                if resp is not None and resp.status_code in (200, 201):
                    data = resp.json()
                    logger.log_event(
                        "razorpay.payment_link_created",
                        case_id=verdict.case_id,
                        plink_id=data.get("id"),
                        short_url=data.get("short_url"),
                        latency_ms=round(latency_ms, 2),
                    )
                    return ActionResult(
                        case_id=verdict.case_id,
                        action=verdict.action,
                        idempotency_key=verdict.idempotency_key,
                        outcome=ActionOutcome.SUCCEEDED,
                        executed_at=datetime.now(timezone.utc),
                        mode=ExecutionMode.LIVE,
                        replayed=False,
                        detail=f"Razorpay Payment Link: {data.get('id')} ({data.get('short_url')})",
                    )
                elif resp is not None and resp.status_code == 400:
                    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text}
                    err_desc = str(data.get("error", {}).get("description", "")) if isinstance(data, dict) else ""
                    if "already exists" in err_desc and "reference_id" in err_desc:
                        logger.log_event("razorpay.idempotent_replay", case_id=verdict.case_id, reference_id=verdict.idempotency_key[:40])
                        return ActionResult(
                            case_id=verdict.case_id,
                            action=verdict.action,
                            idempotency_key=verdict.idempotency_key,
                            outcome=ActionOutcome.SUCCEEDED,
                            executed_at=datetime.now(timezone.utc),
                            mode=ExecutionMode.LIVE,
                            replayed=True,
                            detail=f"Idempotent replay: {err_desc}",
                        )
                    logger.log_event("razorpay.bad_request", level="warning", case_id=verdict.case_id, error=str(data))
                    return ActionResult(
                        case_id=verdict.case_id,
                        action=verdict.action,
                        idempotency_key=verdict.idempotency_key,
                        outcome=ActionOutcome.FAILED,
                        executed_at=datetime.now(timezone.utc),
                        mode=ExecutionMode.LIVE,
                        replayed=False,
                        detail=f"Razorpay HTTP 400: {data}",
                    )
                else:
                    status_code = resp.status_code if resp else "None"
                    text = resp.text if resp else "No response"
                    raise ActionRefused(
                        ActionErrorCode.PROVIDER_ERROR,
                        f"Razorpay returned status {status_code}: {text}",
                    )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as e:
            logger.log_event("razorpay.timeout", level="error", error=str(e), case_id=verdict.case_id)
            raise ExecutionUncertain(
                UncertaintyCode.EXECUTION_TIMEOUT,
                f"Timeout contacting Razorpay API: {e}",
            )
        except ActionRefused:
            raise
        except Exception as e:
            logger.log_event("razorpay.network_error", level="error", error=str(e), case_id=verdict.case_id)
            raise ExecutionUncertain(
                UncertaintyCode.STATUS_UNKNOWN,
                f"Network error contacting Razorpay API: {e}",
            )
