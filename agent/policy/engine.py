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
) -> Verdict:
    """Pure function. First DENY wins; rule order is fixed by rules.yaml.

    DEFER is not a weaker ALLOW — it means "permitted, but not yet", and the returned
    `execute_at` is binding on the scheduler.
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
        )

    # 1 — global halt.
    if rules.kill_switch:
        fired.append("KILL_SWITCH")
        return verdict(Decision.DENY, Action.STOP, "kill switch engaged")

    # 2 — measurement integrity. Unconditional, and deliberately ahead of everything
    # except the halt: a contaminated holdout invalidates the primary KPI, which is
    # a worse outcome than any single missed recovery.
    if case.cohort is Cohort.HOLDOUT:
        fired.append("HOLDOUT_GUARD")
        return verdict(Decision.DENY, Action.STOP, "holdout arm — never acted upon")

    # 3 — stop early on unrecoverable failures.
    if rules.enabled("TERMINAL_CLASS"):
        deny = set(rules.params("TERMINAL_CLASS").get("deny_classes", []))
        if proposal.recoverability.value in deny:
            fired.append("TERMINAL_CLASS")
            return verdict(
                Decision.DENY,
                Action.STOP,
                f"class {proposal.recoverability.value} is not recoverable",
            )

    # 4 — bounded attempt budget. Confidence-independent by design: a maximally
    # confident wrong model cannot spend past this.
    if rules.enabled("ATTEMPT_CAP"):
        cap = _cap_for(rules, case)
        if case.attempts >= cap:
            fired.append("ATTEMPT_CAP")
            return verdict(Decision.DENY, Action.STOP, f"attempt cap reached ({cap})")

    # Nothing below can turn a STOP proposal into spending.
    if proposal.proposed_action is Action.STOP:
        return verdict(Decision.DENY, Action.STOP, "model proposed STOP")

    # Baseline timing: whatever the model asked for, floored at the configured minimum.
    dt_params = rules.params("DOWNTIME_DEFER")
    min_delay = int(dt_params.get("min_delay_minutes", 15))
    delay = max(int(proposal.proposed_delay_minutes or 0), min_delay)
    execute_at = now + timedelta(minutes=delay)
    decision = Decision.ALLOW
    reason = "proceed"

    # 5 — downtime-aware timing. Advisory input to *when*, never to *whether*:
    # a wrong or late downtime signal costs latency, never correctness, because
    # rules 1-4 have already bound the decision.
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
            decision = Decision.DEFER
            reason = candidate_reason
            fired.append("DOWNTIME_DEFER")

    return verdict(decision, Action.RETRY, reason, execute_at)
