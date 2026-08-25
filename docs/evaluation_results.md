# Evaluation Results

This document presents the complete evaluation results for the Razorpay Payment Recovery AI agent, capturing business, AI, and safety metrics alongside the adversarial failure-test results.

## 1. Dataset Size
* **Total Records (n)**: 1,000
* **Corpus**: `test` (Seed: 777001, Scenario: S1)
* **Treated Cohort (n_treated)**: 746
* **Holdout Cohort (n_holdout)**: 254

## 2. Baseline Metrics
The baseline provider relies solely on deterministic taxonomy (triage). 
* **Macro F1 Score**: 0.138
* **Incremental Rupees per 1000**: ₹4,336,529.58
* **Gross Treated Rate**: 26.14%
* **Gross Holdout Rate**: 9.06%
* **Treated Rupees**: ₹6,553.75
* **Holdout Rupees**: ₹2,217.22

## 3. AI Metrics
The AI evaluation runs the `ClaudeDiagnosis` port. Currently, the implementation operates as a stub fallback, mirroring the baseline deterministic behaviour.
* **Macro F1 Score**: 0.138
* **Lift over Baseline**: 0.0%
* **Ambiguous Cases Handled**: 291
* **Per-Class Breakdown**:
  * `TRANSIENT_INFRA`: Precision: 0.38, Recall: 1.0, F1: 0.55, Support: 111
  * `CUSTOMER_FIXABLE`: Precision: 0.0, Recall: 0.0, F1: 0.0, Support: 86
  * `INSTRUMENT_INVALID`: Precision: 0.0, Recall: 0.0, F1: 0.0, Support: 43
  * `TERMINAL`: Precision: 0.0, Recall: 0.0, F1: 0.0, Support: 51

## 4. Business Metrics
* **Wasted Attempt Rate**: 6.36% (38 wasted out of 597 total attempts)
* **Deferred Cases**: 2
* **Abandoned Cases**: 149
* **Holdout Closed Cases**: 254

## 5. Safety & System Metrics
* **Holdout Contamination**: 0 (0% crossover between Treated and Holdout)
* **Attempt Cap Breaches**: 0
* **Policy Veto Rate**: 25.56% (205 vetos out of 802 total decisions)
* **Cryptographic Chain**: OK (unbroken)
* **Counter Consistency**: OK

## 6. Failure-Test Results
The adversarial defense suite successfully covers all 10 failure domains.
* **Overall Pass Rate**: 100% (10 / 10 passed)
* **Tested Scenarios**:
  * ✅ Bad AI Output / Schema Violation
  * ✅ Low Confidence Override
  * ✅ Duplicate Events / Ingestion Storm
  * ✅ Stale State / Optimistic Locking
  * ✅ API Timeout (Downtime Failsafe)
  * ✅ Partial Failure / Execution Uncertain
  * ✅ Conflicting Signals / Triage Override
  * ✅ Unsafe Action (Pydantic validation)
  * ✅ Policy Denial (Attempt Cap)
  * ✅ Unknown Execution State (Rollback)

## 7. Limitations
* **AI Implementation**: The AI diagnosis port is currently a stub logic that mirrors baseline heuristics rather than calling the LLM contextually on the Razorpay evidence. This explains the exact identical outcomes between baseline and AI metrics (Lift = 0.0). 
* **Recall for Complex Classes**: The AI model completely fails (Recall = 0.0) to diagnose `CUSTOMER_FIXABLE`, `INSTRUMENT_INVALID`, and `TERMINAL` cases on the held-out set because those require live LLM extraction.
* **Unverified Rules**: The `ATTEMPT_CAP` policy rule was flagged as 'unverified' in the benchmark system metrics because the benchmarking data might not contain enough longitudinal recurrence to naturally breach the cap within the sample.
