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

- **AI-1 output schema extended**: `DiagnosisProposal` now requires
  `expected_outcome` (probability the proposed action succeeds — a different axis
  from `confidence`, which is about the diagnosis), `risks` (closed-enum
  `RiskFlag` list), and `missing_information` (closed-enum list). All required, no
  defaults — see DECISIONS.md ADR-013. Every construction site across the
  codebase updated; 34/34 tests still pass.
- **Found and fixed a real bug verifying this live, not from the mocks**:
  `openai/gpt-oss-120b` is a reasoning model — at the old `max_tokens=400` with no
  `reasoning_effort` set, every real call hit `finish_reason: "length"` with
  ~90% of the token budget burned on hidden reasoning, truncating the JSON and
  silently falling through to fail-closed on **every single request**. Fixed
  (`reasoning_effort="low"`, `max_tokens=600`); confirmed live with genuinely good,
  schema-compliant output on two real cases, `fallback_tier=0` on both. Claude's
  `max_tokens` also bumped to 600, defensively.

- **AI-1 reasoning quality improved, scoped strictly to `agent/diagnosis/`**
  (+ one line threading an existing field through `pipeline.py` — no policy or
  executor code touched). Two real "use available context" gaps closed:
  `is_recurring` was available on `PaymentFailure` but never reached
  `DiagnosisInput` at all; `downtime.instrument_match` was computed but never
  sent to the model. Three new "avoid unsupported conclusions" validation gates
  added to `prompting.validate()` (confidence requires evidence; near-certainty
  forbids outstanding missing_information; TERMINAL forbids RETRY), all following
  the existing repair-retry-then-fallback pattern, no new code path. System
  prompt updated to state the three rules explicitly. See DECISIONS.md ADR-014.
  **Honest note caught during verification**: `instrument_match` is currently
  always equal to `active` given how `active_at()` filters — that particular fix
  adds no new information today, kept for forward-compatibility and schema
  completeness, not because it currently changes model behavior.
- Verified live against 3 real cases (recurring mandate, thin-signal one-off,
  high-contact-count repeat customer): 3/3 `fallback_tier=0`, zero rule
  violations, confidence and expected_outcome diverging sensibly rather than
  collapsing to one number. Full suite 34/34.

- **AI output validation hardened — a real fail-open bug found and closed, at two
  independent layers.** `agent/policy/engine.py::evaluate()`'s final line was a
  bare fallthrough to `Action.RETRY` for anything that wasn't `STOP` — so
  `Action.RECOVERY_LINK` (a real, schema-valid enum member, reserved/unimplemented)
  would have been silently reinterpreted as a RETRY authorization instead of
  rejected. Fixed at the source (`agent/diagnosis/prompting.py::validate()` now
  rejects any action outside `{RETRY, STOP}`) and independently at the policy
  layer (a new structural guard, rule 0, denies + STOPs + records
  `UNSUPPORTED_ACTION`, deliberately not a `rules.yaml` entry since it's not a
  tunable threshold). See DECISIONS.md ADR-015.
- Also added: markdown-code-fence stripping before JSON parsing (models routinely
  wrap output in ` ```json ` despite instructions not to — parsing more tolerant,
  validation not weakened), and validation-failure reasons now surface in fallback
  `rationale` instead of being silently swallowed by `except Exception: continue`.
- **New test file `tests/test_ai_output_validation.py`** (28 tests) — explicit,
  one-to-one proof for each required category: malformed output, missing fields,
  invalid enum values (including nested `risks[].category`), impossible
  confidence (including `expected_outcome.probability_of_success`), unsupported
  actions at both layers, and total-exhaustion fail-safe behavior. Full suite:
  **62/62** (34 prior + 28 new). Verified live against the real Groq API
  afterward — the added strictness doesn't cause spurious rejection.

- **Non-AI baseline arm built and the first real A1-vs-A3 comparison run.**
  `agent/diagnosis/baseline.py` — context-blind fixed retry, a drop-in
  `DiagnosisPort` so swapping arms changes exactly one component. Selectable via
  `--provider baseline`. 6 tests assert its context-blindness so it can't drift
  into being "smart" and silently invalidate the comparison. See ADR-016.
- **Bug found doing it: the AI arm had never actually run.** `evalharness/run.py`
  never loaded `.env`, so every ambiguous case failed closed to UNKNOWN with a
  missing-API-key error — macro-F1 0.000, reading as catastrophic model failure
  rather than missing config. Fixed with a minimal stdlib `load_dotenv()` plus a
  fail-fast guard that now refuses to run `--provider groq|claude` without a key.
- **Comparison result — the AI arm does not currently beat the baseline, and this
  corpus cannot answer whether it would.** Baseline incremental ₹5.27M/1,000 vs
  AI ₹4.34M/1,000, CIs overlapping almost entirely. More importantly, the
  macro-F1 comparison is measuring nothing: `datagen/generate.py::_pick_true_class()`
  assigns AMBIGUOUS labels with **zero dependence on any input feature**, so
  chance is the ceiling by construction — observed scores (0.151 baseline, 0.260
  AI) match the arithmetic predictions for majority-guessing and
  proportional-guessing against random labels almost exactly.

- **Policy engine v2 (ADR-017).** Decisions reduced to **ALLOW / DENY / REVIEW**
  as specified — `DEFER` folded into ALLOW (timing lives in `execute_at`, the fact
  of deferral in `fired_rules`), `DOWNGRADE` deleted as inert. Every decision now
  carries rule + reason + `rules_version` + `decided_at`, the latter two **required
  with no defaults** so a Verdict cannot be constructed outside policy by accident.
  Four new gates: `REQUIRED_STATE`, `SUPPORTED_ACTION` (promoted from a hardcoded
  guard to a real rule), `DUPLICATE_ACTION`, plus `EV_FLOOR` and `CONFIDENCE_FLOOR`
  enabled. `rules.yaml` → version 2. **`REVIEW` routes to `QUARANTINED`, which was
  previously an unreachable dead state** (flagged in `docs/00_project_state.md`).
- **New test file `tests/test_policy_engine.py`** (21 tests) covering all six
  required scenarios — valid / excessive / low-confidence / duplicate / economic
  failure / missing required state — each asserting *which rule* produced the
  decision, not just the decision, since rule order is the safety argument.
- **Architecture review done; one real LLM-bypass bug found and fixed.**
  `proposed_delay_minutes` is an unbounded LLM-controlled integer flowing into
  `timedelta()`; confirmed empirically that `timedelta(minutes=10**15)` raises
  `OverflowError`, so a model could crash the policy function rather than pass it.
  Fixed with a `max_delay_minutes` clamp. Direction was already safe (the existing
  floor meant the model could only delay, never accelerate), so this was an
  availability hole, not a spend hole.
- Verified there is **exactly one production executor call site** and **exactly one
  production `Verdict` construction site** — the LLM → proposal → policy → executor
  chain holds with no bypass. `EV_FLOOR` was deliberately built to ignore the
  model's own `probability_of_success`, which would otherwise have let it inflate
  past a financial control. Remaining known gap, reported not fixed: `Verdict` is a
  plain Pydantic model, so nothing cryptographically proves provenance — no
  exploitable path today, and out of scope for this pass.

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

1. **Fix AMBIGUOUS label generation — now the top blocker.** Done above: ran the
   real corpus comparison, and it surfaced that
   `datagen/generate.py::_pick_true_class()` draws ambiguous labels independently
   of every input feature, so no model can beat chance on that subset and the
   whole "does AI add value?" question is unanswerable with this corpus. Ambiguous
   labels need to depend on latent state a model could plausibly infer (downtime
   co-occurrence, attempt history, amount band) while staying genuinely ambiguous
   to a pure reason-lookup. **Do this before re-running any arm comparison, and do
   not tune it until the AI wins** — precisely what `eval/PREREGISTRATION.md`
   exists to prevent. The sealed `data/dataset/eval/` split stays untouched.
2. **Day 2 — Razorpay test-mode spike.** Real keys are now in `.env`; get one
   genuine order → failure → payment-link → capture cycle working end to end.
   Closes the field's most-cited gap (`research/COMPETITORS.md` E17).
