# Evaluation Report — corpus `dev` seed=42 scenario=S1

n=300 · generator=0.2.0 · times_scored=90 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹3626545.03 per 1,000** (95% CI [890366.28, 6220535.62], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹6503.30, holdout: ₹2876.75 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 25.6%, holdout: 12.3%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.376** (n=103). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.00 R=0.00 F1=0.00 support=0
  - CUSTOMER_FIXABLE: P=0.50 R=0.65 F1=0.56 support=31
  - INSTRUMENT_INVALID: P=0.75 R=0.29 F1=0.41 support=21
  - TERMINAL: P=0.80 R=0.39 F1=0.53 support=51

## Secondary metrics

- Wasted-attempt rate: 14.1% (24/170 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 57
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **22.7%** (50/220 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.
