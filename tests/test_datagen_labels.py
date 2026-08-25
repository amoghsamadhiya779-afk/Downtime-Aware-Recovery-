"""Tests for feature-conditioned synthetic ground truth labels (ADR-021).

Asserts structure of the data-generating distribution rather than downstream model outcomes:
1. A reason-only predictor (marginalizing out features) scores macro-F1 < 0.40.
2. A full-information oracle (knowing all generating features) scores macro-F1 > 0.75.
3. AMBIGUOUS label assignment is stochastic categorical sampling, never argmax.
4. Conditioned probability distributions form valid probability simplices.
"""

from __future__ import annotations

import random
from collections import Counter

import pytest
from agent.models import Method, Recoverability
from datagen.generate import (
    GENERATOR_VERSION,
    _AMBIGUOUS_BASE_PRIORS,
    _AMBIGUOUS_REASONS,
    _pick_true_class,
    conditioned_ambiguous_probs,
    generate,
)
from evalharness.metrics import LABELS, macro_f1


def test_generator_version_is_0_2_0():
    assert GENERATOR_VERSION == "0.2.0"


def test_conditioned_probs_form_valid_probability_simplex():
    methods = [Method.CARD, Method.NETBANKING, Method.UPI, Method.EMANDATE]
    reasons = _AMBIGUOUS_REASONS
    amounts = [10_000, 50_000, 500_000, 2_000_000]

    for reason in reasons:
        for method in methods:
            for downtime in (False, True):
                for recurring in (False, True):
                    for amount in amounts:
                        probs = conditioned_ambiguous_probs(
                            reason,
                            downtime_active=downtime,
                            method=method,
                            amount_paise=amount,
                            is_recurring=recurring,
                        )
                        assert len(probs) == 4
                        assert set(probs.keys()) == set(LABELS)
                        for p in probs.values():
                            assert p > 0.0, f"probability {p} not strictly positive"
                        assert sum(probs.values()) == pytest.approx(1.0, rel=1e-5)


def test_draw_is_stochastic_never_argmax():
    """Calling _pick_true_class repeatedly on the same feature set must return
    varying classes according to the distribution, not a single deterministic argmax."""
    rng = random.Random(42)
    classes_drawn = {
        _pick_true_class(
            rng,
            reason="payment_failed",
            ambiguous=True,
            downtime_active=False,
            method=Method.CARD,
            amount_paise=200_000,
            is_recurring=False,
        )
        for _ in range(100)
    }
    # Must draw more than one distinct class
    assert len(classes_drawn) > 1


@pytest.mark.parametrize("seed", [42, 123, 999])
def test_reason_only_below_0_40_and_oracle_above_0_75(seed: int):
    """Structure test:
    - Reason-only predictor (modal true class per reason) must score macro-F1 < 0.40.
    - Full-information oracle (argmax of the generating posterior) must score macro-F1 > 0.75.
    """
    rng = random.Random(seed)
    n_samples = 3000

    methods = [Method.CARD, Method.NETBANKING, Method.UPI, Method.EMANDATE]
    reasons = list(_AMBIGUOUS_BASE_PRIORS.keys())

    samples = []
    for _ in range(n_samples):
        method = rng.choice(methods)
        reason = rng.choice(reasons)
        downtime_active = rng.random() < 0.10
        amount_paise = rng.randint(1_000, 5_000_000)
        is_recurring = rng.random() < 0.30

        probs = conditioned_ambiguous_probs(
            reason,
            downtime_active=downtime_active,
            method=method,
            amount_paise=amount_paise,
            is_recurring=is_recurring,
        )

        classes = list(probs.keys())
        weights = list(probs.values())
        true_class = rng.choices(classes, weights=weights, k=1)[0]
        oracle_pred = max(probs.items(), key=lambda x: x[1])[0]

        samples.append(
            {
                "reason": reason,
                "true_class": true_class.value,
                "oracle_pred": oracle_pred.value,
            }
        )

    y_true = [s["true_class"] for s in samples]
    y_oracle = [s["oracle_pred"] for s in samples]

    # Reason-only predictor: pick empirical mode for each reason
    reason_modes = {}
    for r in reasons:
        r_classes = [s["true_class"] for s in samples if s["reason"] == r]
        reason_modes[r] = Counter(r_classes).most_common(1)[0][0]

    y_reason_only = [reason_modes[s["reason"]] for s in samples]

    f1_reason_only, _ = macro_f1(y_true, y_reason_only, LABELS)
    f1_oracle, _ = macro_f1(y_true, y_oracle, LABELS)

    assert (
        f1_reason_only < 0.40
    ), f"Reason-only predictor scored {f1_reason_only:.4f}, expected < 0.40 (ambiguity ceiling violated)"
    assert (
        f1_oracle > 0.75
    ), f"Full-information oracle scored {f1_oracle:.4f}, expected > 0.75 (insufficient feature signal)"


def test_generate_corpus_structural_invariants():
    """Verify that records produced by generate() maintain feature consistency."""
    records, windows, manifest = generate(seed=42, n=500, corpus="dev", ambiguous_fraction=0.30)
    assert manifest.generator_version == "0.2.0"
    assert len(records) == 500

    ambiguous_records = [r for r in records if r.ground_truth.ambiguity == "AMBIGUOUS"]
    assert len(ambiguous_records) > 0

    for r in records:
        assert r.failure.amount_paise >= 1_000
        assert r.failure.created_at is not None
        if r.failure.is_recurring:
            assert r.failure.mandate_id is not None
        else:
            assert r.failure.mandate_id is None
