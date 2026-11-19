<!-- last_verified: 2026-08-25 -->

# Project State (As-Built)

## 1. Phase Status
- **Current Phase:** Final Verification & Submission Preparation
- **Completed Phases:**
  - **Phase 0–1 (Core & Evaluation):** Ingest, taxonomy triage, policy engine (9 rules), fail-closed fallback ladder, state machine, SHA-256 audit log, synthetic data generator (v0.2.0), pre-registered evaluation harness.
  - **Phase 2 (Platform Integration & AI):** Live Razorpay Test API integration (`LiveRazorpayExecutor`), golden fixtures (`data/golden/`), live multi-arm LLM evaluation (Claude Sonnet 5, Groq `openai/gpt-oss-20b`), executive web dashboard (`dashboard/` on port 8000), CI workflow (`.github/workflows/ci.yml`).

## 2. Final Architecture
Single unified pipeline (`agent/pipeline.py`) across live execution and offline replay:
- **Triage Layer (`agent/triage.py`):** Deterministic classification for known reasons; isolates ambiguous tail for AI.
- **Diagnosis Layer (`agent/diagnosis/`):** Pure-function LLM reasoning (`ClaudeDiagnosis`, `GroqDiagnosis`) behind `DiagnosisPort` protocol, with shared evidence-groundedness validation and 3-tier fallback ladder.
- **Zero-LLM Policy Gate (`agent/policy/`):** Sovereign deterministic veto over AI proposals via `rules.yaml` v2 (attempt caps, downtime deferral, holdout guard).
- **Execution & Storage (`agent/executors/`, `agent/audit.py`, `agent/state.py`):** Typed action contracts, SHA-256 idempotency key deduplication, 9-state machine with SQLite triggers, append-only hash-chained audit trail.

## 3. Final Evaluation Metrics
Multi-arm evaluation across `dev` corpus (n=300, seed 42, Generator v0.2.0):
- **Primary KPI:** Incremental ₹ recovered vs randomized 25% holdout:
  - **Stub Heuristic (A3):** ₹4,913,426 / 1k at-risk (95% CI: [₹2,885,604, ₹6,836,521])
  - **Claude Sonnet 5 (Live LLM):** ₹3,802,585 / 1k at-risk (95% CI: [₹1,540,428, ₹5,942,617])
- **Ambiguous Macro-F1:** Claude **0.372** vs Stub **0.336** (+10.7% lift) vs Context-Blind Baseline **0.000**.
- **Wasted Attempt Rate:** Claude **9.6%** vs Stub **14.2%** (32% reduction in futile retries).
- **Burst Outage Validation (S2):** 51 retries deferred past downtime; Claude achieves **0.519 Macro-F1**.
- **Safety Invariants:** 0 holdout leaks, 0 attempt cap breaches, 100% SHA-256 chain verification.

## 4. Known Limitations
1. **Synthetic Counterfactuals:** Recovery probabilities during downtime are synthetic priors based on failure taxonomy.
2. **Global Retry Caps:** Attempt limits are configured per payment method rather than dynamic per-merchant risk tier.
3. **Model Sensitivity:** Free-tier Groq model underperformed heuristic (0.153 F1), proving model choice is load-bearing.

## 5. Demo & Submission Status
- **Automated Tests:** 330/330 passing in ~25s (`pytest -q`).
- **Documentation Provenance:** Verified (`scripts/docs_check.py`).
- **Deterministic Demos:** 3 CLI scenarios (`scripts/demo_controls.py`) and Web Dashboard (`scripts/serve_dashboard.py`) 100% verified.
- **Live Proof:** Real test-mode Payment Link created (`plink_TU5tTPPXJ9K48F`) via `scripts/live_recovery_proof.py`.
- **Submission:** Ready for video recording and Track 03 submission.
