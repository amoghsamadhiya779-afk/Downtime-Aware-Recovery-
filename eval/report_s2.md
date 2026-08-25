# Evaluation Report — corpus `dev` seed=42 scenario=S2

n=300 · generator=0.2.0 · times_scored=102 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹3933150.65 per 1,000** (95% CI [817942.08, 6764908.65], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹7355.82, holdout: ₹3422.67 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 27.8%, holdout: 12.3%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.412** (n=103). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.26 R=1.00 F1=0.42 support=15
  - CUSTOMER_FIXABLE: P=0.41 R=0.35 F1=0.38 support=20
  - INSTRUMENT_INVALID: P=0.50 R=0.17 F1=0.25 support=18
  - TERMINAL: P=0.96 R=0.44 F1=0.60 support=50

## Secondary metrics

- Wasted-attempt rate: 13.7% (23/168 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 43
- Cases abandoned early, zero attempts spent: 59
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **22.2%** (48/216 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- None identified in this run — treat that as a prompt to look harder, not as a clean bill of health.
