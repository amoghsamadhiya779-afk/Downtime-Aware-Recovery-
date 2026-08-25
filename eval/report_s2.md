# Evaluation Report — corpus `dev` seed=42 scenario=S2

n=300 · generator=0.2.0 · times_scored=83 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹4417663.26 per 1,000** (95% CI [1609172.48, 6800593.48], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹6641.38, holdout: ₹2223.71 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 27.3%, holdout: 9.6%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.519** (n=99). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.35 R=1.00 F1=0.52 support=17
  - CUSTOMER_FIXABLE: P=0.62 R=0.54 F1=0.58 support=24
  - INSTRUMENT_INVALID: P=0.75 R=0.23 F1=0.35 support=13
  - TERMINAL: P=0.88 R=0.49 F1=0.63 support=45

## Secondary metrics

- Wasted-attempt rate: 11.0% (18/164 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 51
- Cases abandoned early, zero attempts spent: 63
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **23.7%** (51/215 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- None identified in this run — treat that as a prompt to look harder, not as a clean bill of health.
