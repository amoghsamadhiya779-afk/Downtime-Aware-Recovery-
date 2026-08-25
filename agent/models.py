"""Boundary schemas. Every type crossing a layer boundary is defined here and nowhere else.

Invariant 8: an executor accepts a `Verdict` only. A `DiagnosisProposal` can never reach one,
which is enforced by type signature rather than convention.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Method(str, Enum):
    CARD = "card"
    NETBANKING = "netbanking"
    UPI = "upi"
    EMANDATE = "emandate"


class Recoverability(str, Enum):
    """Why a failed payment might come back.

    UNKNOWN is the fail-closed sentinel (invariant 6): an unseen taxonomy combination
    costs a queued case, never an attempt.
    """

    TRANSIENT_INFRA = "TRANSIENT_INFRA"
    CUSTOMER_FIXABLE = "CUSTOMER_FIXABLE"
    INSTRUMENT_INVALID = "INSTRUMENT_INVALID"
    TERMINAL = "TERMINAL"
    UNKNOWN = "UNKNOWN"


class Action(str, Enum):
    RETRY = "RETRY"
    RECOVERY_LINK = "RECOVERY_LINK"  # reserved; Phase 2
    STOP = "STOP"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DEFER = "DEFER"
    DOWNGRADE = "DOWNGRADE"
    DENY = "DENY"


class Cohort(str, Enum):
    TREATED = "TREATED"
    HOLDOUT = "HOLDOUT"


class CaseState(str, Enum):
    DETECTED = "DETECTED"
    DIAGNOSED = "DIAGNOSED"
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    FAILED_ATTEMPT = "FAILED_ATTEMPT"
    RECOVERED = "RECOVERED"
    ABANDONED = "ABANDONED"
    HOLDOUT_CLOSED = "HOLDOUT_CLOSED"
    QUARANTINED = "QUARANTINED"


TERMINAL_STATES = frozenset(
    {CaseState.RECOVERED, CaseState.ABANDONED, CaseState.HOLDOUT_CLOSED, CaseState.QUARANTINED}
)


class Instrument(BaseModel):
    """Shape follows the documented Razorpay downtime entity (EVIDENCE.md E6)."""

    model_config = ConfigDict(frozen=True)

    bank: str | None = None  # netbanking, emandate
    network: str | None = None  # card
    type: str | None = None  # card: credit | debit
    vpa_handle: str | None = None  # upi

    def matches(self, other: "Instrument") -> bool:
        """True when `other` (a downtime scope) covers this instrument.

        A downtime window with an empty instrument covers the whole method.
        """
        fields = ("bank", "network", "type", "vpa_handle")
        scope = {f: getattr(other, f) for f in fields if getattr(other, f) is not None}
        if not scope:
            return True
        return all(getattr(self, f) == v for f, v in scope.items())


class ErrorObj(BaseModel):
    """Razorpay error envelope (EVIDENCE.md E9)."""

    model_config = ConfigDict(frozen=True)

    code: str
    source: str
    step: str
    reason: str
    description: str = ""


class PaymentFailure(BaseModel):
    """One at-risk payment. This is everything the agent is allowed to see."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    customer_id: str  # opaque random id — NOT a hash of anything real
    order_id: str
    created_at: datetime
    method: Method
    instrument: Instrument
    amount_paise: int = Field(gt=0)
    is_recurring: bool = False
    mandate_id: str | None = None
    attempt_no: int = Field(ge=1)
    error: ErrorObj


class DowntimeWindow(BaseModel):
    """Mirrors the documented Payment Downtime entity (EVIDENCE.md E6).

    `end is None` means the recovery time is unknown, which the deferral logic must handle.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    method: Method
    instrument: Instrument
    begin: datetime
    end: datetime | None = None
    status: str = "started"  # scheduled | started | resolved | updated
    scheduled: bool = False
    severity: str = "medium"  # low | medium | high
    flow: str | None = None  # UPI-specific: collect | intent | in_app (EVIDENCE.md E6)


class DowntimeContext(BaseModel):
    """What the diagnosis layer is told about concurrent degradation."""

    model_config = ConfigDict(frozen=True)

    active: bool = False
    severity: str | None = None
    scheduled: bool | None = None
    instrument_match: bool = False
    expected_end: datetime | None = None
    window_id: str | None = None


class DiagnosisProposal(BaseModel):
    """AI-1 output. A proposal, never an authorization.

    `confidence` here is the raw model-reported value. Invariant 5: it never gates.
    Policy consumes `calibrated_confidence`, which Phase 3 fits; until then the
    calibrator is identity and is labelled as such in the report.
    """

    model_config = ConfigDict(frozen=True)

    recoverability: Recoverability
    confidence: float = Field(ge=0.0, le=1.0)
    proposed_action: Action
    proposed_delay_minutes: int | None = Field(default=None, ge=0)
    rationale: str = Field(max_length=280)
    evidence: list[str] = Field(default_factory=list)
    fallback_tier: int = Field(default=0, ge=0, le=3)  # 0 = model answered first try


class CaseView(BaseModel):
    """The read-only slice of case state the policy engine is allowed to see.

    Deliberately not the DB row: policy must stay a pure function of its arguments.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    cohort: Cohort
    attempts: int = Field(ge=0)
    method: Method
    instrument: Instrument
    amount_paise: int
    is_recurring: bool
    state: CaseState


class Verdict(BaseModel):
    """The only type an executor accepts (invariant 8)."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    decision: Decision
    action: Action
    execute_at: datetime | None = None
    fired_rules: list[str] = Field(default_factory=list)
    reason: str = ""
    rules_version: int = 0

    @property
    def is_executable(self) -> bool:
        return self.decision in (Decision.ALLOW, Decision.DEFER) and self.action != Action.STOP


class ActionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    action: Action
    idempotency_key: str
    succeeded: bool
    executed_at: datetime
    mode: str = "SIM"  # SIM | LIVE | SHADOW
    detail: str = ""
