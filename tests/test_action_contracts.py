"""The executable-action contracts: input, validation, output, error states, and
the idempotency key.

The load-bearing test here is `test_redelivery_after_attempts_incremented_does_not_double_spend`.
Before the key was bound to the Verdict it was derived from a live `attempts`
read at dispatch time, so one authorization executed after the pipeline had
already incremented `attempts` produced a *different* key and spent a second
time. That is the exact scenario at-least-once delivery creates.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from agent import db as agent_db
from agent.executors.contracts import (
    ActionErrorCode,
    ActionRefused,
    RetryInput,
    build_retry_input,
)
from agent.executors.simulated import SimulatedExecutor
from agent.models import (
    Action,
    ActionOutcome,
    Cohort,
    Decision,
    ErrorObj,
    ExecutionMode,
    Instrument,
    Method,
    PaymentFailure,
    Verdict,
)
from agent.state import create_case, transition

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _seed_case(conn, case_id: str = "c1", *, state: str = "EXECUTING") -> PaymentFailure:
    """Create a case and walk it to `state` via legal transitions.

    Defaults to EXECUTING because that is where the pipeline actually hands a
    case to the executor — a test that executes against a freshly-created
    DETECTED case would be exercising a path the system never produces.
    """
    pf = PaymentFailure(
        case_id=case_id, customer_id="cust1", order_id="order1", created_at=NOW,
        method=Method.UPI, instrument=Instrument(vpa_handle="oksbi"),
        amount_paise=250_00, attempt_no=1,
        error=ErrorObj(code="X", source="gateway", step="s", reason="payment_failed"),
    )
    create_case(conn, pf, Cohort.TREATED)
    path = {
        "DETECTED": [],
        "DIAGNOSED": ["DIAGNOSED"],
        "SCHEDULED": ["DIAGNOSED", "SCHEDULED"],
        "EXECUTING": ["DIAGNOSED", "SCHEDULED", "EXECUTING"],
        "ABANDONED": ["DIAGNOSED", "ABANDONED"],
        "RECOVERED": ["DIAGNOSED", "SCHEDULED", "EXECUTING", "RECOVERED"],
        "QUARANTINED": ["DIAGNOSED", "QUARANTINED"],
    }[state]
    for step in path:
        transition(conn, case_id, step)
    return pf


def _verdict(case_id: str = "c1", *, attempt_no: int = 1, decision=Decision.ALLOW,
             action=Action.RETRY, execute_at=NOW) -> Verdict:
    return Verdict(
        case_id=case_id, decision=decision, action=action, attempt_no=attempt_no,
        execute_at=execute_at, rules_version=2, decided_at=NOW,
    )


def _executor(conn, outcome_p: float = 1.0, counter: dict | None = None) -> SimulatedExecutor:
    def outcome_fn(verdict):
        if counter is not None:
            counter["n"] = counter.get("n", 0) + 1
        return outcome_p

    return SimulatedExecutor(conn, _Clock(), outcome_fn, random.Random(0))


class _Clock:
    def now(self) -> datetime:
        return NOW


# ---------------------------------------------------------------------------
# Idempotency key — derived from the authorization, not from live state
# ---------------------------------------------------------------------------

def test_key_is_a_pure_function_of_the_verdict():
    v = _verdict(attempt_no=3)
    assert v.idempotency_key == _verdict(attempt_no=3).idempotency_key


def test_key_changes_with_attempt_no():
    assert _verdict(attempt_no=1).idempotency_key != _verdict(attempt_no=2).idempotency_key


def test_key_changes_with_case():
    assert _verdict("a").idempotency_key != _verdict("b").idempotency_key


def test_redelivery_after_attempts_incremented_does_not_double_spend():
    """The regression this contract exists to prevent.

    One authorization, delivered twice, with the pipeline's attempt increment in
    between — exactly what an at-least-once scheduler produces. Must spend once.
    """
    conn = agent_db.connect(":memory:")
    _seed_case(conn)
    calls: dict = {}
    executor = _executor(conn, counter=calls)
    verdict = _verdict(attempt_no=1)

    first = executor.execute(verdict)
    # Pipeline increments attempts after a successful execution.
    conn.execute("UPDATE cases SET attempts = attempts + 1 WHERE case_id = 'c1'")
    second = executor.execute(verdict)

    assert calls["n"] == 1, "outcome_fn must be consulted once per authorization"
    assert second.replayed is True
    assert second.idempotency_key == first.idempotency_key
    assert second.outcome == first.outcome
    n_rows = conn.execute("SELECT COUNT(*) c FROM actions").fetchone()["c"]
    assert n_rows == 1


def test_a_genuinely_new_authorization_is_not_deduplicated():
    """A second verdict for attempt 2 is a distinct authorization and must run."""
    conn = agent_db.connect(":memory:")
    _seed_case(conn)
    calls: dict = {}
    executor = _executor(conn, counter=calls)

    executor.execute(_verdict(attempt_no=1))
    executor.execute(_verdict(attempt_no=2))

    assert calls["n"] == 2
    assert conn.execute("SELECT COUNT(*) c FROM actions").fetchone()["c"] == 2


# ---------------------------------------------------------------------------
# Input + validation
# ---------------------------------------------------------------------------

def test_build_retry_input_produces_a_validated_model():
    inp = build_retry_input(_verdict(), order_id="order1", method=Method.UPI, amount_paise=100)
    assert isinstance(inp, RetryInput)
    assert inp.attempt_no == 1
    assert inp.idempotency_key == _verdict().idempotency_key


@pytest.mark.parametrize("bad,code", [
    (dict(amount_paise=0), ActionErrorCode.INVALID_PARAMS),
    (dict(amount_paise=-5), ActionErrorCode.INVALID_PARAMS),
    (dict(order_id=""), ActionErrorCode.INVALID_PARAMS),
])
def test_invalid_params_refused_with_typed_code(bad, code):
    kwargs = dict(order_id="order1", method=Method.UPI, amount_paise=100)
    kwargs.update(bad)
    with pytest.raises(ActionRefused) as exc:
        build_retry_input(_verdict(), **kwargs)
    assert exc.value.code is code


def test_missing_execute_at_refused():
    with pytest.raises(ActionRefused) as exc:
        build_retry_input(
            _verdict(execute_at=None), order_id="o", method=Method.UPI, amount_paise=100
        )
    assert exc.value.code is ActionErrorCode.INVALID_PARAMS


# ---------------------------------------------------------------------------
# Error states
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("decision", [Decision.DENY, Decision.REVIEW])
def test_non_authorizing_verdict_refused(decision):
    with pytest.raises(ActionRefused) as exc:
        build_retry_input(
            _verdict(decision=decision, action=Action.STOP),
            order_id="o", method=Method.UPI, amount_paise=100,
        )
    assert exc.value.code is ActionErrorCode.NOT_AUTHORIZED


def test_action_mismatch_refused():
    """An ALLOW carrying an action this executor does not implement must be
    refused by code, not silently coerced into the one it does implement."""
    v = _verdict(action=Action.RECOVERY_LINK)
    with pytest.raises(ActionRefused) as exc:
        build_retry_input(v, order_id="o", method=Method.UPI, amount_paise=100)
    assert exc.value.code is ActionErrorCode.ACTION_MISMATCH


def test_unknown_case_refused():
    conn = agent_db.connect(":memory:")  # no case seeded
    with pytest.raises(ActionRefused) as exc:
        _executor(conn).execute(_verdict())
    assert exc.value.code is ActionErrorCode.UNKNOWN_CASE


def test_refusal_codes_are_classified_retryable_or_terminal():
    """A scheduler needs to know whether re-delivery could ever succeed."""
    assert not ActionRefused(ActionErrorCode.NOT_AUTHORIZED).retryable
    assert not ActionRefused(ActionErrorCode.INVALID_PARAMS).retryable
    assert not ActionRefused(ActionErrorCode.ILLEGAL_STATE).retryable
    assert not ActionRefused(ActionErrorCode.PROVIDER_REJECTED).retryable
    assert ActionRefused(ActionErrorCode.PROVIDER_ERROR).retryable
    # Retryable: once the in-flight dispatch completes, a later delivery lands on
    # the idempotent replay path rather than conflicting again.
    assert ActionRefused(ActionErrorCode.DUPLICATE_IN_FLIGHT).retryable


# ---------------------------------------------------------------------------
# Invalid state transitions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state", ["DETECTED", "DIAGNOSED", "ABANDONED", "RECOVERED", "QUARANTINED"])
def test_execution_refused_from_a_non_executable_state(state):
    """Independent of the policy engine's REQUIRED_STATE rule: a case can reach a
    terminal state between authorization and dispatch, and an executor that
    trusts the verdict to still be current has no way to notice."""
    conn = agent_db.connect(":memory:")
    _seed_case(conn, state=state)
    with pytest.raises(ActionRefused) as exc:
        _executor(conn).execute(_verdict())
    assert exc.value.code is ActionErrorCode.ILLEGAL_STATE


@pytest.mark.parametrize("state", ["SCHEDULED", "EXECUTING"])
def test_execution_permitted_from_dispatchable_states(state):
    conn = agent_db.connect(":memory:")
    _seed_case(conn, state=state)
    result = _executor(conn).execute(_verdict())
    assert result.outcome is ActionOutcome.SUCCEEDED


def test_state_is_checked_independently_of_policy():
    """The executor must not rely on policy having checked state — nothing in
    this test ever calls evaluate(), and the refusal must still happen."""
    conn = agent_db.connect(":memory:")
    _seed_case(conn, state="ABANDONED")
    calls: dict = {}
    with pytest.raises(ActionRefused):
        _executor(conn, counter=calls).execute(_verdict())
    assert calls.get("n", 0) == 0, "nothing may be spent on an illegal-state command"


# ---------------------------------------------------------------------------
# Duplicate command still in flight
# ---------------------------------------------------------------------------

def test_in_flight_duplicate_is_refused_not_replayed():
    """A dispatched-but-uncompleted action has no result to replay, and executing
    now would race it. Previously this fell through and executed, then
    INSERT OR REPLACE overwrote the in-flight row."""
    conn = agent_db.connect(":memory:")
    _seed_case(conn)
    verdict = _verdict()
    conn.execute(
        "INSERT INTO actions (idempotency_key, case_id, action, scheduled_at, executed_at)"
        " VALUES (?,?,?,?,NULL)",
        (verdict.idempotency_key, "c1", Action.RETRY.value, NOW.isoformat()),
    )

    calls: dict = {}
    with pytest.raises(ActionRefused) as exc:
        _executor(conn, counter=calls).execute(verdict)

    assert exc.value.code is ActionErrorCode.DUPLICATE_IN_FLIGHT
    assert calls.get("n", 0) == 0
    assert conn.execute("SELECT COUNT(*) c FROM actions").fetchone()["c"] == 1


def test_completed_duplicate_replays_even_from_a_terminal_state():
    """Ordering check: the replay path must be reached before the state check.
    After a successful attempt the case is legitimately RECOVERED, and a
    re-delivery must return the original result rather than ILLEGAL_STATE — else
    a scheduler would read it as failure and retry forever."""
    conn = agent_db.connect(":memory:")
    _seed_case(conn)
    executor = _executor(conn, outcome_p=1.0)
    first = executor.execute(_verdict())

    transition(conn, "c1", "RECOVERED")
    second = executor.execute(_verdict())

    assert second.replayed is True
    assert second.outcome == first.outcome


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def test_output_carries_typed_outcome_and_mode():
    conn = agent_db.connect(":memory:")
    _seed_case(conn)
    result = _executor(conn, outcome_p=1.0).execute(_verdict())
    assert result.outcome is ActionOutcome.SUCCEEDED
    assert result.succeeded is True
    assert result.replayed is False
    assert result.mode is ExecutionMode.SIM
    assert result.action is Action.RETRY


def test_failed_attempt_is_an_outcome_not_a_refusal():
    """A payment that ran and failed produces a FAILED result — it consumed an
    attempt. A refusal produces no result at all, because nothing ran."""
    conn = agent_db.connect(":memory:")
    _seed_case(conn)
    result = _executor(conn, outcome_p=0.0).execute(_verdict())
    assert result.outcome is ActionOutcome.FAILED
    assert result.succeeded is False
    assert result.replayed is False


def test_replay_preserves_the_original_outcome():
    """Collapsing replay into its own outcome value would lose whether the first
    attempt actually succeeded."""
    conn = agent_db.connect(":memory:")
    _seed_case(conn)
    executor = _executor(conn, outcome_p=0.0)
    first = executor.execute(_verdict())
    second = executor.execute(_verdict())
    assert first.outcome is ActionOutcome.FAILED
    assert second.outcome is ActionOutcome.FAILED
    assert second.replayed is True
