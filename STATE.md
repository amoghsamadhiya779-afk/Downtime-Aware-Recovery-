<!-- last_verified: 2026-08-25 -->

# State

**Read this first on resume.** Rewritten at every session close. History belongs in `DECISIONS.md`; this file answers only "where are we now and what's next."

---

## At a glance

| | |
|---|---|
| **Deadline** | 5 Sep 2026 · **11 days left** |
| **Track** | 03 — AI Revenue Recovery |
| **Phase** | Multi-arm live evaluation complete, real Razorpay API integration complete, UI dashboard shipped. |
| **Tests** | **330 passing**, 19 test files (0 failures, 24.18s runtime) |
| **ADRs** | 23 |
| **Branch** | `main` |
| **Real APIs** | **Razorpay Test API connected** (`agent/executors/live.py`, `data/golden/`); **Groq LLM connected** (`agent/diagnosis/groq_diagnosis.py`) |
| **Biggest blocker** | None — core blockers unblocked |

---

## Build sequence progress

Against the 11-day plan:

| Day | Deliverable | Status |
|---|---|---|
| 0 | Context files + pre-registration | ✅ Done |
| 1 | Golden set, then generator + hidden labels | ✅ Done (`data/golden/` grounded fixtures, generator v0.2.0) |
| 2 | Razorpay test-mode API integration | ✅ Done (`agent/executors/live.py`, `scripts/capture_golden.py`) |
| 3 | Policy engine + rules, LLM stubbed | ✅ Done (v2 rules engine, ADR-017) |
| 4 | Diagnosis layer, structured output, validation | ✅ Done (ADR-013/014/015, live Groq runner) |
| 5 | Downtime replay, executors, idempotency, audit | ✅ Done (`LiveRazorpayExecutor`, SHA-256 hash chaining) |
| 6 | Cohorts, holdout, ₹ ledger | ✅ Done (25% holdout trigger guard, ₹ ledger) |
| 7 | Eval harness, confusion matrix, ablation arms | ✅ Done (`eval/comparison.md`, S1/S2/S3 multi-scenario reports) |
| 8 | Minimal web UI | ✅ Done (2,172-line dashboard in `web/`, 7 KPI cards, 9-phase drawer) |
| 9 | Failure gallery, kill switch, shadow mode | ✅ Done (`scripts/demo_controls.py`, kill switch in `rules.yaml`) |
| 10 | Architecture doc + README with honest limits | ✅ Done (`ARCHITECTURE.md`, `README.md` verified via `docs_check.py`) |
| 11 | 5-min pitch video, submit | ⏳ Next step |

---

## What exists

**`agent/`** — ingest → triage → diagnosis → policy → executor, with an append-only hash-chained audit log.
- `diagnosis/` — `DiagnosisPort` with 4 implementations: `claude`, `groq_diagnosis` (live `openai/gpt-oss-20b` with adaptive rate-limiting), `baseline` (context-blind A1 ablation), and `stub` (A3 heuristic).
- `policy/` — 9 ordered gates, ALLOW/DENY, thresholds in `rules.yaml`.
- `executors/` — `LiveRazorpayExecutor` (real `/v1/payment_links` and `/v1/orders` dispatches) and `SimulatedExecutor` (eval harness replay).
- `state.py` — 9-state machine, optimistic concurrency versioning, SQLite triggers for cohort immutability and append-only audit.

**`data/` & `datagen/`** — feature-conditioned generator (v0.2.0, ADR-021), grounded `data/golden/` Razorpay fixtures, and multi-scenario corpora (`dev`, `test`, `calibration` across S1, S2, S3).

**`evalharness/` & `eval/`** — incremental ₹ vs holdout with bootstrap CI, ambiguous-only macro-F1, secondary metrics, sealed corpus anti-cherry-picking logs (`*_scoring_log.jsonl`), and auto-generated `eval/comparison.md`.

**`scripts/` & `web/`** — `docs_check.py` (numeric provenance + rule ID check), `serve_dashboard.py` (hand-rolled CSS executive dashboard), `demo_controls.py` (3 deterministic scenarios), `capture_golden.py` (live Razorpay capture).

---

## Known debt (accepted, not forgotten)

- **E12/E13/E15 (NPCI retry cap, execution windows, TRAI quiet hours) are secondhand** — `ATTEMPT_CAP` runs on them and is flagged `verified: false`; compliance disclosure included in all evaluation reports.
- `Verdict` is a plain Pydantic model — required fields and immutable frozen dataclass prevent accidental bypassing.
- Claude model arm unconfigured pending Anthropic API key; Groq model arm actively produces live inference numbers.

---

## Next actions

1. **Record 5-minute product walkthrough video** demonstrating:
   - 9-phase transaction recovery trace (`python scripts/demo_controls.py --scenario successful_recovery`).
   - Zero-LLM Policy Gate blocking adversarial AI recommendation (`--scenario unsafe_ai_blocked`).
   - Real-time Executive Dashboard (`python scripts/serve_dashboard.py`).
   - Live Razorpay Payment Link generation (`agent/executors/live.py`).
2. **Submit Track 03 Project Repository**.
