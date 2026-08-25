"""The deterministic gate. AI proposes; this disposes.

Hard constraints on this module:
  * no I/O, no database, no network, no filesystem beyond loading rules once
  * no ambient clock — `now` is an argument
  * no model, ever

`tests/test_policy.py` passes with the Anthropic SDK uninstalled. That is the standing
proof the gate is real rather than decorative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from agent.models import (
    Action,
    CaseView,
    Cohort,
    Decision,
    DiagnosisProposal,
    DowntimeContext,
    Verdict,
    idempotency_key,
)

RULES_PATH = Path(__file__).with_name("rules.yaml")


@dataclass(frozen=True)
class Rules:
    version: int
    kill_switch: bool
    holdout_fraction: float
    by_id: dict[str, dict[str, Any]]

    def enabled(self, rule_id: str) -> bool:
        return bool(self.by_id.get(rule_id, {}).get("enabled", False))

    def params(self, rule_id: str) -> dict[str, Any]:
        return self.by_id.get(rule_id, {}).get("params") or {}

    def unverified_ids(self) -> list[str]:
        """Rules whose constants are not backed by a primary source.

        Surfaced in the eval report so no compliance claim can be made by accident.
        """
        return sorted(
            rid
            for rid, r in self.by_id.items()
            if r.get("enabled") and not r.get("verified", False)
        )


def load_rules(path: Path | None = None, *, kill_switch: bool | None = None) -> Rules:
    raw = yaml.safe_load((path or RULES_PATH).read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw["rules"]}
    return Rules(
        version=int(raw["version"]),
        kill_switch=raw["kill_switch"] if kill_switch is None else kill_switch,
        holdout_fraction=float(raw["holdout_fraction"]),
        by_id=by_id,
    )


def _cap_for(rules: Rules, case: CaseView) -> int:
    p = rules.params("ATTEMPT_CAP")
    return int(p.get("by_method", {}).get(case.method.value, p.get("default_cap", 3)))


def evaluate(
    proposal: DiagnosisProposal,
    case: CaseView,
    rules: Rules,
    now: datetime,
    downtime: DowntimeContext,
    *,
    calibrated_confidence: float | None = None,
) -> Verdict:
    """Pure function. First DENY wins; rule order is fixed by rules.yaml.

    Three outcomes only — ALLOW, DENY, REVIEW. "Permitted, but later" is an ALLOW
    carrying a later `execute_at`; there is no separate DEFER decision.

    `calibrated_confidence` is the seam for CLAUDE.md invariant 5: policy must
    never gate on the model's raw self-reported number. Until Phase 3 fits a real
    calibrator the mapping is identity, and the caller passing nothing gets
    `proposal.confidence` — which is honest about the current state rather than
    pretending a calibration step exists that doesn't.
    """
    fired: list[str] = []

    def verdict(decision: Decision, action: Action, reason: str, at: datetime | None = None) -> Verdict:
        return Verdict(
            case_id=case.case_id,
            decision=decision,
            action=action,
            execute_at=at,
            fired_rules=list(fired),
            reason=reason,
            rules_version=rules.version,
            decided_at=now,
        )

    # --- input validity: can this decision be made at all? -------------------

    # 1 — REQUIRED_STATE. A case in a terminal state being submitted for
    # authorization means something upstream is broken; authorizing spend from
    # that position would compound the bug rather than contain it.
    if rules.enabled("REQUIRED_STATE"):
        actionable = set(rules.params("REQUIRED_STATE").get("actionable_states", []))
        if case.state.value not in actionable:
            fired.append("REQUIRED_STATE")
            return verdict(
                Decision.DENY,
                Action.STOP,
                f"case state {case.state.value} is not actionable",
            )

    # 2 — SUPPORTED_ACTION. Action.RECOVERY_LINK is a real, schema-valid enum
    # member reserved for a future phase that nothing implements. Without this,
    # the final `return verdict(..., Action.RETRY, ...)` below is a bare
    # fallthrough for "anything that isn't STOP" and would silently reinterpret an
    # unsupported action as a retry — failing silently wrong, not safely.
    # agent/diagnosis/prompting.py rejects this at the source too; this is the
    # independent second line for any proposal reaching evaluate() another way.
    if rules.enabled("SUPPORTED_ACTION"):
        supported = set(rules.params("SUPPORTED_ACTION").get("supported", []))
        if proposal.proposed_action.value not in supported:
            fired.append("SUPPORTED_ACTION")
            return verdict(
                Decision.DENY,
                Action.STOP,
                f"proposed_action={proposal.proposed_action.value!r} is not implemented",
            )

    # --- operator override ---------------------------------------------------

    # 3 — global halt.
    if rules.kill_switch:
        fired.append("KILL_SWITCH")
        return verdict(Decision.DENY, Action.STOP, "kill switch engaged")

    # --- measurement integrity -----------------------------------------------

    # 4 — unconditional, and deliberately ahead of every business gate: a
    # contaminated holdout invalidates the primary KPI, which is a worse outcome
    # than any single missed recovery.
    if case.cohort is Cohort.HOLDOUT:
        fired.append("HOLDOUT_GUARD")
        return verdict(Decision.DENY, Action.STOP, "holdout arm — never acted upon")

    # --- business gates ------------------------------------------------------

    # 5 — stop early on unrecoverable failures.
    if rules.enabled("TERMINAL_CLASS"):
        deny = set(rules.params("TERMINAL_CLASS").get("deny_classes", []))
        if proposal.recoverability.value in deny:
            fired.append("TERMINAL_CLASS")
            return verdict(
                Decision.DENY,
                Action.STOP,
                f"class {proposal.recoverability.value} is not recoverable",
            )

    # 6 — bounded attempt budget. Confidence-independent by design: a maximally
    # confident wrong model cannot spend past this.
    if rules.enabled("ATTEMPT_CAP"):
        cap = _cap_for(rules, case)
        if case.attempts >= cap:
            fired.append("ATTEMPT_CAP")
            return verdict(Decision.DENY, Action.STOP, f"attempt cap reached ({cap})")

    # 7 — the same logical action must not run twice. The executor keeps its own
    # unique-index check as well; this is the earlier, cheaper refusal that also
    # leaves a policy-level record of why nothing happened.
    if rules.enabled("DUPLICATE_ACTION") and case.executed_action_keys:
        prospective = idempotency_key(case.case_id, proposal.proposed_action, case.attempts + 1)
        if prospective in case.executed_action_keys:
            fired.append("DUPLICATE_ACTION")
            return verdict(
                Decision.DENY,
                Action.STOP,
                f"action already executed for attempt {case.attempts + 1}",
            )

    # Nothing below can turn a STOP proposal into spending.
    if proposal.proposed_action is Action.STOP:
        return verdict(Decision.DENY, Action.STOP, "model proposed STOP")

    # 8 — economic floor. `assumed_success_rate` comes from rules.yaml, NOT from
    # proposal.expected_outcome.probability_of_success: sourcing it from the model
    # would let the model inflate its way past a financial control just by
    # claiming a higher chance of success. The rule is deliberately blind to what
    # the model believes.
    if rules.enabled("EV_FLOOR"):
        ev_params = rules.params("EV_FLOOR")
        cost = int(ev_params.get("action_cost_paise", 0))
        p_assumed = float(ev_params.get("assumed_success_rate", 0.0))
        expected_value = p_assumed * case.amount_paise - cost
        if expected_value <= 0:
            fired.append("EV_FLOOR")
            return verdict(
                Decision.DENY,
                Action.STOP,
                f"expected value {expected_value:.0f} paise does not cover action cost {cost}",
            )

    # 9 — uncertainty routes to a human. Last among the gates: a DENY from any
    # rule above must beat a REVIEW, never the other way round.
    if rules.enabled("CONFIDENCE_FLOOR"):
        floor = float(rules.params("CONFIDENCE_FLOOR").get("min_calibrated_confidence", 0.0))
        confidence = calibrated_confidence if calibrated_confidence is not None else proposal.confidence
        if confidence < floor:
            fired.append("CONFIDENCE_FLOOR")
            return verdict(
                Decision.REVIEW,
                Action.STOP,
                f"calibrated confidence {confidence:.2f} below floor {floor:.2f} — human review",
            )

    # --- timing, not a gate --------------------------------------------------

    dt_params = rules.params("DOWNTIME_DEFER")
    min_delay = int(dt_params.get("min_delay_minutes", 15))
    # proposed_delay_minutes is an LLM-controlled integer with no upper bound in
    # the schema. Unclamped it flows straight into timedelta(), where a large
    # enough value raises OverflowError and takes down the policy function — the
    # model defeating the gate by crashing it rather than by passing it.
    max_delay = int(dt_params.get("max_delay_minutes", 10080))
    delay = min(max(int(proposal.proposed_delay_minutes or 0), min_delay), max_delay)
    execute_at = now + timedelta(minutes=delay)
    reason = "proceed"

    # 10 — downtime-aware timing. Advisory input to *when*, never to *whether*: a
    # wrong or late downtime signal costs latency, never correctness, because
    # every gate above has already bound the decision.
    if rules.enabled("DOWNTIME_DEFER") and downtime.active and downtime.instrument_match:
        jitter = timedelta(seconds=int(dt_params.get("jitter_seconds", 300)))
        if downtime.expected_end is not None:
            candidate = downtime.expected_end + jitter
            candidate_reason = "deferred past downtime end"
        else:
            backoff = int(dt_params.get("unknown_end_backoff_minutes", 90))
            candidate = now + timedelta(minutes=backoff)
            candidate_reason = "downtime end unknown — fixed backoff"
        # Only counts as having fired if it actually changed the outcome. Downtime
        # being active is not the same as downtime changing the schedule — e.g. a
        # proposed delay that already runs past the window's end needs no push.
        # Getting this wrong pollutes the audit trail (a verdict claiming
        # DOWNTIME_DEFER fired when nothing was deferred) and skews eval/run.py's
        # outcome_fn, which keys off fired_rules to pick the response-model branch.
        if candidate > execute_at:
            execute_at = candidate
            reason = candidate_reason
            fired.append("DOWNTIME_DEFER")

    return verdict(Decision.ALLOW, Action.RETRY, reason, execute_at)
