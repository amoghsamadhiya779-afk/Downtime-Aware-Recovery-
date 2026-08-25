# Downtime-Aware Payment Recovery Control Plane

Autonomous payment failure recovery for Indian payment rails (UPI, Cards, Netbanking, eMandates), evaluated against a randomized holdout control group with a deterministic Zero-LLM policy engine and a SHA-256 cryptographic audit chain.

---

## 1. Problem

When a digital payment fails in India, payment systems face two main failure modes:

1. **Blind Retries**: Repeatedly retrying a failed payment during an active bank or network outage. This exhausts customer retry limits, triggers fraud blocks, and incurs gateway fees.
2. **Premature Abandonment**: Treating transient, recoverable errors (such as network timeouts) as permanently lost transactions.

Directly connecting Large Language Models (LLMs) to payment gateways introduces significant risks:
- Models can hallucinate recovery actions on unrecoverable fraud or expired instruments.
- Model decisions are non-deterministic and difficult to audit under regulatory scrutiny.
- Models lack built-in mechanisms for idempotency, retry caps, and financial state machines.

---

## 2. Solution

The Payment Recovery Control Plane combines AI reasoning with deterministic safety rules:

- **Two-Tier Triage**: Known errors (such as `fraud_suspected` or `card_expired`) are handled instantly without invoking an LLM. Only ambiguous errors (such as `payment_failed` or `payment_declined_by_bank`) are sent to AI diagnosis.
- **Pure-Function AI**: The LLM suggests a recoverability class, estimated probability, and retry delay. It has no tool access, no database write access, and no payment dispatch authority.
- **Zero-LLM Policy Gate**: A deterministic rules engine evaluates every AI proposal against strict invariants (such as method retry caps and active downtime windows) and holds sovereign veto power.
- **Idempotent Execution**: Every action uses a SHA-256 idempotency key. Duplicate dispatches return cached results (`replayed=true`) without double-charging.
- **Cryptographic Audit Log**: Every state transition, triage result, AI proposal, policy verdict, and execution result is stored in an append-only SHA-256 hash chain.

---

## 3. Architecture

The system uses a single unified pipeline for both live recovery and evaluation replay:

```
Payment Failure Signal
         │
         ▼
┌─────────────────────────┐
│   Ingest & Triage       │ ── (Deterministic taxonomy triage)
└─────────────────────────┘
         │
         ▼
┌─────────────────────────┐
│   AI Diagnostic Engine  │ ── (Pure function: recoverability class + delay)
└─────────────────────────┘
         │
         ▼
┌─────────────────────────┐
│  Zero-LLM Policy Gate   │ ── (Rules engine: ATTEMPT_CAP, DOWNTIME_DEFER, etc.)
└─────────────────────────┘
         │
         ▼
┌─────────────────────────┐
│  Idempotent Execution   │ ── (SHA-256 deduplication & SIM/LIVE dispatch)
└─────────────────────────┘
         │
         ▼
┌─────────────────────────┐
│ State Machine & Audit   │ ── (Optimistic concurrency + SHA-256 hash chain)
└─────────────────────────┘
```

### 9-Phase Transaction Lifecycle

Every transaction moves through nine distinct phases:
1. **Event**: Ingestion of the raw failure signal, order ID, amount, and payment method.
2. **Context**: Cohort assignment (Treated vs Holdout) and initial triage.
3. **Diagnosis**: Recoverability classification and calibrated confidence.
4. **Evidence**: Grounded field references and risk signals.
5. **Proposal**: Proposed recovery action, optimal delay, and expected probability.
6. **Policy Verdict**: Deterministic gate decision (`ALLOW` or `DENY`) with fired rules.
7. **Execution**: Dispatch verification, execution mode, and replay detection.
8. **Outcome**: Final transaction state (`RECOVERED`, `ABANDONED`, or `QUARANTINED`).
9. **Audit Trail**: Verification of the immutable SHA-256 event hash chain.

---

## 4. Role of AI

The AI model is strictly isolated as a diagnostic component:

- **Input**: Sanitized error metadata, instrument type, prior attempt count, and downtime status.
- **Output**: Structured JSON specifying `recoverability`, `confidence`, `proposed_action`, `proposed_delay_minutes`, and `expected_outcome`.
- **Privileges**: Zero database privileges, zero API access, zero tool execution capability.
- **Multi-Tier Fallbacks**:
  - *Tier 0*: Primary model provider (e.g. claude-sonnet-5 / openai/gpt-oss-120b).
  - *Tier 1*: Alternate model provider fallback.
  - *Tier 2*: Taxonomy prior based on historical payment failure statistics.
  - *Tier 3*: Fallback to `UNKNOWN` recoverability. The policy gate halts execution (`STOP`), preventing any speculative charge.

---

## 5. Safety Invariants

The system enforces six core safety guarantees:

1. **Deterministic Sovereignty**: The Policy Engine (`agent/policy/engine.py`) reads rules from `agent/policy/rules.yaml`. It can veto any AI recommendation regardless of model confidence.
2. **Per-Method Attempt Caps**: Hard limits on retries prevent customer fatigue and card network penalties:
   - Card: 4 attempts
   - UPI: 2 attempts
   - Netbanking: 2 attempts
   - eMandate: 3 attempts
3. **Downtime Deferral**: When an outage window is active for a specific bank or handle, retries are deferred until the recorded end of the downtime window.
4. **Holdout Guard**: A randomized 25% holdout cohort is isolated unconditionally. The holdout cohort assignment cannot be changed after creation, enforced by SQLite database triggers.
5. **Idempotency**: All execution dispatches require a unique SHA-256 idempotency key. Duplicate calls never trigger secondary payment authorizations.
6. **Optimistic Concurrency**: State transitions require version checks, preventing race conditions or double-processing during concurrent execution.

---

## 6. Evaluation

The system is evaluated by replaying failure events against a hidden ground truth dataset containing organic recovery counterfactuals (`p_organic`).

### Benchmark Results (Corpus: dev, Seed: 42, n=300 cases, Generator v0.2.0)

The following metrics are generated directly by `evalharness.run`:

| Metric | Measured Value | Notes |
| :--- | :--- | :--- |
| **Incremental Value** | **₹4,518,252.78 per 1,000 cases** | 95% Bootstrap CI: [₹2,379,261.71, ₹6,561,229.09] (2,000 resamples) |
| **Gross Recovery (Treated)** | **23.3%** | Treated recovery rate (vs 6.8% organic holdout rate) |
| **Ambiguous Macro-F1** | **0.380** | Scored on 97 ambiguous cases (CLEAN taxonomy cases excluded) |
| **Wasted Attempt Rate** | **10.4%** | 17 of 164 attempts landed on unrecoverable terminal failures |
| **Holdout Contamination** | **0 cases** | Zero holdout transactions were acted upon |
| **Attempt Cap Breaches** | **0 cases** | Zero transactions exceeded retry limits |
| **Policy Veto Rate** | **24.8%** | 54 of 218 retry proposals vetoed by safety rules |
| **Audit Chain Integrity** | **Verified (True)** | SHA-256 cryptographic chain validated across all events |

### Adverse Findings & Multi-Scenario Insights

- **Zero S1 Downtime Deferrals**: In Scenario S1 (realistic baseline, 5% downtime), zero retries were deferred by `DOWNTIME_DEFER` due to low failure-outage overlap at n=300 cases.
- **Scenario S2 Burst Outage Validation**: In Scenario S2 (40% downtime rate), `DOWNTIME_DEFER` actively deferred 40 retries past outage resolution, raising ambiguous macro-F1 to **0.508**.
- **Scenario S3 Negative Control**: In Scenario S3 (0% downtime), `DOWNTIME_DEFER` fired exactly 0 times, confirming no spurious downtime lift when outages are absent.

---

## 7. Failure Handling

The system includes explicit handling for unexpected operational failures:

- **Gateway Timeouts**: If a gateway does not respond within the timeout window (`ExecutionUncertain`), the transaction transitions to `QUARANTINED` for out-of-band reconciliation rather than initiating an unverified retry.
- **Malformed AI Responses**: If an LLM returns invalid JSON or corrupted schema fields, the system falls back to Tier 3 (`UNKNOWN`) and marks the case as `ABANDONED`.
- **Duplicate Ingestion**: Re-ingesting an existing transaction order returns the existing record without generating duplicate attempts or charging the customer twice.
- **Kill Switch**: Setting `kill_switch: true` in `agent/policy/rules.yaml` immediately blocks all retry dispatches across the entire system.

---

## 8. Setup & Installation

### Prerequisites
- Python 3.11 or 3.12
- Git

### Installation Steps

```powershell
# 1. Clone the repository
git clone https://github.com/amoghsamadhiya779-afk/Downtime-Aware-Recovery-.git
cd "Downtime-Aware-Recovery-"

# 2. Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
# source .venv/bin/activate

# 3. Install project dependencies
pip install -e ".[dev]"

# 4. Create local environment configuration
cp .env.example .env

# 5. Generate reproducible dataset (Seed 42 -> 300 cases)
python scripts/gen.py

# 6. Run automated test suite (326 tests)
pytest -v
```

---

## 9. Demo

The system provides three deterministic demo scenarios that are fully reproducible from a clean state:

### Scenario 1: Successful Recovery
A transient UPI authorization failure is diagnosed as `TRANSIENT_INFRA`, approved by policy (`ALLOW`), dispatched, and successfully recovered (₹2,499.00).

```powershell
python scripts/demo_controls.py --scenario successful_recovery
```

### Scenario 2: Unsafe AI Recommendation Blocked
An adversarial AI proposal recommending `RETRY` with 100% confidence on a card transaction that has already reached its 4-attempt cap is vetoed by the Zero-LLM Policy Gate (`DENY` -> `ABANDONED`).

```powershell
python scripts/demo_controls.py --scenario unsafe_ai_blocked
```

### Scenario 3: Duplicate & Timeout Safety
A gateway timeout during netbanking dispatch transitions safely into `QUARANTINED` status, and duplicate dispatches are deduplicated via idempotency keys (`replayed=true`).

```powershell
python scripts/demo_controls.py --scenario duplicate_timeout_handled
```

### Run All Demos Sequentially
```powershell
python scripts/demo.py
```

### Launch Interactive Executive Dashboard
```powershell
python scripts/serve_dashboard.py --port 8000
```
Open **`http://localhost:8000`** in your browser to inspect the 7 core KPIs, hand-rolled CSS analytics grid, and the 9-phase transaction ledger.

---

## 10. Limitations

1. **Synthetic Response Model**: In the current development evaluation corpus, bank recovery probabilities during downtime are modeled using synthetic distributions based on the failure taxonomy.
2. **Baseline Diagnostic Heuristics**: The default offline stub (`StubDiagnosis`) scores a macro-F1 of 0.380 on ambiguous errors using feature-conditioned branching. Connecting live LLM providers (`ClaudeDiagnosis` or `GroqDiagnosis`) with active API keys is required for full diagnostic reasoning.
3. **Fixed Attempt Caps**: Attempt caps are currently configured globally per payment method rather than dynamically adjusted per merchant risk tier or specific issuing bank agreements.

