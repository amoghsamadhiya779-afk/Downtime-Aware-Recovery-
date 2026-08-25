<!-- last_verified: 2026-08-25 -->

# State

Rewritten every session close. Read this first on resume.

## Stage

**Phase 1 (vertical slice) — complete, self-reviewed, fixes applied AND
re-verified. Full test suite passes (34/34).** A real LLM (Groq) has now been
exercised end-to-end for the first time this session, resolving the "AI necessity
unproven" gap partially (one working call, not yet a corpus-scale measurement).

## Done

- All Day-0 context files on disk: `CLAUDE.md`, `PRODUCT_THESIS.md`,
  `ARCHITECTURE.md`, `DECISIONS.md`, `EVIDENCE.md`, `STATE.md` (this file),
  `research/COMPETITORS.md`, `eval/PREREGISTRATION.md`. Plus `docs/00-01, 03, 06`
  (reverse-engineered as-built docs + the dataset-split doc).
- Full Phase 1 code, including this session's additions: `agent/diagnosis/prompting.py`
  (shared prompt/validation/fallback logic), `agent/diagnosis/groq_diagnosis.py`
  (second DiagnosisPort backend), `scripts/generate_data.py` (portable JSON
  dataset generator), `scripts/validate_data.py` (schema + business-logic
  validator), `data/dataset/dev/` and `data/dataset/eval/` (the held-out split,
  see `docs/06_evaluation.md`).
- **`.venv` created with the Windows `py` launcher** (not plain `python`). Project
  installed editable with dev deps, plus `groq`.
- **Full suite: 34/34 pass**, including the two new provider test files
  (`test_claude_diagnosis.py`, `test_groq_diagnosis.py`, 5 tests each) and
  `test_idempotency.py`. `test_policy.py` still passes with `anthropic` uninstalled.
- `make gen && make eval` still byte-for-byte reproducible; `scripts/generate_data.py`
  independently confirmed reproducible across two runs too.
- **`GroqDiagnosis` verified against the real API, not just mocked.** One live call
  (ambiguous UPI failure, active downtime) returned `TRANSIENT_INFRA`, confidence
  0.92, `RETRY` at 5min, evidence citing only real input fields, `fallback_tier=0`.
  First real-model result of any kind this session — every number before this used
  `StubDiagnosis`.
- **Two real bugs found and fixed via the mock-testing rebuild**, both in the test
  fixtures, not the production code: a shared-response-list mock bug (fresh SDK
  client per attempt was silently handed a fresh, undrained copy each time) that
  made the "repair succeeds" tests assert the wrong thing without anyone noticing,
  since they'd never actually been run. See DECISIONS.md ADR-011.
- **One real bug found and fixed in `scripts/generate_data.py`**: mandate_id and
  customer_id were drawn independently, letting two unrelated customers "share" a
  mandate. Fixed by binding mandates to a fixed (customer, method, instrument)
  triple at pool creation — caught by inspecting actual output, not by code review.
  A follow-on fix was needed too: weighting the mandate pool by `RECURRING_RATE`
  alone (rather than `METHOD_WEIGHTS × RECURRING_RATE`) drifted the whole corpus's
  method mix (emandate to 34%) — caught and corrected the same pass.
- **One real bug found and fixed in `scripts/validate_data.py`**: the first
  temporal-consistency check assumed same-mandate-same-reason records always
  belong to one sequence; two independent episodes sharing a reason by
  coincidence is realistic, not corrupt. Rewrote to track attempt-number
  continuity per episode (handles even interleaved episodes) instead.
- **Credential hygiene**: real Razorpay + Groq keys twice landed in `.env.example`
  (the public template) instead of `.env` (gitignored) — caught both times before
  any commit happened (no `.env` — i.e. no git repo — exists yet), moved to `.env`,
  template restored to placeholders.
- **Data audit pass (this session's most recent work)**: queried `data/dev.db`
  directly rather than starting from a code review, and found a real bug —
  `datagen/generate.py` drew `is_recurring` and `mandate_id` from two *independent*
  `rng.random() < 0.3` calls, so they disagreed on 130/300 cases (43.3%). Fixed
  (derive `mandate_id` from the single `is_recurring` draw), `data/dev.db` +
  `data/dev_ground_truth.jsonl` regenerated and re-verified clean: 0 mismatches, 0
  orphans, 0 TERMINAL-with-nonzero-probability, 0 CLEAN-class disagreements, 0
  instrument/method mismatches. See DECISIONS.md ADR-012. Full suite still 34/34
  after the fix. Also removed: stale `eval/report.md` (predated every fix this
  session — deleted rather than regenerated, since regenerating it is real
  evaluation work, deferred to resume) and `data/synthetic/` (redundant, superseded
  by `data/dataset/dev/`).

## Currently broken / not yet built

- **`ClaudeDiagnosis` has still never been run against the real Anthropic API** —
  only mocked. `GroqDiagnosis` has, once, on a single hand-built case.
- **No corpus-scale diagnosis measurement yet.** The one live Groq call proves the
  mechanism works; it does not establish macro-F1 or answer "is AI-1 necessary."
  That needs a real `evalharness/run.py --provider groq` pass against a generated
  corpus with ground truth (`data/dev.db`, built by the older `datagen/` pipeline —
  note `data/dataset/dev|eval` from this session are plain JSON and are NOT yet
  wired into `evalharness/run.py`, which still reads `data/dev.db`).
- No real Razorpay test-mode calls yet (Day 2 work), even though real Razorpay
  test-mode keys are now in `.env`. `RECOVERY_LINK` action is a reserved enum
  value, not implemented.
- 6 of 11 policy rules are disabled placeholders — unchanged this session.
- No scheduler process (C6), no web UI, no shadow-mode executor (removed as scope
  creep — ADR-008), no circuit breaker.
- Ablation arms (A0–A3), negative control (S3), sensitivity sweep, calibration
  (ECE/Brier) — all Phase 3.
- **Two dataset lineages now coexist and are not unified**: `data/dev.db`
  (SQLite, built by `datagen/generate.py`, what `evalharness/run.py` actually
  reads) and `data/dataset/dev|eval/` (JSON, built by `scripts/generate_data.py`,
  what `scripts/validate_data.py` reads). `docs/06_evaluation.md` documents this
  explicitly rather than pretending they're the same thing.
- `git init` has not been run. Nothing is committed anywhere yet.

## Known issues (environment)

- Bare `python` on PATH resolves to a POSIX-layout interpreter and breaks the
  Windows venv layout. **Use `py -m venv .venv`.**
- **New this session**: direct script-path invocation
  (`.venv\Scripts\python.exe C:\full\path\to\script.py`) reproducibly fails with
  `AttributeError: module 'inspect' has no attribute 'signature'` deep inside
  `typing_extensions`, while `-m module_name` invocation from the project root
  works reliably every time. Root cause not fully diagnosed (not worth the further
  time); workaround is to always invoke via `-m` from the project root, which is
  what every proven-working command this session has used.
- `make` was never confirmed available in this shell; all commands run via
  `.venv\Scripts\python.exe` directly.

## Unresolved questions

- Primary-source citations for E12/E13/E15 (NPCI/TRAI constants) — still secondhand.
- Whether checkout-abandonment is in scope. Recommendation stands: cut it.
- Whether to unify `data/dev.db` and `data/dataset/*` into one lineage before Phase 3,
  or keep them deliberately separate (portable JSON demo/validation set vs. live
  pipeline corpus). Not yet decided.

## Next highest-value action

1. **Run `evalharness/run.py --provider groq` against a real corpus** (not just one
   hand-built case) to get an actual macro-F1 number from a real model. This is the
   single most important unresolved claim in `docs/03_product_thesis.md`.
2. **Day 2 — Razorpay test-mode spike.** Real keys are now in `.env`; get one
   genuine order → failure → payment-link → capture cycle working end to end.
   Closes the field's most-cited gap (`research/COMPETITORS.md` E17).
