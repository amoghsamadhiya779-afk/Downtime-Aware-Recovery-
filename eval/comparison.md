# Multi-Arm Evaluation Comparison

Comprehensive multi-arm comparison across diagnosis backends and failure scenarios on `dev` (seed=42, n=300, Generator v0.2.0).

## 1. Arm Comparison Grid

| Arm / Provider | Scenario | Ambiguous Macro-F1 | Incremental ₹ / 1,000 (95% CI) | Wasted Attempt Rate | Policy Veto Rate | DOWNTIME_DEFER Fired | Status |
|---|---|---|---|---|---|---|---|
| **stub (A3 heuristic)** | **S1** | **0.336** | ₹4,913,426 [2,885,604 – 6,836,521] | 14.2% | 24.3% | **0** | Active (Local Heuristic) |
| **stub (A3 heuristic)** | **S2** | **0.425** | ₹3,507,472 [389,349 – 6,384,320] | 10.2% | 22.4% | **47** | Active (Local Heuristic) |
| **stub (A3 heuristic)** | **S3** | **0.312** | ₹1,035,707 [-2,264,398 – 4,008,478] | 10.8% | 23.4% | **0** | Active (Local Heuristic) |
| **baseline (A1 context-blind)** | **S1** | **0.000** | N/A | 19.3% | 24.3% | **0** | Active (Context-Blind) |
| **groq (openai/gpt-oss-20b)** | **S1** | **0.153** | ₹4,217,521 [2,323,352 – 6,079,551] | 19.9% | 23.6% | **0** | Active (Live LLM) |
| **claude (claude-sonnet-5)** | **S1** | **0.372** | ₹3,802,585 [1,540,428 – 5,942,617] | **9.6%** | 21.7% | **0** | Active (Live LLM) |
| **claude (claude-sonnet-5)** | **S2** | **0.519** | ₹4,417,663 [1,609,172 – 6,800,593] | **11.0%** | 23.7% | **51** | Active (Live LLM) |
| **claude (claude-sonnet-5)** | **S3** | **0.372** | ₹3,566,998 [1,225,767 – 5,677,015] | **11.2%** | 24.9% | **0** | Active (Live LLM) |

## 2. Key Empirical Findings & Ablation Analysis

### A. Value of Context-Aware Diagnosis (Claude Sonnet 5 vs Heuristic Stub)
- **Context-Blind Baseline (A1)** scores **0.000 Macro-F1** on ambiguous cases and suffers a higher wasted attempt rate (**19.3%**) because it cannot distinguish between terminal account closures and transient errors.
- **Stub Heuristic (A3)** achieves **0.336 Macro-F1** and reduces wasted attempts to **14.2%**, while the live LLM arm (**Claude Sonnet 5**) achieves **0.372 Macro-F1** (+10.7% relative improvement) and reduces wasted attempts to **9.6%** (32% reduction in futile retries). On S2 (burst outage), Claude reaches **0.519 Macro-F1**.
- **Groq Free-Tier Arm (Adverse Finding)** scores **0.153 Macro-F1**, demonstrating that smaller open models lack sufficient reasoning depth for the ambiguous failure tail.

### B. Downtime Mechanism across Scenarios S1, S2, and S3
- **S1 (Realistic Baseline, 5% downtime)**: Low overlap between failures and outages at n=300 yields `DOWNTIME_DEFER = 0`.
- **S2 (Burst Outage, 40% downtime)**: High outage overlap causes `DOWNTIME_DEFER` to fire **47–51 times**, deferring retries past outage resolution and raising Macro-F1 to **0.425–0.519**.
- **S3 (Negative Control, 0% downtime)**: Zero downtime windows in corpus produces strictly **0** deferrals, confirming zero false lift.

### C. Safety Invariants
- Across all arms and scenarios: **Holdout Contamination = 0**, **Attempt Cap Breaches = 0**, **Audit Chain Verifies = True**.
- Policy veto rate remains strictly within the pre-registered [5%, 40%] target safety band (21.7% - 24.9%).
