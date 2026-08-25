"""Boundary schemas. Every type crossing a layer boundary is defined here and nowhere else.

Invariant 8: an executor accepts a `Verdict` only. A `DiagnosisProposal` can never reach one,
which is enforced by type signature rather than convention.
"""

from __future__ import annotations

import hashlib
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
    """The three authorization outcomes.

    Deliberately not four: DEFER used to be a separate decision, but "permitted,
    later" is ALLOW with a later `execute_at` — the timing lives in the Verdict's
    own field and the fact that deferral happened lives in `fired_rules`, which is
    where the eval harness already reads it from. DOWNGRADE was never returned by
    any rule and is gone. Fewer outcomes means fewer states a caller can mishandle.
    """

    ALLOW = "ALLOW"  # authorized; execute_at says when
    DENY = "DENY"  # not authorized, and no human is being asked
    REVIEW = "REVIEW"  # not authorized automatically; routed to a human queue


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


# TERMINAL_STATES deliberately does NOT live here. Terminality is a property of
# the transition table, so it is derived from it in agent/state.py rather than
# hand-listed in a second place that can drift. The version that used to sit here
# was never read by anything. See DECISIONS.md ADR-020.


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


class RiskCategory(str, Enum):
    """Closed vocabulary for self-flagged risk — never free text. A model that
    could write an arbitrary risk description could smuggle an instruction through
    the audit trail; a model choosing from a fixed list cannot."""

    STALE_SIGNAL = "STALE_SIGNAL"  # downtime/context data may be out of date
    CUSTOMER_FATIGUE = "CUSTOMER_FATIGUE"  # repeated contact/attempt on this customer
    AMOUNT_SENSITIVITY = "AMOUNT_SENSITIVITY"  # cost of being wrong scales with amount
    LOW_SAMPLE_CONFIDENCE = "LOW_SAMPLE_CONFIDENCE"  # thin basis for this reason/context combo
    COMPLIANCE_BOUNDARY = "COMPLIANCE_BOUNDARY"  # close to an attempt/window/contact limit
    AMBIGUOUS_SIGNAL = "AMBIGUOUS_SIGNAL"  # input itself contains conflicting evidence
    OTHER = "OTHER"


class MissingInfoCategory(str, Enum):
    """What the model would have wanted but the input didn't carry. Also closed —
    this is a diagnostic signal for the input pipeline and the human-review queue,
    not a channel for the model to ask for arbitrary data."""

    CUSTOMER_CONTACT_HISTORY = "CUSTOMER_CONTACT_HISTORY"
    PRIOR_METHOD_SUCCESS_RATE = "PRIOR_METHOD_SUCCESS_RATE"
    DOWNTIME_CONFIRMATION = "DOWNTIME_CONFIRMATION"
    ACCOUNT_STANDING = "ACCOUNT_STANDING"
    MERCHANT_RISK_PROFILE = "MERCHANT_RISK_PROFILE"
    OTHER = "OTHER"


class RiskFlag(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: RiskCategory
    note: str = Field(max_length=140)


class ExpectedOutcome(BaseModel):
    """The model's own testable prediction, separate from `confidence`.

    `confidence` is how sure the model is about the *diagnosis* (the classification).
    `probability_of_success` is how likely the model thinks its *proposed action*
    is to actually work — a different axis. A model can be highly confident this is
    TRANSIENT_INFRA while still estimating only even odds that one retry clears it.
    Recorded so it becomes checkable against real outcomes later (Phase 3
    calibration) — never gated on directly (invariant 5 covers `confidence`;
    the same discipline applies here by extension).
    """

    model_config = ConfigDict(frozen=True)

    probability_of_success: float = Field(ge=0.0, le=1.0)
    horizon_minutes: int = Field(ge=0)  # by when the outcome should be observable


class DiagnosisProposal(BaseModel):
    """AI-1 output. A proposal, never an authorization.

    `confidence` here is the raw model-reported value. Invariant 5: it never gates.
    Policy consumes `calibrated_confidence`, which Phase 3 fits; until then the
    calibrator is identity and is labelled as such in the report.

    `evidence`, `risks`, and `missing_information` have no default — every response
    must state them explicitly, even as an empty list, rather than silently omit
    them. A required-but-possibly-empty field forces the model to engage with the
    question on every call; an optional field with a default lets it go unanswered
    without anyone noticing.

    `proposed_action` is a closed three-value enum, never a free string — there is
    no execution-command channel anywhere in this schema. `risks` and
    `missing_information` are closed enums for the same reason: a field a model
    could fill with arbitrary text is a field that could carry an instruction
    through the audit trail undetected.
    """

    model_config = ConfigDict(frozen=True)

    recoverability: Recoverability  # the diagnosis
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]
    proposed_action: Action
    proposed_delay_minutes: int | None = Field(default=None, ge=0)
    expected_outcome: ExpectedOutcome
    risks: list[RiskFlag]
    missing_information: list[MissingInfoCategory]
    rationale: str = Field(max_length=280)
    fallback_tier: int = Field(default=0, ge=0, le=3)  # 0 = model answered first try


def idempotency_key(case_id: str, action: "Action", attempt_no: int) -> str:
    """Stable identity for one logical action.

    Lives here rather than in agent/executors/ so the policy engine can compute a
    prospective key for DUPLICATE_ACTION without importing an executor — policy
    must not depend on the layer it authorizes. The executor imports this same
    function, so there is exactly one definition and the two cannot drift.
    """
    return hashlib.sha256(f"{case_id}:{action.value}:{attempt_no}".encode()).hexdigest()


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
    # Idempotency keys of actions already executed for this case. Supplied by the
    # caller (which owns the database) so DUPLICATE_ACTION can be decided without
    # policy performing I/O. Defaults empty: a caller that doesn't supply it gets
    # no duplicate protection from this layer, which is why the executor keeps its
    # own independent unique-index check rather than trusting policy alone.
    executed_action_keys: frozenset[str] = frozenset()


class Verdict(BaseModel):
    """The only type an executor accepts (invariant 8).

    Every decision carries the four things needed to audit it after the fact:
    which rules fired, why, which policy version produced it, and when it was
    decided. `rules_version` and `decided_at` have no defaults on purpose —
    constructing a Verdict outside the policy engine is then a deliberate act
    that must supply both, rather than something that can happen by accident and
    silently produce an authorization nothing actually authorized.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    decision: Decision
    action: Action
    # Which attempt this verdict authorizes. Set by the policy engine from the
    # case state it evaluated, and binding: the idempotency key derives from THIS
    # number, not from whatever the case row says at dispatch time. Deriving the
    # key from a live read meant one authorization could be executed twice — the
    # first execution incremented `attempts`, so a re-delivery of the same verdict
    # computed a different key and spent again. See DECISIONS.md ADR-018.
    attempt_no: int = Field(ge=1)
    execute_at: datetime | None = None
    fired_rules: list[str] = Field(default_factory=list)
    reason: str = ""
    rules_version: int
    decided_at: datetime

    @property
    def is_executable(self) -> bool:
        return self.decision is Decision.ALLOW and self.action is not Action.STOP

    @property
    def idempotency_key(self) -> str:
        """Pure function of the authorization. Re-delivering the same verdict
        always yields the same key, which is what actually makes at-least-once
        dispatch safe."""
        return idempotency_key(self.case_id, self.action, self.attempt_no)


class ExecutionMode(str, Enum):
    SIM = "SIM"
    LIVE = "LIVE"
    SHADOW = "SHADOW"


class ActionOutcome(str, Enum):
    """What the action did. Distinct from whether it was *allowed* to run —
    a refusal raises ActionRefused and produces no ActionResult at all, because
    a refused action never ran and must not consume attempt budget."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ActionResult(BaseModel):
    """The typed output of every executable action."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    action: Action
    idempotency_key: str
    outcome: ActionOutcome
    executed_at: datetime
    mode: ExecutionMode = ExecutionMode.SIM
    # True when this call was an idempotent no-op. `outcome` then carries the
    # ORIGINAL attempt's result, not a fresh one — collapsing the two into a
    # single "replayed" outcome would lose whether the first attempt succeeded.
    replayed: bool = False
    detail: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome is ActionOutcome.SUCCEEDED
