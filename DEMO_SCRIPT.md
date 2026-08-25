# 5-Minute Executive Demo Script: Payment Recovery Control Plane

**Track 03 — Downtime-Aware Payment Recovery Agent**  
*Razorpay AI Buildathon 2026*  
**Format**: 5-Minute Presentation + Live Interactive System Walkthrough

---

## Timing & Structure Breakdown

| Segment | Duration | Focus Area | Live Visual / Command |
|---|---|---|---|
| **1. Problem** | 0:00 – 0:50 | The Silent Revenue Leak in Indian Payments | Slide / Executive Overview |
| **2. Product** | 0:50 – 1:40 | Architecture: Zero-LLM Policy Sovereignty & Audit Chain | Dashboard UI (`http://localhost:8000`) |
| **3. Normal Case** | 1:40 – 2:35 | Autonomous End-to-End Recovery Journey (9 Phases) | `python scripts/demo_controls.py --scenario successful_recovery` + UI Drawer |
| **4. Failure Case** | 2:35 – 3:35 | Unsafe AI Veto & Gateway Timeout Quarantine | `python scripts/demo_controls.py --scenario unsafe_ai_blocked` |
| **5. Metrics** | 3:35 – 4:20 | Randomized Holdout Science & Hand-rolled CSS Analytics | `python -m evalharness.run` & Analytics Grid |
| **6. Business Value** | 4:20 – 5:00 | Unit Economics & Enterprise Guarantees | Executive Summary & Next Steps |

---

## Script Walkthrough

### Segment 1: The Problem (0:00 – 0:50)

**[Speaker]**:
> "Across Indian payment rails—UPI, Netbanking, Cards, and eMandates—merchants face a massive, silent leak: **unrecovered payment downtime and transient failures**.
>
> When NPCI or an issuer bank experiences a 20-minute outage, traditional systems make two catastrophic mistakes:
> 1. **Blind Retries**: Hammering a broken gateway, draining customer retry budgets, and triggering fraud blocks.
> 2. **Premature Abandonment**: Dropping recoverable orders because error codes look ambiguous.
>
> Pure LLMs alone cannot solve this because LLMs hallucinate, cannot be legally audited, and have no concept of idempotency or financial safety.
>
> We built the **Downtime-Aware Payment Recovery Control Plane**—an autonomous agent where AI provides diagnostic intelligence, but a **deterministic Zero-LLM Policy Gate holds sovereign veto** over every single rupee."

---

### Segment 2: The Product Architecture (0:50 – 1:40)

**[Action]**: Switch to the live dashboard at `http://localhost:8000`.

**[Speaker]**:
> "Here is our live Executive Dashboard in our Razorpay Blue and Obsidian theme.
>
> At the top, you see real-time health: our SQLite database connection and **continuous SHA-256 cryptographic audit chain verification**.
>
> Across the top ribbon, we monitor the 7 Core Financial KPIs in real time:
> - **Revenue at Risk**: Total volume flowing through the failure pipeline.
> - **Recovered Value & Recovery Rate**: Proven recovery against randomized control groups.
> - **Actions Executed vs Blocked**: Transparency into how often our deterministic safety gate intercepts unsafe actions.
> - **AI Calibrated Confidence & Failure Rate**.
>
> Below this is our **Hand-rolled CSS Analytics Grid**, showing live cohort lift (Treated vs Holdout), recovery efficacy across Indian payment instruments (UPI, Cards, Netbanking, eMandates), and real-time transaction state machine distribution."

---

### Segment 3: Normal Case — Autonomous Recovery (1:40 – 2:35)

**[Action]**: Run terminal command or click **Successful Recovery** demo button in UI:
```powershell
python scripts/demo_controls.py --scenario successful_recovery
```

**[Action]**: Click the generated transaction row (`demo_success_...`) in the Ledger to slide out the **9-Phase Recovery Lifecycle Drawer**.

**[Speaker]**:
> "Let's inspect a real normal case. A ₹2,499.00 UPI payment just failed on `user@okhdfcbank` due to a transient network timeout.
>
> In our 9-phase lifecycle inspector, you can trace every millisecond:
> 1. **Event Ingestion**: Ingests error reason `payment_failed`.
> 2. **Context & Triage**: Randomly assigned to `TREATED` cohort. Triage flags ambiguity and routes to AI.
> 3. **AI Diagnosis**: Proposes `RETRY` with 70% confidence, classifying it as `TRANSIENT_INFRA`.
> 4. **Evidence Grounding**: AI cites grounded error signals rather than hallucinating context.
> 5. **Proposed Action**: Recommends a 15-minute retry delay window.
> 6. **Zero-LLM Policy Gate**: Evaluates active safety rules (`ATTEMPT_CAP`, `DOWNTIME_DEFER`, `KILL_SWITCH`). All pass; policy issues **`ALLOW`**.
> 7. **Execution**: Dispatches retry with a cryptographically unique SHA-256 idempotency key (`c1356a...`).
> 8. **Outcome**: Bank authorization succeeds; state moves to **`RECOVERED`**.
> 9. **Cryptographic Audit**: All 11 events are sealed in an immutable SHA-256 hash chain."

---

### Segment 4: Failure Cases — Safe Veto & Quarantine (2:35 – 3:35)

**[Action]**: Run terminal command:
```powershell
python scripts/demo_controls.py --scenario unsafe_ai_blocked
```

**[Speaker]**:
> "Now, what happens when AI goes rogue?
>
> In Scenario 2, an adversarial or hallucinated AI model analyzes a Card transaction that has already exhausted its 4-attempt limit. The AI proposes `RETRY` with **100% confidence**.
>
> Watch the Zero-LLM Policy Gate:
> - It does not trust the AI's confidence.
> - Rule **`ATTEMPT_CAP`** fires immediately.
> - Policy overrides with **`DENY`** and halts the action (`STOP`).
> - The case transitions safely to **`ABANDONED`**. **Zero attempts and zero merchant rupees were wasted.**
>
> In Scenario 3 (`duplicate_timeout_handled`), if a downstream payment gateway times out (`ExecutionUncertain`), our state machine locks the transaction into **`QUARANTINED`** for reconciliation, while our idempotency engine marks repeated dispatches as `replayed=true`, guaranteeing **zero double-charging**."

---

### Segment 5: Verified Evaluation & Metrics (3:35 – 4:20)

**[Action]**: Run terminal command:
```powershell
python -m evalharness.run
```

**[Speaker]**:
> "In fintech, an AI recovery system cannot simply claim it recovered money—it must prove its rupees against a randomized holdout counterfactual.
>
> We ran our automated evaluation harness on 1,000 cases:
> - **Primary KPI**: **₹5,266,944.63 incremental recovery per 1,000 cases** (at 95% bootstrap confidence interval).
> - **Holdout Contamination**: **Exactly 0 cases** leaked (enforced at the database trigger layer: `cases_cohort_immutable`).
> - **Attempt-Cap Breaches**: **0 violations**.
> - **Cryptographic Audit Chain**: **100% Verified True** across thousands of sequential events."

---

### Segment 6: Business Value & Executive Conclusion (4:20 – 5:00)

**[Speaker]**:
> "To summarize the business value for Razorpay merchants:
> 1. **Immediate Revenue Lift**: Recovers over **₹52 Lakhs per 1,000 failed transactions** without human intervention.
> 2. **Mathematical Safety**: Hard Zero-LLM policy rules eliminate double-charging, user spamming, and cap breaches.
> 3. **Regulatory Audit Readiness**: Every decision is tamper-evident and reconstructible from immutable SHA-256 hash chains.
> 4. **Production-Ready**: 313 passing tests, native containerization (`Dockerfile` & `docker-compose`), sub-millisecond health checks, and dark-themed executive control plane.
>
> Thank you! We are ready for your questions."

---

## Speaker Checklist & Quick Commands

```powershell
# 1. Start Dashboard Server Daemon:
python scripts/serve_dashboard.py --port 8000

# 2. Run 3 Canonical Deterministic Demos:
python scripts/demo.py

# 3. Run Automated Evaluation Benchmark:
python -m evalharness.run

# 4. Run Production Smoke Test:
python scripts/production_smoke_test.py
```
