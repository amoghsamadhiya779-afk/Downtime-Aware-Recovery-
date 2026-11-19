# Evaluation Report — corpus `dev` seed=42 scenario=S3

n=300 · generator=0.2.0 · times_scored=110 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹2691280.93 per 1,000** (95% CI [-88507.71, 5316756.07], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹5095.09, holdout: ₹2403.81 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 18.9%, holdout: 8.2%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.308** (n=102). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.04 R=1.00 F1=0.08 support=2
  - CUSTOMER_FIXABLE: P=0.43 R=0.37 F1=0.40 support=27
  - INSTRUMENT_INVALID: P=0.50 R=0.16 F1=0.24 support=19
  - TERMINAL: P=0.83 R=0.37 F1=0.51 support=54

## Secondary metrics

- Wasted-attempt rate: 12.7% (21/165 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 62
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **25.7%** (57/222 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Incremental ₹ CI includes zero (or is negative) at this sample size — the lift is not statistically distinguishable from noise here. Expected at n=300 (Phase 1 dev corpus); the sealed n=1,000 test corpus (Phase 3) is powered for a ~10pp effect.
- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.
