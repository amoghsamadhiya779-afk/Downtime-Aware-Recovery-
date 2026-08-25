"""AI-1's boundary. A `DiagnosisPort` is a pure function: structured in, structured out.

Invariant 2 lives here by construction — this Protocol has no method for calling a
tool, reading a database, or touching the network, so nothing implementing it can
either. Diagnosis only ever runs on AMBIGUOUS cases (agent/triage.py); CLEAN and
UNKNOWN never reach it.
"""

from __future__ import annotations

from typing import Protocol

from agent.models import DiagnosisProposal, DowntimeContext, Method, ErrorObj


class DiagnosisInput:
    """Enum/numeric fields only — CLAUDE.md invariant 3: no free text ever enters a prompt."""

    __slots__ = (
        "method",
        "error",
        "amount_paise",
        "attempt_no",
        "prior_failures",
        "downtime",
        "contact_count_7d",
        "is_recurring",
    )

    def __init__(
        self,
        *,
        method: Method,
        error: ErrorObj,
        amount_paise: int,
        attempt_no: int,
        prior_failures: int,
        downtime: DowntimeContext,
        contact_count_7d: int = 0,
        is_recurring: bool = False,
    ) -> None:
        self.method = method
        self.error = error
        self.amount_paise = amount_paise
        self.attempt_no = attempt_no
        self.prior_failures = prior_failures
        self.downtime = downtime
        self.contact_count_7d = contact_count_7d
        # Available on PaymentFailure/pipeline since Phase 1 but never reached the
        # model until now — a mandate-linked failure has a materially different
        # profile (NPCI retry constraints, billing-cycle patterns) than a one-off
        # checkout failure, and the diagnosis layer had no way to know which one
        # it was looking at.
        self.is_recurring = is_recurring


class DiagnosisPort(Protocol):
    def diagnose(self, inp: DiagnosisInput) -> DiagnosisProposal: ...
