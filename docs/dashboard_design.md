# Minimum Dashboard Specification & Architecture

## Overview

The Minimum Dashboard provides an executive, zero-fluff operational interface for the Autonomous Payment Recovery Control Plane. It focuses strictly on the 7 core business and safety metrics while ensuring full transaction-level traceability backed by an immutable cryptographic audit ledger.

---

## 1. The 7 Core Metrics

| Metric | Formula | Why it matters | Data Source |
| :--- | :--- | :--- | :--- |
| **Revenue at Risk** | `SUM(amount_paise) / 100` | Measures the total gross volume of failed transactions ingested by the control plane. | `cases.amount_paise` |
| **Recovered Value** | `SUM(amount_paise WHERE state = 'RECOVERED') / 100` | Quantifies the actual INR monetary recovery achieved through automated retries. | `cases.amount_paise` (filtered by `state = 'RECOVERED'`) |
| **Recovery Rate** | `(Recovered Value / Revenue at Risk) * 100` | High-level efficiency metric measuring the fraction of lost revenue recaptured. | Derived from Recovered Value & Revenue at Risk |
| **Actions Executed** | `COUNT(actions WHERE executed_at IS NOT NULL)` | Tracks physical retry/action dispatches to external payment networks/gateways. | `actions.executed_at` |
| **Actions Blocked** | `COUNT(audit_events WHERE event_type = 'POLICY_VERDICT' AND decision IN ('DENY', 'REVIEW'))` | Monitors policy interventions (attempt caps, terminal taxonomy rules, EV floor, holdouts). | `audit_events.payload` |
| **AI Confidence** | `AVG(json_extract(payload, '$.confidence')) * 100` | Senses the certainty of the diagnostic LLM across ambiguous error codes. | `audit_events` (`DIAGNOSIS_RETURNED`) |
| **Failure Rate** | `(Unrecovered Cases / Total Cases) * 100` | Tracks the overall proportion of cases that could not be recovered (terminal/abandoned). | `cases.state` (`ABANDONED`, `QUARANTINED`, `FAILED_ATTEMPT`) |

---

## 2. Transaction-Level Traceability

Each transaction ingested by the control plane retains an immutable, cryptographic SHA-256 audit hash-chain that records the exact sequence of events from arrival to final resolution:

```
[SIGNAL_RECEIVED] (Ingestion)
       │
       ▼
[COHORT_ASSIGNED] (Randomized Holdout / Treatment)
       │
       ▼
[TRIAGE_RESULT] (Deterministic Taxonomy or Ambiguous Flag)
       │
       ▼
[DIAGNOSIS_RETURNED] (AI Proposal, Confidence, Expected Outcome, Rationale)
       │
       ▼
[POLICY_VERDICT] (Zero-LLM Gate: ALLOW / DENY / REVIEW + Fired Rules)
       │
       ▼
[ACTION_DISPATCHED] (Scheduler)
       │
       ▼
[ACTION_RESULT / ACTION_REFUSED / ACTION_UNCERTAIN] (Executor Outcome)
       │
       ▼
[DECISION_RECORDED] (Terminal Unified Audit Event)
```

### Drawer Trace Inspector
Clicking **"View Trace"** on any row in the Transaction Ledger opens a side drawer rendering:
- Metadata header (Case ID, Order ID, Amount ₹, Method, Cohort, Final State).
- Cryptographic hash-chain status (`verify_chain` validation badge).
- Step-by-step chronological audit timeline with JSON payloads, actors, timestamp, previous hash, and block hash.

---

## 3. Privacy, PCI Compliance & Data Sanitization

The dashboard layer strictly enforces data redaction:
- **Card Numbers**: Raw 13-19 digit card PANs are masked (`****-****-****-1234`).
- **CVVs & Auth Tokens**: Completely scrubbed (`[REDACTED]`).
- **API Keys & Secrets**: Masked (`[REDACTED_SECRET]`).
- **Idempotency Keys**: Preserved to allow deterministic deduplication inspection without exposing raw credentials.

---

## 4. Running the Dashboard

Launch the dashboard locally using the built-in HTTP server:

```powershell
.venv\Scripts\python.exe scripts\serve_dashboard.py --port 8000 --n 100 --seed 777001
```

Access the dashboard at `http://localhost:8000`.
