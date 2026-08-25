# Evaluation Report — corpus `dev` seed=42 scenario=S3

n=300 · generator=0.2.0 · times_scored=92 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹5263875.88 per 1,000** (95% CI [3289488.59, 7176685.63], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹6180.06, holdout: ₹916.18 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 22.9%, holdout: 5.5%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.355** (n=99). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.00 R=0.00 F1=0.00 support=0
  - CUSTOMER_FIXABLE: P=0.47 R=0.62 F1=0.54 support=29
  - INSTRUMENT_INVALID: P=0.71 R=0.25 F1=0.37 support=20
  - TERMINAL: P=0.79 R=0.38 F1=0.51 support=50

## Secondary metrics

- Wasted-attempt rate: 14.2% (24/169 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 58
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **23.9%** (53/222 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.
