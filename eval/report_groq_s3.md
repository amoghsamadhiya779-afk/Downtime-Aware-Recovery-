# Evaluation Report — corpus `dev` seed=42 scenario=S3

n=300 · generator=0.2.0 · times_scored=15 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹1374745.97 per 1,000** (95% CI [-2178275.04, 4747247.40], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹5949.05, holdout: ₹4574.30 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 21.6%, holdout: 12.3%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.414** (n=96). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.00 R=0.00 F1=0.00 support=0
  - CUSTOMER_FIXABLE: P=0.81 R=0.66 F1=0.72 support=38
  - INSTRUMENT_INVALID: P=0.50 R=0.18 F1=0.27 support=11
  - TERMINAL: P=0.96 R=0.51 F1=0.67 support=47

## Secondary metrics

- Wasted-attempt rate: 7.2% (12/167 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 60
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **23.4%** (51/218 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Incremental ₹ CI includes zero (or is negative) at this sample size — the lift is not statistically distinguishable from noise here. Expected at n=300 (Phase 1 dev corpus); the sealed n=1,000 test corpus (Phase 3) is powered for a ~10pp effect.
- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.
