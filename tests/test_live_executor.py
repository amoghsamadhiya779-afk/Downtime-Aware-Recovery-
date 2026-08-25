"""Tests for LiveRazorpayExecutor (agent/executors/live.py).

Verifies:
1. Dispatch execution: creates Razorpay payment link with correct parameters.
2. Idempotency forwarding: duplicate reference_id responses return replayed=True, SUCCEEDED.
3. Decision gating: non-ALLOW verdicts raise ActionRefused(NOT_AUTHORIZED).
4. Error translation: gateway timeouts map to ExecutionUncertain(EXECUTION_TIMEOUT).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
import pytest
import httpx

from agent.executors.contracts import ActionErrorCode, ActionRefused, ExecutionUncertain, UncertaintyCode
from agent.executors.live import LiveRazorpayExecutor
from agent.models import Action, ActionOutcome, ActionResult, Decision, ExecutionMode, Verdict


class _MockTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.seen_reference_ids: set[str] = set()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "timeout" in url_str or "10.255.255.1" in url_str:
            raise httpx.ConnectTimeout("Connection timed out", request=request)

        body = json.loads(request.content.decode("utf-8"))
        ref_id = body.get("reference_id")

        if ref_id in self.seen_reference_ids:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "BAD_REQUEST_ERROR",
                        "description": f"payment link with given reference_id: {ref_id} already exists.",
                    }
                },
                request=request,
            )

        if ref_id:
            self.seen_reference_ids.add(ref_id)

        plink_id = f"plink_{uuid.uuid4().hex[:12]}"
        return httpx.Response(
            200,
            json={
                "id": plink_id,
                "amount": body.get("amount", 100000),
                "currency": "INR",
                "status": "created",
                "short_url": f"https://rzp.io/i/{plink_id}",
                "reference_id": ref_id,
            },
            request=request,
        )


@pytest.fixture
def live_executor(monkeypatch):
    transport = _MockTransport()
    executor = LiveRazorpayExecutor(key_id="rzp_test_mock", key_secret="mock_secret")
    monkeypatch.setattr(executor, "_client", lambda: httpx.Client(transport=transport, timeout=5.0))
    return executor


def test_live_executor_refuses_non_allow_verdict(live_executor):
    verdict = Verdict(
        case_id=f"case_test_deny_{uuid.uuid4().hex[:6]}",
        decision=Decision.DENY,
        action=Action.STOP,
        attempt_no=1,
        reason="attempt cap reached",
        rules_version=2,
        decided_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ActionRefused) as excinfo:
        live_executor.execute(verdict)
    assert excinfo.value.code is ActionErrorCode.NOT_AUTHORIZED


def test_live_executor_dispatches_payment_link(live_executor):
    case_id = f"case_test_allow_{uuid.uuid4().hex[:8]}"
    verdict = Verdict(
        case_id=case_id,
        decision=Decision.ALLOW,
        action=Action.RETRY,
        attempt_no=1,
        reason="transient failure recovered",
        rules_version=2,
        decided_at=datetime.now(timezone.utc),
    )
    result = live_executor.execute(verdict, amount_paise=150000, description="Integration Test Recovery")
    assert result.outcome is ActionOutcome.SUCCEEDED
    assert result.mode is ExecutionMode.LIVE
    assert result.replayed is False
    assert "plink_" in result.detail


def test_live_executor_idempotent_duplicate_replay(live_executor):
    case_id = f"case_test_dupe_{uuid.uuid4().hex[:8]}"
    verdict = Verdict(
        case_id=case_id,
        decision=Decision.ALLOW,
        action=Action.RETRY,
        attempt_no=1,
        reason="duplicate replay test",
        rules_version=2,
        decided_at=datetime.now(timezone.utc),
    )
    # First execution creates fresh payment link
    res1 = live_executor.execute(verdict, amount_paise=100000)
    assert res1.outcome is ActionOutcome.SUCCEEDED
    assert res1.replayed is False

    # Second execution with identical verdict / reference_id detects existing link
    res2 = live_executor.execute(verdict, amount_paise=100000)
    assert res2.outcome is ActionOutcome.SUCCEEDED
    assert res2.replayed is True


def test_live_executor_timeout_translation(monkeypatch):
    executor = LiveRazorpayExecutor(key_id="rzp_test_mock", key_secret="mock_secret", base_url="http://10.255.255.1", timeout_seconds=0.05)
    transport = _MockTransport()
    monkeypatch.setattr(executor, "_client", lambda: httpx.Client(transport=transport, timeout=0.05))

    verdict = Verdict(
        case_id="case_timeout_001",
        decision=Decision.ALLOW,
        action=Action.RETRY,
        attempt_no=1,
        reason="test timeout",
        rules_version=2,
        decided_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ExecutionUncertain) as excinfo:
        executor.execute(verdict)
    assert excinfo.value.code in (UncertaintyCode.EXECUTION_TIMEOUT, UncertaintyCode.STATUS_UNKNOWN)
