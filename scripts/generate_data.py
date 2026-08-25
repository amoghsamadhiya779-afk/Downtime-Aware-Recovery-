"""⚠️  DEPRECATED (ADR-024) — Use `datagen/generate.py` + `scripts/gen.py` instead.

This script was the original standalone JSON dataset generator. It has been
superseded by `datagen/generate.py`, which produces SQLite corpora consumed
directly by the evaluation harness (`evalharness/run.py`). This file is retained
for reference only and will be removed in a future cleanup.

Historical context: This script produced portable JSON files validated against
Pydantic schemas. The canonical pipeline now uses `datagen/generate.py` →
`agent.pipeline.ingest()` → SQLite → `evalharness/run.py` → `eval/report.md`.
"""
import warnings
warnings.warn(
    "scripts/generate_data.py is deprecated (ADR-024). Use 'python scripts/gen.py' instead.",
    DeprecationWarning,
    stacklevel=2,
)

"""Standalone synthetic dataset generator for the approved schema (docs/02 — the
Field | Type | Meaning | Required | Used by table).

Distinct from `datagen/generate.py`: that module feeds the live SQLite pipeline
via `agent.pipeline.ingest()` for evaluation runs and is import-isolated from
`agent/` by design (invariant 7). This script has a different job — produce a
portable, human-inspectable sample dataset as plain JSON files, schema-validated
against the real Pydantic types (`agent.models`, `datagen.schema`) so it can never
drift from the approved schema, without touching the SQLite/audit machinery at all.

Reuses (does not redefine) agent/triage.py's CLEAN/AMBIGUOUS reason vocabulary —
one fact, one home. Everything else here (method-aware reason pools, amount
distribution, customer/mandate repetition, downtime-correlated failure bursts) is
new, local to this script, and does not modify any existing file.

Requirements satisfied:
  - reproducible seed        -> every draw is a pure function of --seed
  - realistic distributions  -> weighted method mix, log-normal amounts, weighted
                                 per-method failure reasons, business-hours time bias
  - repeated entities        -> skewed repeat-customer pool; a shared mandate pool
                                 where ~40% of mandates carry a realistic multi-attempt
                                 retry sequence instead of one-off records
  - realistic failure patterns -> downtime windows bias nearby same-instrument
                                 failures toward infra-reason codes (the actual
                                 mechanism the product is built to detect), and ~4%
                                 of reasons are genuinely unseen codes, exercising
                                 the fail-closed triage path deliberately
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.models import DowntimeWindow, ErrorObj, Instrument, Method, PaymentFailure, Recoverability
from agent.triage import AMBIGUOUS, CLEAN
from datagen.schema import BatchManifest, GroundTruth

GENERATOR_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Realistic distributions. Authored assumptions for synthetic-data shape, not
# sourced Razorpay statistics — see EVIDENCE.md discipline: nothing here is
# presented as a verified Razorpay figure.
# ---------------------------------------------------------------------------

METHOD_WEIGHTS: dict[Method, float] = {
    Method.UPI: 0.55,
    Method.CARD: 0.22,
    Method.NETBANKING: 0.15,
    Method.EMANDATE: 0.08,
}

INSTRUMENTS: dict[Method, list[Instrument]] = {
    Method.CARD: [
        Instrument(network="visa", type="credit"),
        Instrument(network="visa", type="debit"),
        Instrument(network="mastercard", type="credit"),
        Instrument(network="rupay", type="debit"),
    ],
    Method.NETBANKING: [Instrument(bank="HDFC"), Instrument(bank="SBIN"), Instrument(bank="ICIC"), Instrument(bank="UTIB")],
    Method.UPI: [Instrument(vpa_handle="oksbi"), Instrument(vpa_handle="okhdfcbank"), Instrument(vpa_handle="okicici"), Instrument(vpa_handle="paytm")],
    Method.EMANDATE: [Instrument(bank="HDFC"), Instrument(bank="UTIB"), Instrument(bank="SBIN")],
}

# reason -> relative weight, per method. Only reasons plausible for that method are
# listed (e.g. NPCI-flavoured reasons only appear for UPI/emandate; card-specific
# instrument faults only appear for card). All keys are drawn from agent/triage.py's
# real CLEAN/AMBIGUOUS vocabulary so triage resolves them exactly as it would live.
REASON_WEIGHTS: dict[Method, dict[str, float]] = {
    Method.CARD: {
        "card_expired": 12, "invalid_card_number": 6, "card_blocked": 5,
        "insufficient_funds": 18, "invalid_otp": 10, "otp_attempts_exceeded": 4,
        "fraud_suspected": 3, "international_transaction_not_allowed": 2,
        "gateway_timeout": 8, "server_error": 5, "payment_cancelled_by_user": 6,
        "payment_declined_by_bank": 12, "authentication_failed": 10,
        "transaction_limit_exceeded": 5, "payment_failed": 14,
    },
    Method.NETBANKING: {
        "insufficient_funds": 14, "issuer_down": 10, "account_closed": 3,
        "payment_frozen": 2, "gateway_timeout": 10, "server_error": 8,
        "payment_cancelled_by_user": 8,
        "payment_declined_by_bank": 12, "authentication_failed": 12, "payment_failed": 16,
    },
    Method.UPI: {
        "invalid_vpa": 8, "npci_unavailable": 12, "insufficient_funds": 16,
        "payment_cancelled_by_user": 10, "fraud_suspected": 2,
        "gateway_timeout": 6, "server_error": 4,
        "collect_request_expired": 14, "transaction_limit_exceeded": 6,
        "payment_failed": 18, "payment_declined_by_bank": 8,
    },
    Method.EMANDATE: {
        "mandate_revoked": 8, "account_closed": 3, "insufficient_funds": 22,
        "npci_unavailable": 8, "gateway_timeout": 6,
        "payment_declined_by_bank": 14, "authentication_failed": 6, "payment_failed": 16,
    },
}

# Reason codes deliberately absent from agent/triage.py's vocabulary. A realistic
# taxonomy is never exhaustive (EVIDENCE.md E11) — including a small share of these
# exercises the fail-closed / UNKNOWN path on purpose rather than only in unit tests.
UNSEEN_REASON_RATE = 0.04
UNSEEN_REASONS = ["risk_engine_override_402", "acquirer_code_r17", "processor_maintenance_hold"]

# Infra-flavoured reasons per method — used to bias failures that land inside a
# downtime window toward the failure type that downtime actually causes.
INFRA_REASONS: dict[Method, list[str]] = {
    Method.CARD: ["gateway_timeout", "server_error"],
    Method.NETBANKING: ["issuer_down", "gateway_timeout", "server_error"],
    Method.UPI: ["npci_unavailable", "gateway_timeout", "server_error"],
    Method.EMANDATE: ["npci_unavailable", "gateway_timeout"],
}
DOWNTIME_INFRA_BIAS = 0.70  # P(reason forced to an infra reason | record falls inside a matching window)

RECURRING_RATE: dict[Method, float] = {
    Method.EMANDATE: 0.90,
    Method.UPI: 0.35,
    Method.CARD: 0.15,
    Method.NETBANKING: 0.02,
}

LATENT_CLASS_WEIGHTS: dict[Recoverability, float] = {
    Recoverability.TRANSIENT_INFRA: 0.40,
    Recoverability.CUSTOMER_FIXABLE: 0.30,
    Recoverability.INSTRUMENT_INVALID: 0.15,
    Recoverability.TERMINAL: 0.15,
}


def _weighted_choice(rng: random.Random, weights: dict) -> object:
    keys = list(weights.keys())
    total = sum(weights.values())
    r = rng.uniform(0, total)
    upto = 0.0
    for k in keys:
        upto += weights[k]
        if upto >= r:
            return k
    return keys[-1]


def _amount_paise(rng: random.Random) -> int:
    """Right-skewed: many small failures, a long tail of large ones — real
    transaction-amount distributions are not uniform."""
    rupees = rng.lognormvariate(mu=6.80, sigma=0.9)  # median ~ INR 900
    rupees = min(max(rupees, 10.0), 75_000.0)
    return int(round(rupees)) * 100


def _biased_hour(rng: random.Random) -> int:
    """Weakly business-hours-weighted: real failure volume tracks real transaction
    volume, which is not flat across 24 hours."""
    weights = {h: (3.0 if 9 <= h <= 21 else 1.0) for h in range(24)}
    return int(_weighted_choice(rng, weights))


def _customer_pool(rng: random.Random, n: int) -> tuple[list[str], dict[str, float]]:
    """A skewed pool: a small 'problem customer' segment (repeat card-testers,
    unlucky repeat subscribers) is drawn far more often than the rest — repeat
    entities, weighted the way real customer failure distributions are, not flat."""
    pool_size = max(20, n // 6)
    ids = [f"cust_{i:05d}" for i in range(pool_size)]
    problem_segment = max(1, pool_size // 8)
    weights = {cid: (4.0 if i < problem_segment else 1.0) for i, cid in enumerate(ids)}
    return ids, weights


def _hidden_probs(rng: random.Random, true_class: Recoverability, downtime_active: bool) -> dict[str, float]:
    if true_class is Recoverability.TERMINAL:
        return dict(p_organic=0.0, p_retry_now=0.0, p_retry_after_downtime=0.0)
    if true_class is Recoverability.TRANSIENT_INFRA:
        return dict(
            p_organic=rng.uniform(0.05, 0.15),
            p_retry_now=0.15 if downtime_active else 0.55,
            p_retry_after_downtime=rng.uniform(0.55, 0.75),
        )
    if true_class is Recoverability.CUSTOMER_FIXABLE:
        return dict(
            p_organic=rng.uniform(0.15, 0.30),
            p_retry_now=rng.uniform(0.30, 0.45),
            p_retry_after_downtime=rng.uniform(0.30, 0.45),
        )
    return dict(  # INSTRUMENT_INVALID
        p_organic=rng.uniform(0.02, 0.08),
        p_retry_now=rng.uniform(0.05, 0.15),
        p_retry_after_downtime=rng.uniform(0.05, 0.15),
    )


def _true_class_for(rng: random.Random, reason: str) -> tuple[Recoverability, str]:
    if reason in CLEAN:
        return CLEAN[reason], "CLEAN"
    # AMBIGUOUS or genuinely unseen — both are latent from the triage layer's point
    # of view, and datagen.schema.GroundTruth.ambiguity has no third state for
    # "unseen", so unseen reasons are folded into AMBIGUOUS (they are, if anything,
    # more ambiguous than a recognized-but-overloaded one).
    cls = _weighted_choice(rng, dict(LATENT_CLASS_WEIGHTS))
    return cls, "AMBIGUOUS"  # type: ignore[return-value]


def _make_downtime_windows(rng: random.Random, start: datetime, days: int, n_windows: int) -> list[DowntimeWindow]:
    windows = []
    for i in range(n_windows):
        method = _weighted_choice(rng, dict(METHOD_WEIGHTS))
        instrument = rng.choice(INSTRUMENTS[method])
        begin = start + timedelta(hours=rng.randint(0, 24 * days))
        end = begin + timedelta(hours=rng.randint(1, 4)) if rng.random() < 0.75 else None
        windows.append(
            DowntimeWindow(
                id=f"down_{i:03d}",
                method=method,
                instrument=instrument,
                begin=begin,
                end=end,
                status="started",
                scheduled=rng.random() < 0.25,
                severity=rng.choices(["low", "medium", "high"], weights=[0.3, 0.4, 0.3])[0],
                flow=rng.choice(["collect", "intent", None]) if method is Method.UPI else None,
            )
        )
    return windows


def _active_window(windows: list[DowntimeWindow], method: Method, instrument: Instrument, when: datetime) -> DowntimeWindow | None:
    for w in windows:
        if w.method is method and instrument.matches(w.instrument) and w.begin <= when < (w.end or when + timedelta(days=1)):
            return w
    return None


def generate(
    *,
    seed: int,
    n: int,
    corpus: str,
    scenario_id: str,
    days: int,
    n_downtime_windows: int,
    mandate_sequence_rate: float,
) -> tuple[list[PaymentFailure], list[GroundTruth], list[DowntimeWindow], BatchManifest]:
    """Pure function of its arguments — same seed -> byte-identical output."""
    rng = random.Random(seed)
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)

    windows = _make_downtime_windows(rng, start, days, n_downtime_windows)
    customer_ids, customer_weights = _customer_pool(rng, n)

    # Mandate pool. Each mandate is a FIXED (customer, method, instrument) triple,
    # decided once here — a recurring mandate belongs to exactly one customer in
    # reality, and drawing mandate_id and customer_id independently (an earlier
    # version of this script did) lets two unrelated customers "share" a mandate,
    # which is not a repeated entity, just an ID collision. Binding them at pool
    # creation is what makes every subsequent reuse of a mandate_id realistic.
    # Mandate profiles' method mix is P(method) x P(recurring|method), not
    # P(recurring|method) alone — using RECURRING_RATE alone here would let a
    # rare-but-often-recurring method (emandate) dominate the mandate pool and,
    # through it, the whole corpus's method mix, which drifted emandate to 34% of
    # ALL records in an earlier version of this fix before being caught.
    combined_method_weights = {m: METHOD_WEIGHTS[m] * RECURRING_RATE[m] for m in METHOD_WEIGHTS}
    mandate_share = sum(combined_method_weights.values())  # P(a record is mandate-linked at all)

    n_recurring_estimate = int(n * mandate_share)
    n_mandates = max(8, n_recurring_estimate // 3)
    mandate_profiles = []
    for m in range(n_mandates):
        p_method = _weighted_choice(rng, combined_method_weights)
        p_instrument = rng.choice(INSTRUMENTS[p_method])
        p_customer = rng.choices(customer_ids, weights=[customer_weights[c] for c in customer_ids])[0]
        mandate_profiles.append(dict(
            mandate_id=f"mandate_{m:05d}", method=p_method, instrument=p_instrument, customer_id=p_customer,
        ))

    failures: list[PaymentFailure] = []
    ground_truth: list[GroundTruth] = []

    i = 0
    while len(failures) < n:
        use_mandate = mandate_profiles and rng.random() < mandate_share
        hour = _biased_hour(rng)
        day_offset = rng.randint(0, days - 1)
        base_time = start + timedelta(days=day_offset, hours=hour, minutes=rng.randint(0, 59))

        if use_mandate:
            profile = rng.choice(mandate_profiles)
            method, instrument, customer_id, mandate_id = (
                profile["method"], profile["instrument"], profile["customer_id"], profile["mandate_id"],
            )
            n_attempts = rng.choice([2, 3]) if rng.random() < mandate_sequence_rate else 1
            # Same underlying cause across a sequence — realistic: a mandate
            # failing for insufficient_funds tends to keep failing for the same
            # reason across a short retry window, not a fresh random reason each time.
            seq_reason = (
                rng.choice(UNSEEN_REASONS)
                if rng.random() < UNSEEN_REASON_RATE
                else _weighted_choice(rng, REASON_WEIGHTS[method])
            )
            for attempt_no in range(1, n_attempts + 1):
                if len(failures) >= n:
                    break
                created_at = base_time + timedelta(days=attempt_no - 1)
                reason = seq_reason
                w = _active_window(windows, method, instrument, created_at)
                if w is not None and rng.random() < DOWNTIME_INFRA_BIAS:
                    reason = rng.choice(INFRA_REASONS[method])
                failures.append(_build_failure(rng, i, customer_id, method, instrument, created_at, True, mandate_id, attempt_no, reason))
                ground_truth.append(_build_ground_truth(rng, failures[-1], w is not None))
                i += 1
            continue

        # Non-recurring: one-off checkout or payment-link failure, no mandate.
        method = _weighted_choice(rng, dict(METHOD_WEIGHTS))
        instrument = rng.choice(INSTRUMENTS[method])
        window = _active_window(windows, method, instrument, base_time)
        reason = (
            rng.choice(UNSEEN_REASONS) if rng.random() < UNSEEN_REASON_RATE
            else _weighted_choice(rng, REASON_WEIGHTS[method])
        )
        if window is not None and rng.random() < DOWNTIME_INFRA_BIAS:
            reason = rng.choice(INFRA_REASONS[method])

        customer_id = rng.choices(customer_ids, weights=[customer_weights[c] for c in customer_ids])[0]
        failure = _build_failure(rng, i, customer_id, method, instrument, base_time, False, None, 1, reason)
        failures.append(failure)
        ground_truth.append(_build_ground_truth(rng, failure, window is not None))
        i += 1

    manifest = BatchManifest(
        corpus=corpus,  # type: ignore[arg-type]
        seed=seed,
        scenario_id=scenario_id,
        n=len(failures),
        generator_version=GENERATOR_VERSION,
        times_scored=0,
        created_at=datetime.now(timezone.utc),
    )
    return failures[:n], ground_truth[:n], windows, manifest


def _build_failure(rng, i, customer_id, method, instrument, created_at, is_recurring, mandate_id, attempt_no, reason) -> PaymentFailure:
    return PaymentFailure(
        case_id=f"syn_{i:06d}",
        customer_id=customer_id,
        order_id=f"order_{i:06d}",
        created_at=created_at,
        method=method,
        instrument=instrument,
        amount_paise=_amount_paise(rng),  # drawn from the single seeded rng — reproducible by construction
        is_recurring=is_recurring,
        mandate_id=mandate_id,
        attempt_no=attempt_no,
        error=ErrorObj(
            code="BAD_REQUEST_ERROR" if reason in AMBIGUOUS else "GATEWAY_ERROR",
            source="gateway" if reason in AMBIGUOUS else "customer",
            step="payment_authorization",
            reason=reason,
            description=reason.replace("_", " "),
        ),
    )


def _build_ground_truth(rng: random.Random, pf: PaymentFailure, downtime_active: bool) -> GroundTruth:
    true_class, ambiguity = _true_class_for(rng, pf.error.reason)
    probs = _hidden_probs(rng, true_class, downtime_active)
    return GroundTruth(
        case_id=pf.case_id,
        true_class=true_class,
        ambiguity=ambiguity,  # type: ignore[arg-type]
        p_organic=probs["p_organic"],
        p_retry_now=probs["p_retry_now"],
        p_retry_after_downtime=probs["p_retry_after_downtime"],
        max_recoverable=probs["p_retry_after_downtime"] > 0.05 or probs["p_retry_now"] > 0.05,
    )


def _stats(failures: list[PaymentFailure], ground_truth: list[GroundTruth], windows: list[DowntimeWindow]) -> dict:
    from collections import Counter

    customer_counts = Counter(f.customer_id for f in failures)
    mandate_counts = Counter(f.mandate_id for f in failures if f.mandate_id)
    method_counts = Counter(f.method.value for f in failures)
    ambiguity_counts = Counter(g.ambiguity for g in ground_truth)
    unseen = sum(1 for f in failures if f.error.reason not in CLEAN and f.error.reason not in AMBIGUOUS)

    downtime_correlated = 0
    for f in failures:
        if _active_window(windows, f.method, f.instrument, f.created_at) is not None:
            downtime_correlated += 1

    return dict(
        n=len(failures),
        method_mix={k: round(v / len(failures), 3) for k, v in method_counts.items()},
        customers_total=len(customer_counts),
        customers_with_repeat_failures=sum(1 for c in customer_counts.values() if c > 1),
        max_failures_single_customer=max(customer_counts.values()),
        mandates_total=len(mandate_counts),
        mandates_with_multi_attempt_sequence=sum(1 for c in mandate_counts.values() if c > 1),
        ambiguity_mix=dict(ambiguity_counts),
        unseen_reason_count=unseen,
        downtime_correlated_failures=downtime_correlated,
        downtime_windows=len(windows),
    )


def write(out_dir: Path, failures, ground_truth, windows, manifest) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "payment_failures.json").write_text(
        json.dumps([json.loads(f.model_dump_json()) for f in failures], indent=2), encoding="utf-8"
    )
    (out_dir / "downtime_windows.json").write_text(
        json.dumps([json.loads(w.model_dump_json()) for w in windows], indent=2), encoding="utf-8"
    )
    # Hidden ground truth: separate file, clearly labelled, never read by agent/.
    (out_dir / "ground_truth.HIDDEN.json").write_text(
        json.dumps([json.loads(g.model_dump_json()) for g in ground_truth], indent=2), encoding="utf-8"
    )

    stats = _stats(failures, ground_truth, windows)
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--corpus", choices=["dev", "calibration", "test"], default="dev")
    ap.add_argument("--scenario", default="S1")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--downtime-windows", type=int, default=6)
    ap.add_argument("--mandate-sequence-rate", type=float, default=0.40)
    ap.add_argument("--out", default="data/synthetic")
    args = ap.parse_args()

    failures, ground_truth, windows, manifest = generate(
        seed=args.seed,
        n=args.n,
        corpus=args.corpus,
        scenario_id=args.scenario,
        days=args.days,
        n_downtime_windows=args.downtime_windows,
        mandate_sequence_rate=args.mandate_sequence_rate,
    )
    stats = write(Path(args.out), failures, ground_truth, windows, manifest)

    print(f"generated {stats['n']} PaymentFailure records (seed={args.seed}) -> {args.out}/")
    print(f"  method mix: {stats['method_mix']}")
    print(f"  customers: {stats['customers_total']} total, {stats['customers_with_repeat_failures']} with repeat failures (max {stats['max_failures_single_customer']})")
    print(f"  mandates: {stats['mandates_total']} total, {stats['mandates_with_multi_attempt_sequence']} carrying a multi-attempt sequence")
    print(f"  ambiguity mix: {stats['ambiguity_mix']}  (unseen-reason records: {stats['unseen_reason_count']})")
    print(f"  downtime windows: {stats['downtime_windows']}, {stats['downtime_correlated_failures']} failures fall inside one")
    print(f"  hidden ground truth -> {args.out}/ground_truth.HIDDEN.json (never read by agent/)")


if __name__ == "__main__":
    main()
