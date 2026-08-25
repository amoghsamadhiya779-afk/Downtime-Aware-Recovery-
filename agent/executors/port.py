"""The only door into the outside world. Accepts a `Verdict` and nothing else
(invariant 8) — a `DiagnosisProposal` has no path to this Protocol, enforced by the
type signature rather than by convention.

The contract every implementation must honour, declared in
agent/executors/contracts.py:

    input        the Verdict, plus case data the action needs, validated into a
                 typed per-action input model (currently RetryInput)
    validation   performed by contracts.build_*_input — never re-derived per
                 executor, so no implementation can accidentally skip a check
    output       ActionResult, carrying a typed ActionOutcome and a `replayed`
                 flag distinguishing a fresh attempt from an idempotent no-op
    errors       ActionRefused(ActionErrorCode); a refusal means the action never
                 ran and must not consume attempt budget
    idempotency  verdict.idempotency_key — a pure function of the authorization,
                 so re-delivery of the same Verdict can never spend twice
"""

from __future__ import annotations

from typing import Protocol

from agent.models import ActionResult, Verdict


class ExecutorPort(Protocol):
    def execute(self, verdict: Verdict) -> ActionResult:
        """Perform the authorized action, or raise ActionRefused.

        Returning an ActionResult means the action ran (or was an idempotent
        replay of one that did). Refusing means it did not.
        """
        ...
