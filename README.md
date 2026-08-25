# Downtime-Aware Payment Recovery Control Plane

> **Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery**  
> Autonomous payment failure recovery measured against a randomized holdout with a zero-LLM policy engine and cryptographic SHA-256 audit trail.

---

## 1. What This Is

When a digital payment fails in India (UPI, Card, Netbanking, eMandate), blind retry loops cause customer fatigue, gateway rate-limiting, and unnecessary transaction fees. 

This system provides an **Autonomous Recovery Control Plane** that:
1. **Separates Triage from AI Reasoning**: Deterministic errors (e.g. `fraud_suspected`, `card_expired`) are triaged instantly with zero LLM inference.
2. **Diagnoses Ambiguous Failures**: Genuinely ambiguous signals (e.g. `payment_failed`, `payment_declined_by_bank`) are routed to AI diagnosis for recoverability classification and optimal retry horizon estimation.
3. **Enforces Zero-LLM Policy Veto**: A deterministic, rule-based Policy Engine holds absolute veto authority over AI proposals (enforcing method attempt caps, downtime deferral, economic floors, and holdout preservation).
4. **Guarantees Idempotency & Uncertainty Quarantine**: Prevents double-charging via SHA-256 idempotency deduplication and isolates gateway timeouts into `QUARANTINED` status for reconciliation.
5. **Cryptographic Auditability**: Every lifecycle event, policy verdict (`DecisionRecord`), and state transition is immutably appended to a SHA-256 hash-chain.

---

## 2. Quickstart & Clean Environment Setup

### Prerequisites
- Python 3.11+ (tested on Python 3.11 & 3.12)
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

# 3. Install application and test dependencies
pip install -e ".[dev]"

# 4. Copy environment configuration
cp .env.example .env
```

---

## 3. Core Commands & Workflows

### A. Generate Seeded Synthetic Dataset
Generates reproducible operational SQLite database and hidden ground truth:
```powershell
python scripts/gen.py
# Or via Makefile: make gen
```

### B. Run Complete Test Suite
Runs all 310 unit, property-based, and lifecycle integration tests:
```powershell
python -m pytest -v
# Or via Makefile: make test
```

### C. Run Evaluation Harness
Replays the evaluation corpus and calculates incremental recovery vs. randomized holdout:
```powershell
python -m evalharness.run
# Or with machine-readable JSON output:
python -m evalharness.run --json
```

### D. Launch Executive Control Plane Dashboard
Starts the interactive glassmorphic web dashboard on `http://localhost:8000`:
```powershell
python scripts/serve_dashboard.py --port 8000
```
Open **`http://localhost:8000`** in your browser to inspect the 7 core KPIs, transaction ledger, and 9-phase lifecycle detail view.

### E. Run Developer Failure Mode Controls (CLI)
Triggers real backend system execution for 4 distinct failure modes:
```powershell
python scripts/demo_controls.py --all
```

---

## 4. Evaluation Benchmark Results

*The following metrics are quoted directly from generated `eval/report.md` (corpus `dev`, seed=42, n=300, S1 scenario):*

| Metric | Result | Description |
| :--- | :--- | :--- |
| **Incremental Recovered Value** | **₹5,266,944.63 per 1,000** | 95% CI [₹2,236,886.14, ₹7,998,325.23] (2,000 bootstrap resamples) |
| **Gross Recovery Rate (Treated)** | **29.5%** | Recovery rate on treated arm (n=227) |
| **Gross Recovery Rate (Holdout)** | **6.8%** | Baseline organic recovery rate on holdout arm (n=73) |
| **Ambiguous Macro-F1** | **0.151** | AI diagnostic quality on ambiguous subset (n=88) |
| **Wasted Attempt Rate** | **6.7%** | Attempts landing on unrecoverable terminal errors |
| **Holdout Contamination** | **0** | Zero holdout cases were acted upon (Invariant 4) |
| **Attempt-Cap Breaches** | **0** | Zero transactions exceeded per-method retry caps |
| **Policy Veto Rate** | **21.7%** | 50/230 AI proposals vetoed by the Policy Engine |
| **Cryptographic Audit Chain** | **Verified (True)** | SHA-256 hash-chain validated across all events |

---

## 5. Architectural Invariants

1. **One Code Path, Two Modes**: Replay evaluation and live execution share the exact same pipeline; only `Clock` and `ExecutorPort` are injected.
2. **Zero-Tool LLM**: The AI model is a pure function (structured in → structured out). It holds zero database, API, or execution privileges.
3. **Zero-LLM Policy Veto**: The policy engine (`agent/policy/engine.py`) evaluates rules deterministically from `agent/policy/rules.yaml`.
4. **Unconditional Holdout Guard**: Rule `HOLDOUT_GUARD` isolates the 25% holdout cohort to prove incremental rupee value against organic recovery. Cohort immutability is enforced by SQLite trigger.
5. **Fail-Closed Safety**: Any schema error, malformed LLM response, or unseen reason code safely falls back to `Tier 3 UNKNOWN` and halts into `ABANDONED`.
6. **Physical Separation**: `agent/` never imports `datagen/` or hidden ground truth.

---

## 6. Container Deployment (Docker)

```bash
# Build and start container
docker compose up --build -d

# Verify container health
curl -f http://localhost:8000/api/health
```

---

## 7. Known Limitations & Adverse Findings

1. **Synthetic Response Model**: In Phase 1, recovery probabilities for transient infrastructure errors are modeled synthetically based on documented gateway characteristics (`EVIDENCE.md`).
2. **Sub-Optimal Stub Macro-F1**: Baseline `StubDiagnosis` scores macro-F1 of 0.151 on ambiguous errors because it predicts only `TRANSIENT_INFRA`. Real LLM providers (`ClaudeDiagnosis`, `GroqDiagnosis`) should be supplied with API keys in `.env` for production evaluation.
3. **Attempt Cap Source**: Attempt caps (UPI: 2, Card: 4, Netbanking: 2, eMandate: 3) are derived from industry best practices; pending final formal publication by card networks.
