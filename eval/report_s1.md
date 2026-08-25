# Evaluation Report — corpus `dev` seed=42 scenario=S1

n=300 · generator=0.2.0 · times_scored=82 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹3802585.82 per 1,000** (95% CI [1540428.72, 5942617.41], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹5521.99, holdout: ₹1719.40 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 23.8%, holdout: 8.2%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.372** (n=100). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.00 R=0.00 F1=0.00 support=0
  - CUSTOMER_FIXABLE: P=0.69 R=0.55 F1=0.61 support=33
  - INSTRUMENT_INVALID: P=0.67 R=0.12 F1=0.21 support=16
  - TERMINAL: P=0.85 R=0.55 F1=0.67 support=51

## Secondary metrics

- Wasted-attempt rate: 9.6% (16/166 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 61
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **21.7%** (46/212 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.
