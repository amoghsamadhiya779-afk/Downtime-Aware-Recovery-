<!-- last_verified: 2026-08-25 -->

# Pre-Registration

Written **before** the sealed test corpus (C, n=1,000) exists. This is what
pre-registration means: a commitment made before the numbers can bias it. Written
after seeing results is not pre-registration — it's narration.

## Primary KPI (locked)

**Incremental ₹ recovered per 1,000 at-risk**, vs. randomized holdout:

```
(Σ₹ᵗ/nᵗ − Σ₹ʰ/nʰ) × 1000
```

Success threshold: **95% bootstrap CI lower bound > 0** on scenario S1 (realistic
downtime rate). 10,000 resamples on corpus C. Gross recovery rate is printed beside
incremental in every report — never alone.

## Corpora (locked)

| Corpus | n | Purpose | Scoring discipline |
|---|---|---|---|
| A — dev | 300 | Prompt/rule iteration | Burn freely |
| B — calibration | 500 | Fit the confidence calibrator | Never scored for headline |
| **C — test** | **1,000** | The headline | **Sealed. Scored once. `times_scored` published.** |

Power: at 25% holdout and ~30% baseline recovery (E22 — assumption), MDE ≈ 10pp at
80% power, α=0.05. A smaller true effect will not be distinguishable at this n, and
the report says so rather than implying precision the design can't deliver.

## Secondary metrics (locked)

Wasted-attempt rate, attempts/recovery, contacts/₹, achieved-vs-ceiling — all
reported, none are the headline.

## AI quality (locked)

**Ambiguous macro-F1** is the headline diagnosis number — scored on the AMBIGUOUS
subset only. Overall accuracy across all cases is computed but never quoted as a
system result; it's inflated by the CLEAN majority that never reaches the model.
ECE and Brier, raw vs. calibrated, reported once the calibrator exists (Phase 3).

## Safety invariants (locked, build-breaking)

Holdout contamination = 0. Attempt-cap breaches = 0. Quiet-hours violations = 0
(once `QUIET_HOURS` is enabled). Fail-open incidents = 0. Audit chain verifies.
Policy veto rate in **[0.05, 0.40]** — near 0 means the gate is decorative, near 1
means the model is useless. Adversarial damage bound: worst-case wasted spend under
a model forced to `RETRY, confidence 1.0` stays bounded — see `tests/test_adversarial.py`.

## Baselines (locked, both required)

- **B0** — holdout / no action: is any of this incremental?
- **B1** — naive fixed T+1/T+2/T+3 (mirrors Razorpay's shipped Subscriptions
  behaviour, E5): do we beat the incumbent?

## Ablations (locked)

A0 = B1 (incumbent) · A1 = rules-only, LLM disabled · A2 = no-downtime, rule
`DOWNTIME_DEFER` off · A3 = full system.

`A3 − A2` = value of the downtime mechanism. `A3 − A1` = **value of the LLM**. If
`A3 − A1` is not statistically significant, the README states plainly that the LLM
is not earning its place. This harness is built to surface that conclusion, not
avoid it.

**S3 — negative control** (locked): with no downtime present in the corpus, the
downtime mechanism must show ≈0 lift. Lift there means a bug, not a feature.
Published either way.

## Failure injection (locked)

F1 timeout · F2 malformed JSON · **F3 adversarial model** (built and passing —
`tests/test_adversarial.py`) · F4 5xx/429 · F5 sustained outage/circuit breaker ·
F6 delayed downtime signal · F7 inverted downtime signal · F8 duplicate webhook
storm · F9 kill switch mid-batch.

## Anti-cherry-picking mechanisms (locked)

1. This file, hash-committed before corpus C is scored.
2. Sealed test set; `times_scored` published in every report referencing it.
3. The report generator refuses to emit a partial report — omitting a required
   scenario or ablation arm is a build failure, not a choice.
4. No hand-written numbers in the README — CI greps for numerics absent from the
   generated `eval/report.md`.
5. **Mandatory, non-empty adverse-findings section.** Already exercised on the
   Phase 1 dev corpus: it caught and disclosed two genuine issues (a placeholder
   diagnosis component scoring below random-guess baseline, and zero downtime
   overlap at the default rate) on the very first real run. See `STATE.md`.
6. Gross always printed beside incremental, never alone.
7. CIs on every point estimate.
8. Sensitivity sweep reports the *fraction of the parameter grid* where the
   conclusion survives — not a single favorable point.
9. S3 negative control published whether or not it behaves.
10. Full reproduction from a committed seed. Confirmed for the Phase 1 dev corpus
    this session: `make gen && make eval` run twice, diffed, byte-identical.

## Status

Phase 1 implements the primary KPI, safety invariants, and F3 against the **dev
corpus (A, n=300)** only. Corpus C does not exist yet — nothing has been sealed or
scored against it. Ablations, S3, the sensitivity sweep, and calibration are Phase 3
work, tracked in `STATE.md`.
