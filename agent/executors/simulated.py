"""Phase 1's executor: outcomes drawn from the hidden response model, never seen by
the agent (datagen/ is import-isolated from agent/ — invariant 7; enforced by
tests/test_isolation.py). Phase 2 swaps in a LiveExecutor behind the same
`ExecutorPort` with no change to agent/pipeline.py.

Contract for every action it performs is declared in agent/executors/contracts.py:
input model, validation, output, typed error states, idempotency key.

Idempotency: the key is derived from the Verdict alone (`verdict.idempotency_key`),
so re-delivering the same authorization always maps to the same key and cannot
spend twice. It used to be derived from a live `attempts` read at dispatch time,
which meant one authorization executed after `attempts` had already been
incremented produced a *different* key and spent again — see DECISIONS.md ADR-018.
"""

from __future__ import annotations

import random
import sqlite3

from agent.clock import Clock
from agent.executors.contracts import (
    ActionErrorCode,
    ActionRefused,
    ExecutionUncertain,
    UncertaintyCode,
    build_retry_input,
    check_executable_state,
)
from agent.models import (
    Action,
    ActionOutcome,
    ActionResult,
    CaseState,
    ExecutionMode,
    Method,
    Verdict,
    idempotency_key,
)

# Re-exported for callers that imported it from here before it moved to
# agent/models.py (where the policy engine can also reach it without importing
# an executor). One definition, two consumers, no drift.
__all__ = ["SimulatedExecutor", "idempotency_key"]


class SimulatedExecutor:
    """`outcome_fn(verdict) -> probability of success` is the hidden response model.
    It is injected, not imported, so this module never needs to know its shape.
    """

    MODE = ExecutionMode.SIM

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        outcome_fn,
        rng: random.Random,
        *,
        timeout_fn=None,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._outcome_fn = outcome_fn
        self._rng = rng
        self._timeout_fn = timeout_fn  # (verdict) -> bool; True = simulate timeout

    def execute(self, verdict: Verdict) -> ActionResult:
        # --- 1. the case must exist -----------------------------------------
        row = self._conn.execute(
            "SELECT order_id, method, amount_paise, state FROM cases WHERE case_id = ?",
            (verdict.case_id,),
        ).fetchone()
        if row is None:
            raise ActionRefused(ActionErrorCode.UNKNOWN_CASE, verdict.case_id)

        # --- 2. invalid + unauthorized commands ------------------------------
        # Validation lives in the contract, not here, so every executor enforces
        # the same preconditions and none can skip one by accident.
        action_input = build_retry_input(
            verdict,
            order_id=row["order_id"],
            method=Method(row["method"]),
            amount_paise=row["amount_paise"],
        )
        key = action_input.idempotency_key

        # --- 3. duplicate command, already completed -------------------------
        # Deliberately checked BEFORE the state check. A completed action has
        # already happened, so the case having since moved to RECOVERED or
        # ABANDONED is expected rather than an error — refusing here with
        # ILLEGAL_STATE would make a re-delivering scheduler think the work
        # failed and retry it forever. Returning the original result is what
        # actually makes at-least-once delivery converge.
        existing = self._conn.execute(
            "SELECT executed_at, succeeded FROM actions WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if existing is not None and existing["executed_at"] is not None:
            return ActionResult(
                case_id=action_input.case_id,
                action=Action.RETRY,
                idempotency_key=key,
                outcome=ActionOutcome.SUCCEEDED if existing["succeeded"] else ActionOutcome.FAILED,
                executed_at=self._clock.now(),
                mode=self.MODE,
                replayed=True,
                detail="idempotent replay — no second attempt spent",
            )

        # --- 4. duplicate command, still in flight ---------------------------
        # A row with executed_at IS NULL means this action was dispatched and has
        # not reported back. There is no original result to replay, and executing
        # now would race the in-flight dispatch, so this is a genuine conflict
        # rather than an idempotent no-op. Retryable: once the in-flight attempt
        # completes, a later delivery lands on the replay path above.
        if existing is not None:
            raise ActionRefused(
                ActionErrorCode.DUPLICATE_IN_FLIGHT,
                f"action {key[:12]}… is already dispatched and has not completed",
            )

        # --- 5. invalid state transition -------------------------------------
        # Independent of the policy engine's REQUIRED_STATE rule: that checked the
        # state at authorization time, this checks it at execution time, and a
        # case can reach a terminal state in between.
        check_executable_state(CaseState(row["state"]))

        # --- 5.5. simulated timeout (Phase 2: real network deadline) ----------
        # Checked AFTER validation and dedup but BEFORE the outcome: the action
        # has been dispatched to the provider (validation passed, no duplicate)
        # but we timed out waiting for the response. The action may or may not
        # have actually completed — we don't know.
        if self._timeout_fn and self._timeout_fn(verdict):
            raise ExecutionUncertain(
                UncertaintyCode.EXECUTION_TIMEOUT,
                f"timeout executing {verdict.action.value} for {verdict.case_id}",
                idempotency_key=key,
            )

        succeeded = self._rng.random() < self._outcome_fn(verdict)
        now = self._clock.now()

        self._conn.execute(
            "INSERT OR REPLACE INTO actions"
            " (idempotency_key, case_id, action, scheduled_at, executed_at, succeeded, mode, detail)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                key,
                action_input.case_id,
                Action.RETRY.value,
                action_input.execute_at.isoformat(),
                now.isoformat(),
                int(succeeded),
                self.MODE.value,
                "",
            ),
        )
        return ActionResult(
            case_id=action_input.case_id,
            action=Action.RETRY,
            idempotency_key=key,
            outcome=ActionOutcome.SUCCEEDED if succeeded else ActionOutcome.FAILED,
            executed_at=now,
            mode=self.MODE,
        )


# NullExecutor (shadow mode) deliberately not implemented here — the approved
# Phase 1 plan explicitly defers it to Phase 2. See DECISIONS.md ADR-008.
