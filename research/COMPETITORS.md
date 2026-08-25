<!-- last_verified: 2026-08-25 -->

# Competitive Field

Snapshot: 25 Aug 2026. **218 public GitHub repositories** matched "razorpay
buildathon" (GitHub repo search), many updated within minutes of the search —
this is a live, crowded field, not a static one. Deep-sampled 7 repos across
Tracks 01–04; skimmed ~15 more by description. Not re-verified since — treat
specifics as a point-in-time snapshot, not a current standing.

## Deep-sampled repos

| Project | Track | Mechanism | Headline metric | Notable |
|---|---|---|---|---|
| `atharavmahangade-spec/mandate-rescue` | 03 | NPCI-constrained scheduling, deterministic + LLM split | 91.8% vs 29.6% naive baseline, ₹9.4L uplift, n=100 | Regulatory constants as code; explicit naive baseline; documents 1 non-recovered case |
| `Hem60/vakil` | 02 | Chargeback fight/fold economics | P 0.700 R 0.903 F1 0.789, **Brier 0.259→0.175** | Only sampled project with calibration; hash-chained ledger; provenance-gated citations |
| `Adithya-workspace/Revive-ai` | 03 | detect→diagnose→policy→execute→verify, LangGraph | ₹6.86L "verified recovered" of ₹3.06Cr at risk (6.7%) | "AI proposes, policy disposes"; 12,189 audit events |
| `Aahan0605/Razorpay_ps` | 02 | ML classifier + LLM verifier, code-clamped bands | P 0.769 R 0.727, PR-AUC 0.789, 24 FPs | Best-documented honest-limitations section; caught a real leakage bug via a unit test |
| `Medha-shrma/Recon__AI-` | 04 | 3-layer match: exact→fuzzy→Claude on ambiguous only | 94.2% match, 60/21/14 split | Cost-aware LLM escalation done right |
| `abhishekck31/RevenueRadar` | 03 | Multi-agent (3 specialists + orchestrator) | **None reported** | Multi-agent theater — no metrics despite the complexity |
| `Jagadeesh58/chargeback-risk-engine` | 02 | — | claims "honest P/R on held-out synthetic set" | README not fully retrievable at sample time |

## Field-wide patterns

**Recurring strengths** — the field has already internalized the published bars:
"AI proposes, policy disposes" gating is near-universal; seeded, reproducible
synthetic datasets are standard; honest exception/failure lists are common; several
projects reserve LLM calls for the ambiguous tail rather than every case.

**Recurring weaknesses — this is where this project's differentiation lives:**

| # | Weakness | Why it's exploitable |
|---|---|---|
| 1 | **Zero real Razorpay API usage.** Every sampled project simulates end to end | This project's Day 2 goal directly closes this |
| 2 | **Self-graded simulators.** Same author writes the data generator and the outcome model | `datagen/`/`agent/` import isolation (invariant 7) + declared response-model assumption exist because of this |
| 3 | **No randomized holdout.** Everyone reports gross ₹, nobody reports incremental | Primary KPI (ADR-002) is built specifically to close this gap |
| 4 | **Payment Downtime API unused.** Not one sampled project consumes it | `agent/downtime.py` + `DOWNTIME_DEFER` rule is the whole mechanism this gap enables |
| 5 | **LLM layer unevaluated.** Confidence gates used without calibration evidence (only `vakil` calibrates) | Phase 3 commits to ECE/Brier, raw vs. calibrated |

## Benchmarks to beat

`mandate-rescue` (regulatory-constant discipline, explicit baseline) and `vakil`
(calibration, cryptographic audit trail) are the strongest sampled entries. Both
share the same exploitable gap: **neither can prove their recovered money was
incremental**, and neither touches a real Razorpay surface. Beating them on those
two axes specifically — not on feature count — is the plan.

## Inference

Track popularity, by sample distribution (not a published figure): **03 ≫ 02 > 04 ≫ 01.**
Track 01 was conspicuously sparse in the sample — one conversational-checkout repo
surfaced (`VeerGetGit/RazorPay_agentic_checkout`).
