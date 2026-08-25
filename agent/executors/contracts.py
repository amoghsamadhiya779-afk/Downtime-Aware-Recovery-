"""Typed contracts for every executable action.

An "executable action" is one an `ExecutorPort` can actually perform. Today that
is exactly one: `Action.RETRY`. `Action.STOP` is a state transition, never
dispatched to an executor (`Verdict.is_executable` is False for it), and
`Action.RECOVERY_LINK` is a reserved enum member with no implementation anywhere
— it is deliberately given no contract here, because a contract written against
no implementation and no stated requirements is speculation, not specification
(same reasoning as DECISIONS.md ADR-008).

The shape of every action contract:

    Verdict (authorization)  ->  validate  ->  <Action>Input  ->  ActionResult
                                    |
                                    +-- ActionRefused(ActionErrorCode) on failure

The Verdict stays the only type an executor accepts (invariant 8). The per-action
input is *derived* from it under validation rather than replacing it, so the
invariant holds while each action still gets its own typed parameter object.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from agent.models import Action, CaseState, Method, Verdict


class ActionErrorCode(str, Enum):
    """Why an executor refused to perform an action.

    Closed set: an executor must fail with a code a caller can branch on, not a
    bare string. Retryable and terminal codes are separated because a scheduler
    needs to know whether re-delivering the same verdict could ever succeed.
    """

    # --- refusals: the request was never valid, re-delivery will not help ----
    NOT_AUTHORIZED = "NOT_AUTHORIZED"  # verdict is not an executable authorization
    ACTION_MISMATCH = "ACTION_MISMATCH"  # executor does not implement verdict.action
    INVALID_PARAMS = "INVALID_PARAMS"  # derived input failed validation
    UNKNOWN_CASE = "UNKNOWN_CASE"  # case_id has no row
    ILLEGAL_STATE = "ILLEGAL_STATE"  # case is not in a state where acting is legal

    # --- conflict: another dispatch of this same action is already in flight --
    DUPLICATE_IN_FLIGHT = "DUPLICATE_IN_FLIGHT"

    # --- downstream failures: re-delivery is meaningful (Phase 2, live executor)
    PROVIDER_ERROR = "PROVIDER_ERROR"  # transport/5xx — retryable
    PROVIDER_REJECTED = "PROVIDER_REJECTED"  # provider refused — terminal


TERMINAL_ERROR_CODES = frozenset(
    {
        ActionErrorCode.NOT_AUTHORIZED,
        ActionErrorCode.ACTION_MISMATCH,
        ActionErrorCode.INVALID_PARAMS,
        ActionErrorCode.UNKNOWN_CASE,
        ActionErrorCode.ILLEGAL_STATE,
        ActionErrorCode.PROVIDER_REJECTED,
    }
)

# States in which dispatching an action is legal. The pipeline moves a case to
# EXECUTING immediately before calling the executor; a scheduler dispatching
# directly would hand one over in SCHEDULED. Anything else — DETECTED (never
# authorized), DIAGNOSED (authorized but not dispatched), or any terminal state —
# means the case moved on and this command is stale.
#
# The policy engine's REQUIRED_STATE rule checks state at *authorization* time.
# This is the independent check at *execution* time, because time passes in
# between: a case can reach a terminal state after a verdict is issued but before
# it is dispatched, and an executor that trusts the authorization to still be
# current has no way to notice.
EXECUTABLE_CASE_STATES = frozenset({CaseState.SCHEDULED, CaseState.EXECUTING})


def check_executable_state(state: CaseState) -> None:
    """Raise if the case is not in a state where performing an action is legal."""
    if state not in EXECUTABLE_CASE_STATES:
        raise ActionRefused(
            ActionErrorCode.ILLEGAL_STATE,
            f"case state {state.value} is not one of "
            f"{sorted(s.value for s in EXECUTABLE_CASE_STATES)}",
        )


class ActionRefused(RuntimeError):
    """Raised instead of a bare ValueError so a caller can branch on `code`.

    Refusal is not the same as a failed attempt: a refused action never ran, so
    it must not consume attempt budget. A `FAILED` ActionResult did run and did.
    """

    def __init__(self, code: ActionErrorCode, detail: str = "") -> None:
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = detail

    @property
    def retryable(self) -> bool:
        return self.code not in TERMINAL_ERROR_CODES


class UncertaintyCode(str, Enum):
    """Why an execution outcome is unknown.

    Distinct from ActionErrorCode: a refusal means nothing ran, an uncertain
    outcome means the action was dispatched but we cannot determine the result.
    Blindly retrying is unsafe — reconciliation is the only safe path.
    """

    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"  # deadline exceeded waiting for provider
    STATUS_UNKNOWN = "STATUS_UNKNOWN"  # provider responded but outcome indeterminate


class ExecutionUncertain(RuntimeError):
    """Raised when an action was dispatched but the outcome is unknown.

    This is NOT an ActionRefused (nothing ran) and NOT an ActionResult (something
    definitively ran). The case must be quarantined for reconciliation — never
    blindly retried.

    Why a separate type: ActionRefused carries the invariant "no attempt was
    consumed", and ActionResult carries "an attempt was consumed". An uncertain
    outcome violates both invariants, so representing it as either would corrupt
    the attempt-count replay.
    """

    def __init__(
        self, code: UncertaintyCode, detail: str = "", *, idempotency_key: str = ""
    ) -> None:
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = detail
        self.idempotency_key = idempotency_key


class RetryInput(BaseModel):
    """Validated parameters for Action.RETRY.

    `attempt_no` comes from the Verdict, never from a live database read: it is
    the attempt the policy engine *authorized*, and binding it here is what makes
    the idempotency key a pure function of the authorization rather than of
    whatever the case row happens to say at dispatch time.

    `order_id`, `method` and `amount_paise` are carried because performing a real
    retry against Razorpay needs them (Phase 2). The simulated executor ignores
    them; the contract describes the action, not the current stub.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(min_length=1)
    attempt_no: int = Field(ge=1)
    execute_at: datetime
    order_id: str = Field(min_length=1)
    method: Method
    amount_paise: int = Field(gt=0)

    @property
    def idempotency_key(self) -> str:
        from agent.models import idempotency_key

        return idempotency_key(self.case_id, Action.RETRY, self.attempt_no)


def build_retry_input(verdict: Verdict, *, order_id: str, method: Method, amount_paise: int) -> RetryInput:
    """Verdict -> validated RetryInput, or ActionRefused with a typed code.

    Every precondition an executor needs is checked here, once, so no executor
    has to re-derive them and none can skip them by accident.
    """
    if not verdict.is_executable:
        raise ActionRefused(
            ActionErrorCode.NOT_AUTHORIZED,
            f"decision={verdict.decision.value} action={verdict.action.value}",
        )
    if verdict.action is not Action.RETRY:
        raise ActionRefused(
            ActionErrorCode.ACTION_MISMATCH,
            f"expected RETRY, got {verdict.action.value}",
        )
    if verdict.execute_at is None:
        raise ActionRefused(ActionErrorCode.INVALID_PARAMS, "execute_at is required for RETRY")

    try:
        return RetryInput(
            case_id=verdict.case_id,
            attempt_no=verdict.attempt_no,
            execute_at=verdict.execute_at,
            order_id=order_id,
            method=method,
            amount_paise=amount_paise,
        )
    except Exception as e:  # pydantic ValidationError, or anything it wraps
        raise ActionRefused(ActionErrorCode.INVALID_PARAMS, str(e)) from e
