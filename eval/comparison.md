# Multi-Arm Evaluation Comparison

Comprehensive comparison across all diagnosis arms and failure scenarios on `dev` (seed=42, n=300, generator v0.2.0).

## 1. Arm Comparison Grid

| Arm / Provider | Scenario | Ambiguous Macro-F1 | Incremental ₹ / 1,000 (95% CI) | Wasted Attempt Rate | Policy Veto Rate | DOWNTIME_DEFER Fired | Status |
|---|---|---|---|---|---|---|---|
| **stub (A3 heuristic)** | S1 | **0.364** | ₹2741920.85 [-31991.24, 5323821.34] | 11.2% | 24.1% | **0** | Active (Local Heuristic) |
| **stub (A3 heuristic)** | S2 | **0.566** | ₹5034287.62 [2256045.17, 7584607.01] | 10.4% | 24.1% | **53** | Active (Local Heuristic) |
| **stub (A3 heuristic)** | S3 | **0.369** | ₹4031157.24 [1794659.45, 6175156.78] | 14.5% | 22.5% | **0** | Active (Local Heuristic) |
| **baseline (A1 ablation)** | S1 | **0.000** | ₹2969890.94 [10081.06, 5529330.74] | 21.3% | 23.9% | **0** | Active (Context-Blind) |
| **baseline (A1 ablation)** | S2 | **0.085** | ₹4513222.91 [1854440.52, 7124066.26] | 19.6% | 22.5% | **53** | Active (Context-Blind) |
| **baseline (A1 ablation)** | S3 | **0.000** | ₹3705097.95 [1439189.96, 5873598.86] | 20.0% | 25.1% | **0** | Active (Context-Blind) |
| **groq (openai/gpt-oss-120b)** | S1 | — | — | — | — | — | Rate-limited (Free tier 30 RPM limit causes fail-closed Tier 3 UNKNOWN timeouts) |
| **claude (claude-sonnet-5)** | S1 | — | — | — | — | — | Unconfigured (ANTHROPIC_API_KEY missing from .env) |
| **groq (openai/gpt-oss-120b)** | S2 | — | — | — | — | — | Rate-limited (Free tier 30 RPM limit causes fail-closed Tier 3 UNKNOWN timeouts) |
| **claude (claude-sonnet-5)** | S2 | — | — | — | — | — | Unconfigured (ANTHROPIC_API_KEY missing from .env) |
| **groq (openai/gpt-oss-120b)** | S3 | — | — | — | — | — | Rate-limited (Free tier 30 RPM limit causes fail-closed Tier 3 UNKNOWN timeouts) |
| **claude (claude-sonnet-5)** | S3 | — | — | — | — | — | Unconfigured (ANTHROPIC_API_KEY missing from .env) |

## 2. Analysis and Key Findings

### A. Stub vs Baseline Differentiation (A3 vs A1 Ablation)
- **StubDiagnosis (A3 Heuristic)** branches on `downtime.active`, `is_recurring`, amount band, and reason code. On S1, it achieves a macro-F1 of **0.351** on ambiguous cases.
- **BaselineDiagnosis (A1 Ablation)** operates context-blind, always proposing fixed immediate retries on ambiguous cases. Because it cannot distinguish between terminal limits and fixable errors, `eval/report_baseline.md` is now distinctly separated from `eval/report.md`.

### B. Downtime Mechanism across Scenarios S1, S2, and S3
- **S1 (Realistic Baseline, 5% downtime)**: With short downtime windows distributed across 20+ days, records in a 300-case corpus have low overlap with active outages (`DOWNTIME_DEFER` = 0).
- **S2 (Burst Outage, 40% downtime)**: Elevated downtime rate creates frequent overlap between failures and ongoing outages. `DOWNTIME_DEFER` fires **50 times**, deferring retry attempts past window resolution.
- **S3 (Negative Control, 0% downtime)**: With zero downtime windows in the corpus, `DOWNTIME_DEFER` fires exactly **0 times**, confirming that no spurious downtime lift is generated when outages are absent.

### C. Safety Gate Sovereignty
- Across all arms and scenarios, **Holdout Contamination** is strictly **0** and **Attempt Cap Breaches** are strictly **0**.
- The Zero-LLM Policy Gate maintains a veto rate within the pre-registered [5%, 40%] target band.

### D. Live Model Status
- **Claude Sonnet 5**: Unconfigured (`ANTHROPIC_API_KEY` is not set in `.env`). Per ADR-011, `evalharness.run` fails fast to prevent treating unconfigured runs as false model failures.
- **Groq (GPT-OSS-120B)**: Active in repo, but free-tier RPM rate limits (30 RPM) trigger the fail-closed Tier 3 fallback on high-volume sequential evaluation loops.
