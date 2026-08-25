"""The only door into the outside world. Accepts a `Verdict` and nothing else
(invariant 8) — a `DiagnosisProposal` has no path to this Protocol, enforced by the
type signature rather than by convention.
"""

from __future__ import annotations

from typing import Protocol

from agent.models import ActionResult, Verdict


class ExecutorPort(Protocol):
    def execute(self, verdict: Verdict) -> ActionResult: ...
