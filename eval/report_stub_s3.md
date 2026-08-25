# Evaluation Report — corpus `dev` seed=42 scenario=S3

n=300 · generator=0.2.0 · times_scored=36 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹4031157.24 per 1,000** (95% CI [1794659.45, 6175156.78], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹5697.96, holdout: ₹1666.80 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 23.3%, holdout: 8.2%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.369** (n=99). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.00 R=0.00 F1=0.00 support=0
  - CUSTOMER_FIXABLE: P=0.68 R=0.53 F1=0.60 support=32
  - INSTRUMENT_INVALID: P=1.00 R=0.13 F1=0.24 support=15
  - TERMINAL: P=0.84 R=0.52 F1=0.64 support=52

## Secondary metrics

- Wasted-attempt rate: 14.5% (24/165 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 62
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **22.5%** (48/213 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.
