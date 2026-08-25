# Evaluation Report — corpus `dev` seed=42 scenario=S2

n=300 · generator=0.2.0 · times_scored=14 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹5290491.68 per 1,000** (95% CI [2473392.08, 7959612.52], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹7624.08, holdout: ₹2333.59 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 27.3%, holdout: 8.2%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.602** (n=96). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.46 R=1.00 F1=0.63 support=21
  - CUSTOMER_FIXABLE: P=0.77 R=0.72 F1=0.74 support=32
  - INSTRUMENT_INVALID: P=0.60 R=0.33 F1=0.43 support=9
  - TERMINAL: P=1.00 R=0.44 F1=0.61 support=34

## Secondary metrics

- Wasted-attempt rate: 7.7% (13/168 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 51
- Cases abandoned early, zero attempts spent: 59
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **26.6%** (61/229 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- None identified in this run — treat that as a prompt to look harder, not as a clean bill of health.
