"""⚠️  DEPRECATED (ADR-024) — Validation is now handled by `evalharness/run.py`.

This script validated the JSON output of `scripts/generate_data.py`, which is
itself deprecated. The canonical evaluation pipeline (`datagen/generate.py` →
SQLite → `evalharness/run.py`) validates data through Pydantic schema enforcement
at ingest time and safety invariant assertions in the evaluation report. This file
is retained for reference only.
"""
import warnings
warnings.warn(
    "scripts/validate_data.py is deprecated (ADR-024). Use 'python -m evalharness.run' instead.",
    DeprecationWarning,
    stacklevel=2,
)

"""Dataset validator for the output of scripts/generate_data.py.

Re-validates every record against the real Pydantic schema (agent.models,
datagen.schema) rather than hand-rolled field checks — missing/invalid values are
caught by construction, not by a second, driftable copy of the field rules. On top
of that, checks things no single-record schema can express: duplicates, cross-field
and cross-record impossible states, class support, and temporal ordering.

Output discipline: silent on a passing check, always prints summary statistics,
prints only the checks that actually failed. Exit code 1 if any FAIL-severity
finding exists; WARN-severity findings (thin class support) do not fail the run.

Usage:
    python -m scripts.validate_data --dir data/dataset/dev
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from agent.models import DowntimeWindow, Method, PaymentFailure, Recoverability
from agent.triage import AMBIGUOUS, CLEAN
from datagen.schema import BatchManifest, GroundTruth

MIN_CLASS_SUPPORT = 20  # below this, a class's stats are too thin to trust — WARN, not FAIL

# Which Instrument sub-fields are legitimate for each method — used to catch a
# record whose instrument shape doesn't match its method (e.g. a card record
# carrying a vpa_handle).
EXPECTED_INSTRUMENT_FIELDS: dict[Method, set[str]] = {
    Method.CARD: {"network", "type"},
    Method.NETBANKING: {"bank"},
    Method.UPI: {"vpa_handle"},
    Method.EMANDATE: {"bank"},
}
ALL_INSTRUMENT_FIELDS = {"bank", "network", "type", "vpa_handle"}


@dataclass
class Finding:
    category: str
    severity: str  # FAIL | WARN
    message: str
    ref: str = ""


def _load_json(path: Path) -> list[dict] | dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset(directory: Path) -> tuple[list[dict], list[dict], list[dict], dict]:
    failures_raw = _load_json(directory / "payment_failures.json")
    windows_raw = _load_json(directory / "downtime_windows.json")
    ground_truth_raw = _load_json(directory / "ground_truth.HIDDEN.json")
    manifest_raw = _load_json(directory / "manifest.json")
    return failures_raw, windows_raw, ground_truth_raw, manifest_raw


# ---------------------------------------------------------------------------
# Missing / invalid values — delegated to the real schema, not reimplemented.
# ---------------------------------------------------------------------------

def check_schema_validity(model_cls, records: list[dict], id_field: str) -> list[Finding]:
    findings = []
    for rec in records:
        try:
            model_cls.model_validate(rec)
        except ValidationError as e:
            ref = str(rec.get(id_field, "<unknown>"))
            for err in e.errors():
                loc = ".".join(str(p) for p in err["loc"])
                category = "missing_values" if err["type"] == "missing" else "invalid_values"
                findings.append(Finding(category, "FAIL", f"{loc}: {err['msg']}", ref))
    return findings


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------

def check_duplicates(failures: list[dict], windows: list[dict], ground_truth: list[dict]) -> list[Finding]:
    findings = []

    def _dupes(records, key):
        seen = Counter(r[key] for r in records)
        return [k for k, c in seen.items() if c > 1]

    for dupe in _dupes(failures, "case_id"):
        findings.append(Finding("duplicates", "FAIL", f"case_id appears {sum(1 for f in failures if f['case_id']==dupe)}x in payment_failures", dupe))
    for dupe in _dupes(failures, "order_id"):
        findings.append(Finding("duplicates", "FAIL", "duplicate order_id", dupe))
    for dupe in _dupes(ground_truth, "case_id"):
        findings.append(Finding("duplicates", "FAIL", "duplicate case_id in ground_truth", dupe))
    for dupe in _dupes(windows, "id"):
        findings.append(Finding("duplicates", "FAIL", "duplicate downtime window id", dupe))

    return findings


# ---------------------------------------------------------------------------
# Impossible states — cross-field / cross-record invariants no single-record
# schema validator can express.
# ---------------------------------------------------------------------------

def check_impossible_states(failures: list[dict], windows: list[dict], ground_truth: list[dict]) -> list[Finding]:
    findings = []

    failure_ids = {f["case_id"] for f in failures}
    gt_ids = {g["case_id"] for g in ground_truth}
    for orphan in failure_ids - gt_ids:
        findings.append(Finding("impossible_states", "FAIL", "payment_failure has no matching ground_truth record", orphan))
    for orphan in gt_ids - failure_ids:
        findings.append(Finding("impossible_states", "FAIL", "ground_truth record has no matching payment_failure", orphan))

    gt_by_id = {g["case_id"]: g for g in ground_truth}

    for f in failures:
        cid = f["case_id"]
        # mandate_id and is_recurring must agree — a mandate implies recurring and
        # vice versa, by construction of the generator; either without the other
        # is not a state that can occur for a real Razorpay mandate.
        has_mandate = f.get("mandate_id") is not None
        if has_mandate != bool(f.get("is_recurring")):
            findings.append(Finding("impossible_states", "FAIL", f"mandate_id={f.get('mandate_id')!r} but is_recurring={f.get('is_recurring')}", cid))

        # instrument shape must match method (agent/downtime.py's matching logic
        # and the diagnosis prompt both assume this holds).
        method = f.get("method")
        instrument = f.get("instrument") or {}
        present = {k for k in ALL_INSTRUMENT_FIELDS if instrument.get(k) is not None}
        expected = EXPECTED_INSTRUMENT_FIELDS.get(Method(method), set())
        if present and not present.issubset(expected):
            findings.append(Finding("impossible_states", "FAIL", f"instrument fields {present} not valid for method={method}", cid))

        # A CLEAN reason has a deterministic true_class — any deviation means the
        # generator's ground truth disagrees with the triage layer it's meant to
        # be scored against, silently invalidating every downstream metric.
        reason = f.get("error", {}).get("reason")
        gt = gt_by_id.get(cid)
        if gt is not None and reason in CLEAN:
            expected_class = CLEAN[reason].value
            if gt.get("true_class") != expected_class:
                findings.append(Finding("impossible_states", "FAIL", f"reason={reason!r} is CLEAN->{expected_class} but ground_truth.true_class={gt.get('true_class')}", cid))
            if gt.get("ambiguity") != "CLEAN":
                findings.append(Finding("impossible_states", "FAIL", f"reason={reason!r} is CLEAN but ground_truth.ambiguity={gt.get('ambiguity')!r}", cid))
        elif gt is not None and gt.get("ambiguity") != "AMBIGUOUS":
            findings.append(Finding("impossible_states", "FAIL", f"reason={reason!r} is not in CLEAN but ground_truth.ambiguity={gt.get('ambiguity')!r}", cid))

        # TERMINAL is definitionally unrecoverable — any nonzero recovery
        # probability contradicts the class itself.
        if gt is not None and gt.get("true_class") == Recoverability.TERMINAL.value:
            for field in ("p_organic", "p_retry_now", "p_retry_after_downtime"):
                if gt.get(field, 0) != 0:
                    findings.append(Finding("impossible_states", "FAIL", f"true_class=TERMINAL but {field}={gt.get(field)} (must be 0)", cid))

    for w in windows:
        if w.get("end") is not None and w["end"] <= w["begin"]:
            findings.append(Finding("impossible_states", "FAIL", f"end ({w['end']}) is not after begin ({w['begin']})", w["id"]))
        if w.get("flow") is not None and w.get("method") != "upi":
            findings.append(Finding("impossible_states", "FAIL", f"flow={w['flow']!r} set on non-UPI method={w.get('method')}", w["id"]))

    return findings


# ---------------------------------------------------------------------------
# Temporal consistency
# ---------------------------------------------------------------------------

def check_temporal_consistency(failures: list[dict]) -> list[Finding]:
    findings = []

    # A mandate can have several independent failure episodes over time (e.g.
    # insufficient_funds on two separate, unrelated billing cycles) — that's
    # realistic, not corrupt, and an earlier version of this check grouped by
    # (mandate_id, reason) and flagged it as a false positive. The actual
    # invariant is about attempt_no CONTINUITY, not reason matching: within any
    # one episode, chronologically ordered attempt_no must be 1, 2, 3, ... An
    # attempt_no of 1 always starts a fresh episode; anything else must continue
    # some episode currently expecting exactly that number. Tracking multiple
    # concurrently "active" episodes (rather than assuming they never overlap in
    # time) handles interleaved episodes correctly too, not just sequential ones.
    by_mandate: dict[str, list[dict]] = defaultdict(list)
    for f in failures:
        if f.get("mandate_id"):
            by_mandate[f["mandate_id"]].append(f)

    for mandate_id, records in by_mandate.items():
        ordered = sorted(records, key=lambda r: r["created_at"])
        active_runs: list[int] = []  # next attempt_no expected by each in-progress episode
        for r in ordered:
            a = r["attempt_no"]
            if a == 1:
                active_runs.append(2)
                continue
            matched_idx = next((idx for idx, expected in enumerate(active_runs) if expected == a), None)
            if matched_idx is None:
                findings.append(Finding(
                    "temporal_consistency", "FAIL",
                    f"attempt_no={a} does not continue any in-progress episode for this mandate",
                    r["case_id"],
                ))
            else:
                active_runs[matched_idx] = a + 1

    # Loose sanity bound — catches a corrupted or wildly out-of-range timestamp
    # without coupling this validator to one generator's exact date parameters.
    dates = [datetime.fromisoformat(f["created_at"].replace("Z", "+00:00")) for f in failures]
    if dates:
        span_days = (max(dates) - min(dates)).days
        if span_days > 400:
            findings.append(Finding("temporal_consistency", "FAIL", f"record span is {span_days} days — unexpectedly wide for one corpus", ""))
        if min(dates).year < 2020:
            findings.append(Finding("temporal_consistency", "FAIL", f"earliest created_at ({min(dates)}) is implausibly old", ""))

    return findings


# ---------------------------------------------------------------------------
# Class distribution — WARN on thin support, never FAIL (a distribution isn't
# wrong, just potentially too small to trust for a headline metric).
# ---------------------------------------------------------------------------

def check_class_distribution(ground_truth: list[dict]) -> tuple[list[Finding], dict]:
    findings = []
    class_counts = Counter(g["true_class"] for g in ground_truth)
    ambiguity_counts = Counter(g["ambiguity"] for g in ground_truth)

    # UNKNOWN is a diagnosis-output sentinel, never a valid ground-truth true_class
    # (datagen.generate._true_class_for never assigns it) — checking its support
    # would always spuriously WARN "0 support" and isn't a real finding.
    real_classes = [c for c in Recoverability if c is not Recoverability.UNKNOWN]
    for cls in real_classes:
        support = class_counts.get(cls.value, 0)
        if support < MIN_CLASS_SUPPORT:
            findings.append(Finding("class_distribution", "WARN", f"{cls.value} support is {support} (< {MIN_CLASS_SUPPORT}) — too thin to trust in isolation", ""))

    ambiguous_support = ambiguity_counts.get("AMBIGUOUS", 0)
    if ambiguous_support < MIN_CLASS_SUPPORT:
        findings.append(Finding("class_distribution", "WARN", f"AMBIGUOUS support is {ambiguous_support} (< {MIN_CLASS_SUPPORT}) — macro-F1 on this subset will have a wide CI", ""))

    return findings, dict(class_counts=dict(class_counts), ambiguity_counts=dict(ambiguity_counts))


# ---------------------------------------------------------------------------
# Summary statistics — always printed, independent of pass/fail.
# ---------------------------------------------------------------------------

def summary_statistics(failures: list[dict], windows: list[dict], ground_truth: list[dict], manifest: dict) -> dict:
    method_counts = Counter(f["method"] for f in failures)
    n = len(failures)
    customer_counts = Counter(f["customer_id"] for f in failures)
    mandate_counts = Counter(f["mandate_id"] for f in failures if f.get("mandate_id"))
    amounts = sorted(f["amount_paise"] / 100 for f in failures)

    return dict(
        corpus=manifest.get("corpus"),
        seed=manifest.get("seed"),
        generator_version=manifest.get("generator_version"),
        n=n,
        method_mix={k: round(v / n, 3) for k, v in method_counts.items()} if n else {},
        n_downtime_windows=len(windows),
        n_customers=len(customer_counts),
        customers_with_repeat_failures=sum(1 for c in customer_counts.values() if c > 1),
        n_mandates=len(mandate_counts),
        mandates_with_multi_attempt=sum(1 for c in mandate_counts.values() if c > 1),
        amount_rupees=dict(
            min=round(amounts[0], 2), median=round(amounts[len(amounts) // 2], 2),
            p90=round(amounts[int(len(amounts) * 0.9)], 2), max=round(amounts[-1], 2),
        ) if amounts else {},
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def validate(directory: Path) -> tuple[list[Finding], dict]:
    failures_raw, windows_raw, ground_truth_raw, manifest_raw = load_dataset(directory)

    findings: list[Finding] = []
    findings += check_schema_validity(PaymentFailure, failures_raw, "case_id")
    findings += check_schema_validity(DowntimeWindow, windows_raw, "id")
    findings += check_schema_validity(GroundTruth, ground_truth_raw, "case_id")
    findings += check_duplicates(failures_raw, windows_raw, ground_truth_raw)
    findings += check_impossible_states(failures_raw, windows_raw, ground_truth_raw)
    findings += check_temporal_consistency(failures_raw)
    dist_findings, dist_stats = check_class_distribution(ground_truth_raw)
    findings += dist_findings

    stats = summary_statistics(failures_raw, windows_raw, ground_truth_raw, manifest_raw)
    stats.update(dist_stats)
    return findings, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="dataset directory (output of scripts/generate_data.py)")
    args = ap.parse_args()

    findings, stats = validate(Path(args.dir))
    fails = [f for f in findings if f.severity == "FAIL"]
    warns = [f for f in findings if f.severity == "WARN"]

    by_category: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_category[f.category].append(f)

    if findings:
        print(f"# Failed checks — {args.dir}\n")
        for category, items in by_category.items():
            print(f"## {category} ({len(items)})")
            for f in items[:20]:  # cap noisy output; count above is the true total
                ref = f" [{f.ref}]" if f.ref else ""
                print(f"  {f.severity}: {f.message}{ref}")
            if len(items) > 20:
                print(f"  ... and {len(items) - 20} more")
            print()
    else:
        print(f"# All checks passed — {args.dir}\n")

    print("# Summary statistics\n")
    print(json.dumps(stats, indent=2))

    print(f"\n{len(fails)} FAIL, {len(warns)} WARN")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
