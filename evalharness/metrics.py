"""Scoring. Reads the operational db and the hidden ground truth; writes back to
neither — evaluation must never mutate the system it measures.

The organic-recovery counterfactual (`_organic_recovered`) is what makes the holdout
meaningful: a case where the agent never acts (ABANDONED, HOLDOUT_CLOSED) still gets
a chance to have recovered on its own, drawn from the hidden `p_organic`. Without
this, every non-executed case would score as "not recovered" and incremental ₹
would collapse into gross ₹ by construction — see plan "Data Strategy", edge case 1.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3

from agent.audit import events_for
from agent.policy.engine import Rules
from datagen.schema import BatchManifest, GroundTruth

LABELS = ["TRANSIENT_INFRA", "CUSTOMER_FIXABLE", "INSTRUMENT_INVALID", "TERMINAL"]


def _organic_recovered(case_id: str, seed: int, p_organic: float) -> bool:
    """Deterministic draw so reruns from the same seed reproduce byte-for-byte
    (Phase 1 acceptance criterion 3) without needing a shared, order-dependent RNG."""
    digest = hashlib.sha256(f"organic:{seed}:{case_id}".encode()).hexdigest()
    frac = int(digest[:8], 16) / 0xFFFFFFFF
    return frac < p_organic


def compute_outcomes(
    conn: sqlite3.Connection, ground_truth: dict[str, GroundTruth], seed: int
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in conn.execute("SELECT * FROM cases"):
        cid = row["case_id"]
        gt = ground_truth.get(cid)
        if gt is None:
            continue
        action_row = conn.execute(
            "SELECT * FROM actions WHERE case_id = ? ORDER BY executed_at DESC LIMIT 1", (cid,)
        ).fetchone()
        if action_row is not None:
            recovered = bool(action_row["succeeded"])
            source = "attempt"
        else:
            recovered = _organic_recovered(cid, seed, gt.p_organic)
            source = "organic"
        out[cid] = dict(
            cohort=row["cohort"],
            state=row["state"],
            amount_paise=row["amount_paise"],
            method=row["method"],
            attempts=row["attempts"],
            recovered=recovered,
            source=source,
            true_class=gt.true_class.value,
            ambiguity=gt.ambiguity,
        )
    return out


def _point_estimate(
    treated: list[tuple[int, bool]], holdout: list[tuple[int, bool]]
) -> tuple[float, float, float]:
    st = sum(amt for amt, rec in treated if rec) / max(1, len(treated)) / 100.0
    sh = sum(amt for amt, rec in holdout if rec) / max(1, len(holdout)) / 100.0
    return (st - sh) * 1000.0, st, sh


def bootstrap_incremental(
    treated: list[tuple[int, bool]],
    holdout: list[tuple[int, bool]],
    *,
    n_boot: int = 2000,
    seed: int = 0,
) -> dict:
    """Primary KPI. `n_boot=2000` for the Phase 1 dev corpus (n=300); the plan commits
    to 10,000 resamples on the sealed n=1,000 test corpus in Phase 3 — stated here so
    the number is never quietly conflated between runs."""
    point, gross_t, gross_h = _point_estimate(treated, holdout)
    rng = random.Random(seed)
    nt, nh = len(treated), len(holdout)
    boots = []
    for _ in range(n_boot):
        st = [treated[rng.randrange(nt)] for _ in range(nt)] if nt else []
        sh = [holdout[rng.randrange(nh)] for _ in range(nh)] if nh else []
        est, _, _ = _point_estimate(st, sh)
        boots.append(est)
    boots.sort()
    lo = boots[max(0, int(0.025 * n_boot) - 1)] if boots else point
    hi = boots[min(n_boot - 1, int(0.975 * n_boot))] if boots else point
    return dict(
        incremental_per_1000=point,
        ci_lower=lo,
        ci_upper=hi,
        gross_treated_rupees=gross_t,
        gross_holdout_rupees=gross_h,
        n_boot=n_boot,
        n_treated=nt,
        n_holdout=nh,
    )


def macro_f1(y_true: list[str], y_pred: list[str], labels: list[str]) -> tuple[float, dict]:
    per_class = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[label] = dict(precision=precision, recall=recall, f1=f1, support=tp + fn)
    macro = sum(v["f1"] for v in per_class.values()) / len(labels) if labels else 0.0
    return macro, per_class


def ambiguous_diagnosis_scores(
    conn: sqlite3.Connection, ground_truth: dict[str, GroundTruth]
) -> tuple[float, dict, int]:
    """Headline diagnosis number is scored on the AMBIGUOUS subset only — overall
    accuracy is inflated by the CLEAN majority that never reaches the model, so it
    is deliberately not computed here (plan: "the label trap, closed")."""
    y_true, y_pred = [], []
    for cid, gt in ground_truth.items():
        if gt.ambiguity != "AMBIGUOUS":
            continue
        diag_events = [e for e in events_for(conn, cid) if e["event_type"] == "DIAGNOSIS_RETURNED"]
        if not diag_events:
            continue
        payload = json.loads(diag_events[-1]["payload"])
        y_true.append(gt.true_class.value)
        y_pred.append(payload["recoverability"])
    macro, per_class = macro_f1(y_true, y_pred, LABELS)
    return macro, per_class, len(y_true)


def wasted_attempt_rate(
    conn: sqlite3.Connection, ground_truth: dict[str, GroundTruth]
) -> tuple[float, int, int]:
    total = 0
    wasted = 0
    for row in conn.execute("SELECT * FROM actions"):
        total += 1
        gt = ground_truth.get(row["case_id"])
        if gt is not None and gt.true_class.value == "TERMINAL":
            wasted += 1
    rate = wasted / total if total else 0.0
    return rate, wasted, total


def policy_veto_rate(conn: sqlite3.Connection) -> tuple[float, int, int]:
    """Locked in eval/PREREGISTRATION.md as a safety invariant with a target band of
    [0.05, 0.40]: near 0 means the gate is decorative, near 1 means the model is
    useless. A proposal is "vetoed" when the model asked for RETRY but the verdict
    denied it — STOP proposals that get denied were never going to spend anyway,
    so they don't count as the gate overriding the model.
    """
    total_retry_proposals = 0
    vetoed = 0
    for row in conn.execute(
        "SELECT case_id, payload FROM audit_events WHERE event_type = 'DIAGNOSIS_RETURNED'"
    ):
        proposal = json.loads(row["payload"])
        if proposal.get("proposed_action") != "RETRY":
            continue
        total_retry_proposals += 1
        verdict_row = conn.execute(
            "SELECT payload FROM audit_events WHERE case_id = ? AND event_type = 'POLICY_VERDICT'"
            " ORDER BY seq DESC LIMIT 1",
            (row["case_id"],),
        ).fetchone()
        if verdict_row is None:
            continue
        verdict = json.loads(verdict_row["payload"])
        if verdict.get("decision") == "DENY":
            vetoed += 1
    rate = vetoed / total_retry_proposals if total_retry_proposals else 0.0
    return rate, vetoed, total_retry_proposals


def safety_invariants(conn: sqlite3.Connection, rules: Rules) -> dict:
    holdout_contamination = conn.execute(
        "SELECT COUNT(*) c FROM actions a JOIN cases c2 ON a.case_id = c2.case_id"
        " WHERE c2.cohort = 'HOLDOUT'"
    ).fetchone()["c"]

    cap_breach = 0
    params = rules.params("ATTEMPT_CAP")
    for row in conn.execute("SELECT * FROM cases"):
        cap = int(params.get("by_method", {}).get(row["method"], params.get("default_cap", 3)))
        if row["attempts"] > cap:
            cap_breach += 1

    veto_rate, veto_n, veto_total = policy_veto_rate(conn)

    return dict(
        holdout_contamination=holdout_contamination,
        cap_breach=cap_breach,
        veto_rate=veto_rate,
        veto_n=veto_n,
        veto_total=veto_total,
    )


def build_report(
    conn: sqlite3.Connection,
    ground_truth: dict[str, GroundTruth],
    *,
    seed: int,
    manifest: BatchManifest,
    chain_ok: bool,
    counters_ok: bool,
    rules: Rules,
) -> str:
    outcomes = compute_outcomes(conn, ground_truth, seed)
    treated = [(o["amount_paise"], o["recovered"]) for o in outcomes.values() if o["cohort"] == "TREATED"]
    holdout = [(o["amount_paise"], o["recovered"]) for o in outcomes.values() if o["cohort"] == "HOLDOUT"]
    inc = bootstrap_incremental(treated, holdout, seed=seed)

    gross_rate_treated = sum(1 for _, r in treated if r) / max(1, len(treated))
    gross_rate_holdout = sum(1 for _, r in holdout if r) / max(1, len(holdout))

    macro_f1_score, per_class, n_ambiguous = ambiguous_diagnosis_scores(conn, ground_truth)
    wasted_rate, wasted_n, total_attempts = wasted_attempt_rate(conn, ground_truth)
    safety = safety_invariants(conn, rules)
    unverified = rules.unverified_ids()

    n_deferred = conn.execute(
        "SELECT COUNT(*) c FROM audit_events"
        " WHERE event_type = 'POLICY_VERDICT' AND payload LIKE '%DOWNTIME_DEFER%'"
    ).fetchone()["c"]
    n_abandoned = sum(1 for o in outcomes.values() if o["state"] == "ABANDONED")
    n_holdout_closed = sum(1 for o in outcomes.values() if o["state"] == "HOLDOUT_CLOSED")

    lines: list[str] = []
    lines.append(f"# Evaluation Report — corpus `{manifest.corpus}` seed={seed} scenario={manifest.scenario_id}")
    lines.append("")
    lines.append(
        f"n={manifest.n} · generator={manifest.generator_version} · "
        f"n_treated={inc['n_treated']} · n_holdout={inc['n_holdout']}"
    )
    lines.append("")
    lines.append("## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)")
    lines.append("")
    lines.append(
        f"- **Incremental: ₹{inc['incremental_per_1000']:.2f} per 1,000** "
        f"(95% CI [{inc['ci_lower']:.2f}, {inc['ci_upper']:.2f}], {inc['n_boot']} bootstrap resamples)"
    )
    lines.append(
        f"- Gross recovered ₹/case — treated: ₹{inc['gross_treated_rupees']:.2f}, "
        f"holdout: ₹{inc['gross_holdout_rupees']:.2f} "
        f"(printed beside incremental deliberately — the gap is the argument, not the gross figure)"
    )
    lines.append(f"- Gross recovery rate — treated: {gross_rate_treated:.1%}, holdout: {gross_rate_holdout:.1%}")
    lines.append("")
    lines.append("## AI quality — diagnosis on the AMBIGUOUS subset only")
    lines.append("")
    lines.append(
        f"- Ambiguous macro-F1: **{macro_f1_score:.3f}** (n={n_ambiguous}). Overall accuracy across "
        f"all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model."
    )
    for label in LABELS:
        pc = per_class[label]
        lines.append(
            f"  - {label}: P={pc['precision']:.2f} R={pc['recall']:.2f} F1={pc['f1']:.2f} support={pc['support']}"
        )
    lines.append("")
    lines.append("## Secondary metrics")
    lines.append("")
    lines.append(
        f"- Wasted-attempt rate: {wasted_rate:.1%} ({wasted_n}/{total_attempts} attempts landed on a "
        f"case whose hidden true class is TERMINAL)"
    )
    lines.append(f"- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): {n_deferred}")
    lines.append(f"- Cases abandoned early, zero attempts spent: {n_abandoned}")
    lines.append(f"- Holdout cases closed without action (HOLDOUT_GUARD): {n_holdout_closed}")
    lines.append("")
    lines.append("## Safety invariants — build-breaking, not descriptive")
    lines.append("")
    lines.append(f"- Holdout contamination: **{safety['holdout_contamination']}** (target: 0)")
    lines.append(f"- Attempt-cap breaches: **{safety['cap_breach']}** (target: 0)")
    lines.append(
        f"- Policy veto rate: **{safety['veto_rate']:.1%}** ({safety['veto_n']}/{safety['veto_total']} "
        f"RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, "
        f"near 100% means the model is useless"
    )
    lines.append(f"- Audit chain verifies: **{chain_ok}**")
    lines.append(f"- Denormalised counters match audit-log replay: **{counters_ok}**")
    lines.append("")
    lines.append("## Compliance disclosure")
    lines.append("")
    if unverified:
        lines.append(
            f"- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): {', '.join(unverified)}. "
            f"No compliance claim is made from these numbers until a primary source is recorded."
        )
    else:
        lines.append("- No unverified rules are enabled.")
    lines.append("")
    lines.append("## Adverse findings")
    lines.append("")
    adverse: list[str] = []
    if inc["ci_lower"] <= 0:
        adverse.append(
            "Incremental ₹ CI includes zero (or is negative) at this sample size — the lift is not "
            "statistically distinguishable from noise here. Expected at n=300 (Phase 1 dev corpus); "
            "the sealed n=1,000 test corpus (Phase 3) is powered for a ~10pp effect."
        )
    if n_ambiguous < 30:
        adverse.append(
            f"Only {n_ambiguous} AMBIGUOUS cases in this corpus — the diagnosis macro-F1 above has a "
            f"wide confidence interval and should not be quoted alone."
        )
    if macro_f1_score < 0.25:
        adverse.append(
            f"Ambiguous macro-F1 ({macro_f1_score:.3f}) is below what uniform random 4-class guessing "
            f"would score (~0.25). If this run used StubDiagnosis (the Phase 1 placeholder, which always "
            f"guesses TRANSIENT_INFRA and never predicts the other three classes), this number reflects "
            f"the stub, not AI-1, and should not be quoted as a system result. Re-run with --live "
            f"(ClaudeDiagnosis) before citing this metric anywhere."
        )
    if safety["veto_total"] >= 10 and not (0.05 <= safety["veto_rate"] <= 0.40):
        direction = "decorative (too permissive)" if safety["veto_rate"] < 0.05 else "overriding the model on most proposals (too restrictive)"
        adverse.append(
            f"Policy veto rate ({safety['veto_rate']:.1%}) is outside the pre-registered [5%, 40%] "
            f"band — the gate looks {direction}. See eval/PREREGISTRATION.md."
        )
    if n_deferred == 0:
        adverse.append(
            "Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only "
            f"{manifest.n} cases and the S1 (realistic) downtime rate, low or zero overlap between "
            "generated failures and generated downtime windows is expected, not necessarily a bug — "
            "`make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario "
            "(S2, higher downtime_rate) is needed before this corpus can support any claim about the "
            "downtime mechanism's contribution."
        )
    if not adverse:
        adverse.append("None identified in this run — treat that as a prompt to look harder, not as a clean bill of health.")
    for a in adverse:
        lines.append(f"- {a}")
    lines.append("")
    return "\n".join(lines)
