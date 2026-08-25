# Evaluation Report — corpus `dev` seed=42 scenario=S2

n=300 · generator=0.2.0 · times_scored=91 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹4625413.90 per 1,000** (95% CI [1832521.50, 7103180.75], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹7123.74, holdout: ₹2498.32 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 28.6%, holdout: 9.6%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.546** (n=106). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.47 R=1.00 F1=0.64 support=21
  - CUSTOMER_FIXABLE: P=0.42 R=0.64 F1=0.51 support=22
  - INSTRUMENT_INVALID: P=0.88 R=0.35 F1=0.50 support=20
  - TERMINAL: P=0.85 R=0.40 F1=0.54 support=43

## Secondary metrics

- Wasted-attempt rate: 11.0% (18/164 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 38
- Cases abandoned early, zero attempts spent: 63
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **26.8%** (60/224 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- None identified in this run — treat that as a prompt to look harder, not as a clean bill of health.
