# Evaluation Report — corpus `dev` seed=42 scenario=S2

n=300 · generator=0.2.0 · times_scored=99 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹4030216.93 per 1,000** (95% CI [1206626.75, 6602310.92], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹6751.75, holdout: ₹2721.53 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 24.2%, holdout: 11.0%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.498** (n=104). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.43 R=0.91 F1=0.58 support=23
  - CUSTOMER_FIXABLE: P=0.37 R=0.32 F1=0.34 support=22
  - INSTRUMENT_INVALID: P=0.80 R=0.31 F1=0.44 support=13
  - TERMINAL: P=0.77 R=0.52 F1=0.62 support=46

## Secondary metrics

- Wasted-attempt rate: 10.8% (17/157 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 47
- Cases abandoned early, zero attempts spent: 70
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **23.8%** (49/206 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- None identified in this run — treat that as a prompt to look harder, not as a clean bill of health.
