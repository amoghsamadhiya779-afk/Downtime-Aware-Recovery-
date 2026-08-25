# Evaluation Report — corpus `dev` seed=42 scenario=S2

n=300 · generator=0.2.0 · times_scored=96 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹5606582.74 per 1,000** (95% CI [2756731.43, 8046312.15], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹7853.67, holdout: ₹2247.09 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 30.4%, holdout: 11.0%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.490** (n=101). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.43 R=0.95 F1=0.59 support=19
  - CUSTOMER_FIXABLE: P=0.43 R=0.48 F1=0.45 support=25
  - INSTRUMENT_INVALID: P=0.57 R=0.29 F1=0.38 support=14
  - TERMINAL: P=0.75 R=0.42 F1=0.54 support=43

## Secondary metrics

- Wasted-attempt rate: 10.9% (18/165 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 44
- Cases abandoned early, zero attempts spent: 62
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **23.6%** (51/216 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- None identified in this run — treat that as a prompt to look harder, not as a clean bill of health.
