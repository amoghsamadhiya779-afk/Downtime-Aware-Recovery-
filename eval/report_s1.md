# Evaluation Report — corpus `dev` seed=42 scenario=S1

n=300 · generator=0.2.0 · times_scored=95 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹4639002.08 per 1,000** (95% CI [2391876.18, 6714510.14], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹6125.58, holdout: ₹1486.58 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 23.3%, holdout: 8.2%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.320** (n=97). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.04 R=0.50 F1=0.07 support=2
  - CUSTOMER_FIXABLE: P=0.41 R=0.50 F1=0.45 support=26
  - INSTRUMENT_INVALID: P=0.40 R=0.11 F1=0.17 support=18
  - TERMINAL: P=0.74 R=0.49 F1=0.59 support=51

## Secondary metrics

- Wasted-attempt rate: 11.4% (18/158 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 69
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **24.0%** (50/208 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.
