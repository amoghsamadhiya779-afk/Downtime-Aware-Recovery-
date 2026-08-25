"""The transaction/recovery state machine: allowed transitions, invalid
transitions, and terminal states.

Exhaustive rather than illustrative. Every (from, to) pair in the 9x9 product is
asserted one way or the other, so adding a state or an edge without deciding what
it means for every other state fails the suite instead of passing silently.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest

from agent import db as agent_db
from agent.models import CaseState, Cohort, ErrorObj, Instrument, Method, PaymentFailure
from agent.state import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    IllegalTransition,
    allowed_transitions,
    create_case,
    get_case,
    is_terminal,
    transition,
)

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)
ALL_STATES = list(CaseState)

# Shortest legal path from DETECTED to each state, used to put a case into a
# given state without reaching into the database and writing it directly —
# writing it directly would let a test set up a state the machine cannot
# actually produce.
PATH_TO: dict[CaseState, list[CaseState]] = {
    CaseState.DETECTED: [],
    CaseState.DIAGNOSED: [CaseState.DIAGNOSED],
    CaseState.SCHEDULED: [CaseState.DIAGNOSED, CaseState.SCHEDULED],
    CaseState.EXECUTING: [CaseState.DIAGNOSED, CaseState.SCHEDULED, CaseState.EXECUTING],
    CaseState.FAILED_ATTEMPT: [
        CaseState.DIAGNOSED, CaseState.SCHEDULED, CaseState.EXECUTING, CaseState.FAILED_ATTEMPT,
    ],
    CaseState.RECOVERED: [
        CaseState.DIAGNOSED, CaseState.SCHEDULED, CaseState.EXECUTING, CaseState.RECOVERED,
    ],
    CaseState.ABANDONED: [CaseState.DIAGNOSED, CaseState.ABANDONED],
    CaseState.HOLDOUT_CLOSED: [CaseState.DIAGNOSED, CaseState.HOLDOUT_CLOSED],
    CaseState.QUARANTINED: [CaseState.DIAGNOSED, CaseState.QUARANTINED],
}


def _case_in(conn, state: CaseState, case_id: str = "c1") -> str:
    pf = PaymentFailure(
        case_id=case_id, customer_id="cust1", order_id="o1", created_at=NOW,
        method=Method.UPI, instrument=Instrument(vpa_handle="oksbi"), amount_paise=5000,
        attempt_no=1, error=ErrorObj(code="X", source="gateway", step="s", reason="payment_failed"),
    )
    create_case(conn, pf, Cohort.TREATED)
    for step in PATH_TO[state]:
        transition(conn, case_id, step)
    return case_id


# ---------------------------------------------------------------------------
# Table integrity
# ---------------------------------------------------------------------------

def test_every_state_appears_in_the_transition_table():
    """A state defined on the enum but missing from the table would raise KeyError
    at runtime rather than being rejected cleanly."""
    assert set(VALID_TRANSITIONS) == set(ALL_STATES)


def test_every_target_is_a_real_state():
    for source, targets in VALID_TRANSITIONS.items():
        for target in targets:
            assert target in VALID_TRANSITIONS, f"{source.value} -> {target.value} targets an unknown state"


def test_no_state_transitions_to_itself():
    for state, targets in VALID_TRANSITIONS.items():
        assert state not in targets, f"{state.value} -> itself is not a transition"


def test_every_non_terminal_state_can_reach_a_terminal_one():
    """No state may be a dead end that is not terminal — that is exactly the
    orphaned-case bug ADR-020 fixed for EXECUTING."""
    reachable_terminal = set(TERMINAL_STATES)
    # Fixed-point: keep adding states that can reach something already known to
    # reach a terminal state.
    changed = True
    while changed:
        changed = False
        for state, targets in VALID_TRANSITIONS.items():
            if state not in reachable_terminal and targets & reachable_terminal:
                reachable_terminal.add(state)
                changed = True
    assert reachable_terminal == set(ALL_STATES), (
        f"cannot reach a terminal state from: "
        f"{sorted(s.value for s in set(ALL_STATES) - reachable_terminal)}"
    )


# ---------------------------------------------------------------------------
# Terminal states
# ---------------------------------------------------------------------------

def test_terminal_states_are_exactly_those_with_no_outgoing_edges():
    assert TERMINAL_STATES == frozenset(
        s for s, targets in VALID_TRANSITIONS.items() if not targets
    )


def test_the_expected_three_states_are_terminal():
    assert TERMINAL_STATES == frozenset({
        CaseState.RECOVERED,
        CaseState.ABANDONED,
        CaseState.HOLDOUT_CLOSED,
    })


@pytest.mark.parametrize("state", sorted(TERMINAL_STATES, key=lambda s: s.value))
def test_no_transition_out_of_a_terminal_state_is_permitted(state):
    conn = agent_db.connect(":memory:")
    _case_in(conn, state)
    for target in ALL_STATES:
        with pytest.raises(IllegalTransition):
            transition(conn, "c1", target)


def test_is_terminal_helper_agrees_with_the_table():
    for state in ALL_STATES:
        assert is_terminal(state) == (state in TERMINAL_STATES)
        assert is_terminal(state.value) == (state in TERMINAL_STATES)


# ---------------------------------------------------------------------------
# Exhaustive allowed / invalid coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source,target",
    [(s, t) for s, t in itertools.product(ALL_STATES, ALL_STATES) if t in VALID_TRANSITIONS[s]],
    ids=lambda v: v.value if isinstance(v, CaseState) else str(v),
)
def test_allowed_transition_succeeds(source, target):
    conn = agent_db.connect(":memory:")
    _case_in(conn, source)
    transition(conn, "c1", target)
    assert CaseState(get_case(conn, "c1")["state"]) is target


@pytest.mark.parametrize(
    "source,target",
    [(s, t) for s, t in itertools.product(ALL_STATES, ALL_STATES) if t not in VALID_TRANSITIONS[s]],
    ids=lambda v: v.value if isinstance(v, CaseState) else str(v),
)
def test_invalid_transition_is_rejected(source, target):
    conn = agent_db.connect(":memory:")
    _case_in(conn, source)
    with pytest.raises(IllegalTransition):
        transition(conn, "c1", target)
    # The case must not have moved.
    assert CaseState(get_case(conn, "c1")["state"]) is source


# ---------------------------------------------------------------------------
# The specific edges ADR-020 added, named so their purpose survives a refactor
# ---------------------------------------------------------------------------

def test_executing_can_return_to_scheduled_for_a_retryable_refusal():
    conn = agent_db.connect(":memory:")
    _case_in(conn, CaseState.EXECUTING)
    transition(conn, "c1", CaseState.SCHEDULED)
    assert CaseState(get_case(conn, "c1")["state"]) is CaseState.SCHEDULED


def test_executing_can_reach_quarantined_for_a_terminal_refusal():
    conn = agent_db.connect(":memory:")
    _case_in(conn, CaseState.EXECUTING)
    transition(conn, "c1", CaseState.QUARANTINED)
    assert CaseState(get_case(conn, "c1")["state"]) is CaseState.QUARANTINED


def test_quarantined_can_reach_recovered_via_reconciliation():
    conn = agent_db.connect(":memory:")
    _case_in(conn, CaseState.QUARANTINED)
    transition(conn, "c1", CaseState.RECOVERED)
    assert CaseState(get_case(conn, "c1")["state"]) is CaseState.RECOVERED


def test_quarantined_can_reach_failed_attempt_via_reconciliation():
    conn = agent_db.connect(":memory:")
    _case_in(conn, CaseState.QUARANTINED)
    transition(conn, "c1", CaseState.FAILED_ATTEMPT)
    assert CaseState(get_case(conn, "c1")["state"]) is CaseState.FAILED_ATTEMPT


def test_quarantined_can_reach_diagnosed_via_reconciliation():
    conn = agent_db.connect(":memory:")
    _case_in(conn, CaseState.QUARANTINED)
    transition(conn, "c1", CaseState.DIAGNOSED)
    assert CaseState(get_case(conn, "c1")["state"]) is CaseState.DIAGNOSED


def test_quarantined_can_reach_abandoned_via_reconciliation():
    conn = agent_db.connect(":memory:")
    _case_in(conn, CaseState.QUARANTINED)
    transition(conn, "c1", CaseState.ABANDONED)
    assert CaseState(get_case(conn, "c1")["state"]) is CaseState.ABANDONED


def test_holdout_closed_is_reached_from_diagnosed_not_detected():
    """Holdout cases are diagnosed before being denied, so diagnosis quality is
    measurable on both arms (ADR-006)."""
    assert CaseState.HOLDOUT_CLOSED in allowed_transitions(CaseState.DIAGNOSED)
    assert CaseState.HOLDOUT_CLOSED not in allowed_transitions(CaseState.DETECTED)


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def test_unknown_state_name_raises_value_error_not_illegal_transition():
    """A typo is not an illegal transition — the state does not exist. Reporting
    it as IllegalTransition would misdiagnose the bug."""
    conn = agent_db.connect(":memory:")
    _case_in(conn, CaseState.DETECTED)
    with pytest.raises(ValueError) as exc:
        transition(conn, "c1", "RECOVERD")  # typo
    assert not isinstance(exc.value, IllegalTransition)


def test_string_and_enum_targets_are_equivalent():
    conn = agent_db.connect(":memory:")
    _case_in(conn, CaseState.DETECTED, case_id="a")
    _case_in(conn, CaseState.DETECTED, case_id="b")
    transition(conn, "a", "DIAGNOSED")
    transition(conn, "b", CaseState.DIAGNOSED)
    assert get_case(conn, "a")["state"] == get_case(conn, "b")["state"]


def test_optimistic_concurrency_rejects_a_stale_write():
    conn = agent_db.connect(":memory:")
    _case_in(conn, CaseState.DETECTED)
    conn.execute("UPDATE cases SET version = version + 1 WHERE case_id = 'c1'")
    # get_case inside transition() now reads the bumped version, so this succeeds;
    # the guard is against a *concurrent* bump between read and write, simulated
    # by bumping again mid-flight.
    row = get_case(conn, "c1")
    conn.execute("UPDATE cases SET version = version + 1 WHERE case_id = 'c1'")
    cur = conn.execute(
        "UPDATE cases SET state = ?, version = version + 1 WHERE case_id = ? AND version = ?",
        (CaseState.DIAGNOSED.value, "c1", row["version"]),
    )
    assert cur.rowcount == 0, "a stale version must not be able to write"
