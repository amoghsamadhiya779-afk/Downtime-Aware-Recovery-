# Evaluation Report — corpus `dev` seed=42 scenario=S2

n=300 · generator=0.2.0 · times_scored=38 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹4513222.91 per 1,000** (95% CI [1854440.52, 7124066.26], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹6736.94, holdout: ₹2223.71 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 27.3%, holdout: 9.6%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.085** (n=97). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.21 R=1.00 F1=0.34 support=20
  - CUSTOMER_FIXABLE: P=0.00 R=0.00 F1=0.00 support=24
  - INSTRUMENT_INVALID: P=0.00 R=0.00 F1=0.00 support=13
  - TERMINAL: P=0.00 R=0.00 F1=0.00 support=40

## Secondary metrics

- Wasted-attempt rate: 19.6% (37/189 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 53
- Cases abandoned early, zero attempts spent: 38
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **22.5%** (55/244 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Ambiguous macro-F1 (0.085) is below what uniform random 4-class guessing would score (~0.25). If this run used StubDiagnosis (the Phase 1 placeholder, which always guesses TRANSIENT_INFRA and never predicts the other three classes), this number reflects the stub, not AI-1, and should not be quoted as a system result. Re-run with --live (ClaudeDiagnosis) before citing this metric anywhere.
