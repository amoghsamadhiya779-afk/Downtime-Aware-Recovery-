"""Seeded synthetic corpus generator.

Produces two artefacts that never live in the same file:
  * the OPERATIONAL db  — via agent.pipeline.ingest(), exactly what the agent
    pipeline is allowed to see (same code path a live webhook would use)
  * the HIDDEN ground-truth store (JSONL) — read only by evalharness/

Physical separation, not just an import-lint rule, backs invariant 7.

The CLEAN/AMBIGUOUS split reuses agent/triage.py's own vocabulary, so the data split
and the architecture's Triage/Diagnosis split are the same split (plan "Data
Strategy" — closes the label trap where reason -> class would be deterministic and
the confusion matrix would be theatre).
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.downtime import DowntimeStore
from agent.models import (
    DowntimeWindow,
    ErrorObj,
    Instrument,
    Method,
    PaymentFailure,
    Recoverability,
)
from agent.pipeline import ingest
from agent.policy.engine import Rules
from agent.triage import AMBIGUOUS, CLEAN

from datagen.schema import BatchManifest, GroundTruth

GENERATOR_VERSION = "0.1.0"

METHODS = [Method.CARD, Method.NETBANKING, Method.UPI, Method.EMANDATE]

_INSTRUMENTS: dict[Method, list[Instrument]] = {
    Method.CARD: [
        Instrument(network="visa", type="credit"),
        Instrument(network="mastercard", type="debit"),
    ],
    Method.NETBANKING: [
        Instrument(bank="HDFC"),
        Instrument(bank="SBIN"),
        Instrument(bank="ICIC"),
    ],
    Method.UPI: [Instrument(vpa_handle="oksbi"), Instrument(vpa_handle="okhdfcbank")],
    Method.EMANDATE: [Instrument(bank="HDFC"), Instrument(bank="UTIB")],
}

_CLEAN_REASONS = list(CLEAN.keys())
_AMBIGUOUS_REASONS = list(AMBIGUOUS)


@dataclass
class GeneratedRecord:
    failure: PaymentFailure
    ground_truth: GroundTruth
    downtime_active_at_creation: bool


def _hidden_probs(rng: random.Random, true_class: Recoverability, downtime_active: bool) -> dict[str, float]:
    """The response model (ASSUMPTION — EVIDENCE.md E22). Broad strokes only:
    terminal never recovers; transient infra recovers well once an outage clears
    and poorly while it's ongoing; the other two classes are largely
    downtime-indifferent, which is what makes the downtime mechanism's lift
    isolable rather than confounded with everything else.
    """
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
    # INSTRUMENT_INVALID
    return dict(
        p_organic=rng.uniform(0.02, 0.08),
        p_retry_now=rng.uniform(0.05, 0.15),
        p_retry_after_downtime=rng.uniform(0.05, 0.15),
    )


def _pick_true_class(rng: random.Random, reason: str, ambiguous: bool) -> Recoverability:
    if not ambiguous:
        return CLEAN[reason]
    weights = {
        Recoverability.TRANSIENT_INFRA: 0.40,
        Recoverability.CUSTOMER_FIXABLE: 0.30,
        Recoverability.INSTRUMENT_INVALID: 0.15,
        Recoverability.TERMINAL: 0.15,
    }
    return rng.choices(list(weights), weights=list(weights.values()), k=1)[0]


def generate(
    *,
    seed: int,
    n: int,
    corpus: str,
    scenario_id: str = "S1",
    downtime_rate: float = 0.05,
    ambiguous_fraction: float = 0.30,
    terminal_floor: float = 0.15,
    start: datetime | None = None,
) -> tuple[list[GeneratedRecord], list[DowntimeWindow], BatchManifest]:
    """Pure function of its arguments. Same seed -> byte-identical corpus (acceptance
    criterion 3)."""
    rng = random.Random(seed)
    start = start or datetime(2026, 8, 1, tzinfo=timezone.utc)

    # A handful of downtime windows at roughly the configured affected-record rate
    # (S1 "realistic rate" per the plan; S2 burst uses a higher downtime_rate).
    windows: list[DowntimeWindow] = []
    n_windows = max(1, round(n * downtime_rate / 8))  # ~8 records/window on average
    for i in range(n_windows):
        method = rng.choice(METHODS)
        instrument = rng.choice(_INSTRUMENTS[method])
        begin = start + timedelta(hours=rng.randint(0, 24 * 20))
        end = begin + timedelta(hours=rng.randint(1, 6)) if rng.random() < 0.7 else None
        windows.append(
            DowntimeWindow(
                id=f"down_{corpus}_{seed}_{i:03d}",
                method=method,
                instrument=instrument,
                begin=begin,
                end=end,
                status="started",
                scheduled=rng.random() < 0.3,
                severity=rng.choice(["low", "medium", "high"]),
            )
        )

    records: list[GeneratedRecord] = []
    n_customers = max(1, n // 3)
    for i in range(n):
        case_id = f"{corpus}_{seed}_{i:05d}"
        method = rng.choice(METHODS)
        instrument = rng.choice(_INSTRUMENTS[method])
        ambiguous = rng.random() < ambiguous_fraction
        reason = rng.choice(_AMBIGUOUS_REASONS) if ambiguous else rng.choice(_CLEAN_REASONS)
        true_class = _pick_true_class(rng, reason, ambiguous)

        created_at = start + timedelta(hours=rng.randint(0, 24 * 25), minutes=rng.randint(0, 59))
        downtime_active = any(
            w.method == method
            and instrument.matches(w.instrument)
            and w.begin <= created_at < (w.end or created_at + timedelta(days=1))
            for w in windows
        )

        probs = _hidden_probs(rng, true_class, downtime_active)
        gt = GroundTruth(
            case_id=case_id,
            true_class=true_class,
            ambiguity="AMBIGUOUS" if ambiguous else "CLEAN",
            p_organic=probs["p_organic"],
            p_retry_now=probs["p_retry_now"],
            p_retry_after_downtime=probs["p_retry_after_downtime"],
            max_recoverable=probs["p_retry_after_downtime"] > 0.05 or probs["p_retry_now"] > 0.05,
        )

        is_recurring = rng.random() < 0.3
        pf = PaymentFailure(
            case_id=case_id,
            customer_id=f"cust_{rng.randrange(0, n_customers):05d}",
            order_id=f"order_{i:05d}",
            created_at=created_at,
            method=method,
            instrument=instrument,
            amount_paise=rng.randint(1_000, 5_000_000),
            is_recurring=is_recurring,
            # Was a SECOND, independent `rng.random() < 0.3` draw — two unrelated
            # coin flips meant is_recurring and mandate_id disagreed on ~42% of
            # records (confirmed: 130/300 in the data/dev.db this bug produced).
            # A mandate implies recurring and vice versa; there is no other valid
            # combination.
            mandate_id=f"mandate_{i:05d}" if is_recurring else None,
            attempt_no=1,
            error=ErrorObj(
                code="BAD_REQUEST_ERROR" if ambiguous else "GATEWAY_ERROR",
                source="gateway" if ambiguous else "customer",
                step="payment_authentication",
                reason=reason,
                description=reason.replace("_", " "),
            ),
        )
        records.append(GeneratedRecord(pf, gt, downtime_active))

    manifest = BatchManifest(
        corpus=corpus,  # type: ignore[arg-type]
        seed=seed,
        scenario_id=scenario_id,
        n=n,
        generator_version=GENERATOR_VERSION,
        times_scored=0,
        created_at=datetime.now(timezone.utc),
    )
    return records, windows, manifest


def write_operational_db(
    conn: sqlite3.Connection,
    records: list[GeneratedRecord],
    windows: list[DowntimeWindow],
    seed: int,
    rules: Rules,
) -> None:
    """Routes every record through the real ingest path (agent/pipeline.py) so the
    audit trail starts at SIGNAL_RECEIVED exactly as it would for a live webhook."""
    store = DowntimeStore(conn)
    for w in windows:
        store.add(w)
    for r in records:
        ingest(conn, r.failure, seed, rules, r.failure.created_at)


def write_ground_truth(path: Path, records: list[GeneratedRecord], manifest: BatchManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(manifest.model_dump_json() + "\n")
        for r in records:
            f.write(r.ground_truth.model_dump_json() + "\n")


def read_ground_truth(path: Path) -> tuple[BatchManifest, dict[str, GroundTruth]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    manifest = BatchManifest.model_validate_json(lines[0])
    gt = {}
    for line in lines[1:]:
        g = GroundTruth.model_validate_json(line)
        gt[g.case_id] = g
    return manifest, gt
