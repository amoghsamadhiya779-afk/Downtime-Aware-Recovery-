# Evaluation Report — corpus `dev` seed=42 scenario=S1

n=300 · generator=0.2.0 · times_scored=106 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹1228988.08 per 1,000** (95% CI [-1843087.81, 3960289.74], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹4538.59, holdout: ₹3309.60 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 18.9%, holdout: 11.0%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.381** (n=98). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.00 R=0.00 F1=0.00 support=0
  - CUSTOMER_FIXABLE: P=0.64 R=0.52 F1=0.57 support=31
  - INSTRUMENT_INVALID: P=0.80 R=0.25 F1=0.38 support=16
  - TERMINAL: P=0.85 R=0.43 F1=0.57 support=51

## Secondary metrics

- Wasted-attempt rate: 5.5% (8/146 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 81
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **24.4%** (47/193 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **False**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Incremental ₹ CI includes zero (or is negative) at this sample size — the lift is not statistically distinguishable from noise here. Expected at n=300 (Phase 1 dev corpus); the sealed n=1,000 test corpus (Phase 3) is powered for a ~10pp effect.
- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.
