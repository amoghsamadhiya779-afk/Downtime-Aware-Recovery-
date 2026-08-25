<!-- last_verified: 2026-08-25 -->

# State

**Read this first on resume.** Rewritten (not appended to) at every session close —
it had grown into a 300-line changelog that opened with a stale test count and a
false claim that nothing was committed. History belongs in `DECISIONS.md`; this
file answers only "where are we now and what's next."

---

## At a glance

| | |
|---|---|
| **Deadline** | 5 Sep 2026 · **11 days left** |
| **Track** | 03 — AI Revenue Recovery |
| **Phase** | 1 complete and hardened. Phase 2 not started. |
| **Tests** | **321 passing**, 16 files |
| **ADRs** | 21 |
| **Branch** | `policy-engine-v2-and-baseline` (1 commit pushed; PR not opened — `gh` not installed) |
| **Uncommitted** | Yes — ADR-018/019/020/021 work (contracts, executor, state machine, feature-conditioned labels) |
| **Biggest blocker** | Zero real Razorpay API calls (test-mode keys sit unused in .env) |

---

## Build sequence progress

Against the 11-day plan in the approved plan file:

| Day | Deliverable | Status |
|---|---|---|
| 0 | Context files + pre-registration | ✅ Done |
| 1 | Golden set, then generator + hidden labels | ⚠️ Generator done (two, see *Known debt*); **golden set never built** |
| 2 | Razorpay test-mode spike | ❌ **Not started** — keys are in `.env`, unused |
| 3 | Policy engine + rules, LLM stubbed | ✅ Done, then rebuilt as v2 (ADR-017) |
| 4 | Diagnosis layer, structured output, validation | ✅ Done (ADR-013/014/015) |
| 5 | Downtime replay, executors, idempotency, audit | ✅ Done, hardened (ADR-018/019/020) |
| 6 | Cohorts, holdout, ₹ ledger | ✅ Done |
| 7 | Eval harness, confusion matrix, sensitivity sweep | ⚠️ Harness done; **sweep + ablation arms not built** |
| 8 | Minimal web UI | ❌ Not started |
| 9 | Failure gallery, kill switch, shadow mode | ⚠️ Kill switch done; shadow mode cut (ADR-008); gallery not built |
| 10 | Architecture doc + README with honest limits | ✅ `ARCHITECTURE.md` + `docs/00,01,03,06` exist; **README completed** |
| 11 | 5-min pitch video, submit | ❌ Not started |

**Roughly:** the decision core is done and unusually well-tested. The *submission
artifacts* (README, video, real-API proof) are the thin part, and they are what
the panel actually sees.

---

## What exists

**`agent/`** — ingest → triage → diagnosis → policy → executor, with an
append-only hash-chained audit log.
- `diagnosis/` — `DiagnosisPort` with 4 implementations: `claude`, `groq_diagnosis`
  (free tier, live-verified), `baseline` (non-AI A1 arm), `stub` (+ adversarial fixture).
  Shared prompt/validation/fallback in `prompting.py` so providers cannot drift.
- `policy/` — 9 ordered gates, ALLOW/DENY/REVIEW, thresholds in `rules.yaml` v2.
- `executors/` — typed action contracts (`contracts.py`), `SimulatedExecutor` only.
- `state.py` — 9-state machine, terminality derived from the transition table.

**`datagen/` + `scripts/`** — two corpus generators (see debt), a schema/business-logic
validator, `gen.py`, `demo.py`, `docs_check.py`.

**`evalharness/`** — incremental ₹ vs holdout with bootstrap CI, ambiguous-only
macro-F1, safety invariants, and a mandatory adverse-findings section.

**Docs** — `CLAUDE.md`, `PRODUCT_THESIS.md`, `ARCHITECTURE.md`, `DECISIONS.md` (20 ADRs),
`EVIDENCE.md`, `research/COMPETITORS.md`, `eval/PREREGISTRATION.md`, `docs/00,01,03,06`.

---

## Blockers, in priority order

**1. Zero real Razorpay API calls.** Test-mode keys sit unused in `.env`. This is
the field's most-cited gap (`research/COMPETITORS.md` E17: no sampled competitor
touches real APIs) and the load-bearing answer to a panel asking "is this real or
simulated?"

**2. `ClaudeDiagnosis` never run against the real API** — only mocked.
`GroqDiagnosis` has run live, on hand-built cases and one corpus pass.

*(Note: AMBIGUOUS label generation blocker resolved in ADR-021 with feature-conditioned posterior).*

---

## Known debt (accepted, not forgotten)

- **Two dataset lineages, unreconciled.** `data/dev.db` (SQLite, `datagen/`, what
  `evalharness` reads) vs `data/dataset/dev|eval/` (JSON, `scripts/generate_data.py`,
  what `validate_data.py` reads). Documented in `docs/06_evaluation.md` rather than
  papered over. Unify or formally separate before Phase 3.
- **6 of 15 policy rules are disabled placeholders** with reserved ids/order.
- **E12/E13/E15 (NPCI retry cap, execution windows, TRAI quiet hours) are
  secondhand** — taken from a competitor repo, not a primary source. `ATTEMPT_CAP`
  runs on them and is flagged `verified: false`; **no compliance claim may be made**
  anywhere until primary sources land in `EVIDENCE.md`.
- `Verdict` is a plain Pydantic model — nothing cryptographically proves it came
  from `evaluate()`. No exploitable path today; required fields removed the
  accidental one.
- No scheduler process, no web UI, no circuit breaker, no shadow mode (cut, ADR-008).
- Phase 3 entirely: ablation arms A0–A3, negative control S3, sensitivity sweep,
  calibration (ECE/Brier).

---

## Environment (hard-won, don't re-derive)

- **Use `py -m venv .venv`**, not `python -m venv` — bare `python` resolves to a
  POSIX-layout interpreter and produces `.venv/bin/`, breaking every Windows path.
- **Invoke via `-m module` from the project root.** Direct script-path invocation
  reproducibly fails with `AttributeError: module 'inspect' has no attribute
  'signature'` inside `typing_extensions`. Not fully diagnosed; the workaround is
  reliable and every proven command uses it.
- `make` is **not** available in this shell — use `.venv\Scripts\python.exe` directly.
- `gh` is **not** installed — PRs must be opened in the browser.
- Credentials live in `.env` (gitignored). They have twice been pasted into
  `.env.example` (the committed template) by mistake — **check that file before
  every commit.**

---

## Next actions

1. **Fix AMBIGUOUS label generation** (blocker 1). Make labels depend on latent
   state a model could plausibly infer — downtime co-occurrence, attempt history,
   amount band — while staying genuinely ambiguous to a pure reason-lookup. Then
   re-run the arm comparison. The sealed `data/dataset/eval/` split stays untouched.
2. **Razorpay test-mode spike** (blocker 2): one genuine order → failure →
   payment-link → capture cycle.
3. **Write the README** (blocker 3), quoting generated numbers only.
4. Open the PR for the pushed branch, and commit the ADR-018/019/020 work.
