"""Phase 1's executor: outcomes drawn from the hidden response model, never seen by
the agent (datagen/ is import-isolated from agent/ — invariant 7; enforced by
tests/test_isolation.py). Phase 2 swaps in a LiveExecutor behind the same
`ExecutorPort` with no change to agent/pipeline.py.

Idempotency: retrying the same (case_id, action, attempt_no) key does not spend
twice — it returns the original result. This is what makes at-least-once scheduler
delivery safe.
"""

from __future__ import annotations

import random
import sqlite3

from agent.clock import Clock
from agent.models import Action, ActionResult, Verdict, idempotency_key

# Re-exported for callers that imported it from here before it moved to
# agent/models.py (where the policy engine can also reach it without importing
# an executor). One definition, two consumers, no drift.
__all__ = ["SimulatedExecutor", "idempotency_key"]


class SimulatedExecutor:
    """`outcome_fn(case_id) -> probability of success` is the hidden response model.
    It is injected, not imported, so this module never needs to know the model's shape.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        outcome_fn,
        rng: random.Random,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._outcome_fn = outcome_fn  # (Verdict) -> probability of success
        self._rng = rng

    def execute(self, verdict: Verdict) -> ActionResult:
        if not verdict.is_executable:
            raise ValueError(f"non-executable verdict passed to executor: {verdict.decision}")

        row = self._conn.execute(
            "SELECT attempts FROM cases WHERE case_id = ?", (verdict.case_id,)
        ).fetchone()
        attempt_no = row["attempts"] + 1
        key = idempotency_key(verdict.case_id, verdict.action, attempt_no)

        existing = self._conn.execute(
            "SELECT * FROM actions WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if existing is not None and existing["executed_at"] is not None:
            return ActionResult(
                case_id=verdict.case_id,
                action=verdict.action,
                idempotency_key=key,
                succeeded=bool(existing["succeeded"]),
                executed_at=self._clock.now(),
                mode="SIM",
                detail="idempotent replay — no second attempt spent",
            )

        p = self._outcome_fn(verdict)
        succeeded = self._rng.random() < p
        now = self._clock.now()

        self._conn.execute(
            "INSERT OR REPLACE INTO actions"
            " (idempotency_key, case_id, action, scheduled_at, executed_at, succeeded, mode, detail)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                key,
                verdict.case_id,
                verdict.action.value,
                (verdict.execute_at or now).isoformat(),
                now.isoformat(),
                int(succeeded),
                "SIM",
                "",
            ),
        )
        return ActionResult(
            case_id=verdict.case_id,
            action=verdict.action,
            idempotency_key=key,
            succeeded=succeeded,
            executed_at=now,
            mode="SIM",
        )

# NullExecutor (shadow mode) deliberately not implemented here — the approved
# Phase 1 plan explicitly defers it to Phase 2. See DECISIONS.md ADR-008.
