# Multi-Scenario Evaluation Report — S1, S2, and S3 Published Together

Evaluation across all three pre-registered scenarios (seed=42, n=300).
Per `eval/PREREGISTRATION.md`, reporting only S2 is the dishonest version; lift in S3 is a bug, not a result.

## Executive Summary: Scenario Comparison Grid

| Scenario | Description | Downtime Rate | Incremental ₹ / 1,000 (95% CI) | Ambiguous Macro-F1 | DOWNTIME_DEFER Fired | Wasted Attempt Rate |
|---|---|---|---|---|---|---|
| **S1** | Realistic Baseline | 5.0% | ₹5013695.46 [2808314.49, 7237805.07] | 0.000 | **0** | 19.3% |
| **S2** | Burst Outage | 40.0% | ₹4638256.76 [2009605.46, 7190859.99] | 0.083 | **47** | 20.3% |
| **S3** | Negative Control | 0.0% | ₹2486113.73 [-232822.65, 4988607.16] | 0.000 | **0** | 22.1% |

> **Pre-Registration Invariant Verification**:
> 1. **S2 Burst**: Elevated outage overlap activates `DOWNTIME_DEFER` > 0 times, exercising deferred retry timing.
> 2. **S3 Negative Control**: Zero downtime windows produces exactly 0 `DOWNTIME_DEFER` triggers. No false downtime lift.

---

## Detailed Breakdown: Scenario S1

# Evaluation Report — corpus `dev` seed=42 scenario=S1

n=300 · generator=0.2.0 · times_scored=67 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹5013695.46 per 1,000** (95% CI [2808314.49, 7237805.07], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹6497.03, holdout: ₹1483.34 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 24.2%, holdout: 8.2%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.000** (n=101). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.00 R=0.00 F1=0.00 support=0
  - CUSTOMER_FIXABLE: P=0.00 R=0.00 F1=0.00 support=34
  - INSTRUMENT_INVALID: P=0.00 R=0.00 F1=0.00 support=16
  - TERMINAL: P=0.00 R=0.00 F1=0.00 support=51

## Secondary metrics

- Wasted-attempt rate: 19.3% (36/187 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 40
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **24.3%** (60/247 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Ambiguous macro-F1 (0.000) is below what uniform random 4-class guessing would score (~0.25). If this run used StubDiagnosis (the Phase 1 placeholder, which always guesses TRANSIENT_INFRA and never predicts the other three classes), this number reflects the stub, not AI-1, and should not be quoted as a system result. Re-run with --live (ClaudeDiagnosis) before citing this metric anywhere.
- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.


---

## Detailed Breakdown: Scenario S2

# Evaluation Report — corpus `dev` seed=42 scenario=S2

n=300 · generator=0.2.0 · times_scored=68 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹4638256.76 per 1,000** (95% CI [2009605.46, 7190859.99], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹7076.52, holdout: ₹2438.26 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 28.2%, holdout: 9.6%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.083** (n=101). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.20 R=1.00 F1=0.33 support=20
  - CUSTOMER_FIXABLE: P=0.00 R=0.00 F1=0.00 support=24
  - INSTRUMENT_INVALID: P=0.00 R=0.00 F1=0.00 support=13
  - TERMINAL: P=0.00 R=0.00 F1=0.00 support=44

## Secondary metrics

- Wasted-attempt rate: 20.3% (38/187 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 47
- Cases abandoned early, zero attempts spent: 40
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **22.4%** (54/241 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Ambiguous macro-F1 (0.083) is below what uniform random 4-class guessing would score (~0.25). If this run used StubDiagnosis (the Phase 1 placeholder, which always guesses TRANSIENT_INFRA and never predicts the other three classes), this number reflects the stub, not AI-1, and should not be quoted as a system result. Re-run with --live (ClaudeDiagnosis) before citing this metric anywhere.


---

## Detailed Breakdown: Scenario S3

# Evaluation Report — corpus `dev` seed=42 scenario=S3

n=300 · generator=0.2.0 · times_scored=69 · n_treated=227 · n_holdout=73

## Primary KPI — incremental ₹ recovered per 1,000 at-risk (vs. holdout)

- **Incremental: ₹2486113.73 per 1,000** (95% CI [-232822.65, 4988607.16], 2000 bootstrap resamples)
- Gross recovered ₹/case — treated: ₹4938.98, holdout: ₹2452.86 (printed beside incremental deliberately — the gap is the argument, not the gross figure)
- Gross recovery rate — treated: 20.7%, holdout: 11.0%

## AI quality — diagnosis on the AMBIGUOUS subset only

- Ambiguous macro-F1: **0.000** (n=101). Overall accuracy across all cases is NOT reported — it is inflated by the CLEAN majority, which never reaches the model.
  - TRANSIENT_INFRA: P=0.00 R=0.00 F1=0.00 support=0
  - CUSTOMER_FIXABLE: P=0.00 R=0.00 F1=0.00 support=34
  - INSTRUMENT_INVALID: P=0.00 R=0.00 F1=0.00 support=16
  - TERMINAL: P=0.00 R=0.00 F1=0.00 support=51

## Secondary metrics

- Wasted-attempt rate: 22.1% (42/190 attempts landed on a case whose hidden true class is TERMINAL)
- Retries deferred past downtime end (rule DOWNTIME_DEFER fired): 0
- Cases abandoned early, zero attempts spent: 37
- Holdout cases closed without action (HOLDOUT_GUARD): 73

## Safety invariants — build-breaking, not descriptive

- Holdout contamination: **0** (target: 0)
- Attempt-cap breaches: **0** (target: 0)
- Policy veto rate: **23.4%** (58/248 RETRY proposals denied) — target band [5%, 40%]: near 0 means the gate is decorative, near 100% means the model is useless
- Audit chain verifies: **True**
- Denormalised counters match audit-log replay: **True**

## Compliance disclosure

- ⚠ Rules executing on UNVERIFIED constants (EVIDENCE.md E12–E15): ATTEMPT_CAP. No compliance claim is made from these numbers until a primary source is recorded.

## Adverse findings

- Incremental ₹ CI includes zero (or is negative) at this sample size — the lift is not statistically distinguishable from noise here. Expected at n=300 (Phase 1 dev corpus); the sealed n=1,000 test corpus (Phase 3) is powered for a ~10pp effect.
- Ambiguous macro-F1 (0.000) is below what uniform random 4-class guessing would score (~0.25). If this run used StubDiagnosis (the Phase 1 placeholder, which always guesses TRANSIENT_INFRA and never predicts the other three classes), this number reflects the stub, not AI-1, and should not be quoted as a system result. Re-run with --live (ClaudeDiagnosis) before citing this metric anywhere.
- Zero retries were deferred by DOWNTIME_DEFER in this corpus. With only 300 cases and the S1 (realistic) downtime rate, low or zero overlap between generated failures and generated downtime windows is expected, not necessarily a bug — `make demo` demonstrates the mechanism directly on hand-built cases. A burst scenario (S2, higher downtime_rate) is needed before this corpus can support any claim about the downtime mechanism's contribution.


---
