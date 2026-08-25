<!-- Reverse-engineered from the repository as it stands on disk. Describes what IS
     built, not what was planned. Where this differs from the root-level PRODUCT_THESIS.md
     / ARCHITECTURE.md / STATE.md, THIS document defers to the actual code — those
     other files mix intent with status and should not be trusted as an as-built spec. -->

# Project State (as-built)

Snapshot basis: direct inspection of every `.py` file, `agent/policy/rules.yaml`,
`pyproject.toml`, and `Makefile` in the repository. No tests were executed to
produce this document — it is derived from static reading, per instruction.

## What exists on disk

```
agent/
  models.py            all boundary Pydantic schemas
  clock.py              Clock protocol, RealClock, VirtualClock
  db.py                  sqlite3 schema + two DB-enforced triggers
  state.py               case row CRUD, state machine, transition()
  audit.py                append-only hash-chained event log
  downtime.py             DowntimeStore: add() / active_at() / context_at()
  triage.py                deterministic reason -> class lookup table
  diagnosis/
    port.py                 DiagnosisPort protocol, DiagnosisInput
    stub.py                   StubDiagnosis, AdversarialDiagnosis, UnknownDiagnosis
    claude.py                  ClaudeDiagnosis (real API call + fallback ladder)
  policy/
    rules.yaml                 11 rules defined, 5 enabled
    engine.py                    evaluate() — pure function
  executors/
    port.py                       ExecutorPort protocol
    simulated.py                    SimulatedExecutor only (NullExecutor removed)
  ledger.py               assign_cohort() — seeded, hash-based
  pipeline.py             ingest() + process_case() — wires every layer together

datagen/
  schema.py              GroundTruth, BatchManifest (hidden-label types)
  generate.py             seeded corpus generator + DB/ground-truth writers

evalharness/
  metrics.py              all scoring functions + build_report()
  run.py                    CLI: replay a corpus, write eval/report.md

scripts/
  gen.py                  regenerates data/dev.db (n=300, seed=42)
  demo.py                  two hand-built cases, prints full decision traces
  docs_check.py             greps *.md for rule-id citations against rules.yaml

tests/                   7 files, see "Test inventory" below
docs/                    this directory
research/COMPETITORS.md
pyproject.toml, Makefile, conftest.py, .env.example, .gitignore
CLAUDE.md, PRODUCT_THESIS.md, ARCHITECTURE.md, DECISIONS.md, EVIDENCE.md, STATE.md
eval/PREREGISTRATION.md
```

No `web/` directory exists despite being named in `CLAUDE.md`'s layout section — the
UI is not built. No `.git` directory — nothing is committed to version control yet.

## Test inventory (7 files, as of last edit — not re-run since)

| File | What it actually covers |
|---|---|
| `test_policy.py` | 8 tests, hypothesis-based, on `agent/policy/engine.py`. Imports nothing from `agent/diagnosis/claude.py`. |
| `test_downtime.py` | 7 tests on `agent/downtime.py` boundary conditions (begin/end inclusivity, null-end, instrument/method mismatch, resolved status). |
| `test_isolation.py` | 1 test — AST-walks every file under `agent/` and asserts none imports `datagen`. |
| `test_adversarial.py` | 1 test — 60 cases, up to 10 processing rounds, `AdversarialDiagnosis` + an always-fail outcome function, asserts zero holdout contamination and no attempt exceeds its method's cap. |
| `test_audit.py` | 5 tests — chain verification, both DB triggers (`UPDATE`/`DELETE` raise `sqlite3.IntegrityError`, not `OperationalError`), tamper detection after the trigger is manually dropped, and `replay()` vs. state-store equality. |
| `test_idempotency.py` | 2 tests (added this session) — duplicate `execute()` calls on the same verdict don't re-draw an outcome or insert a second `actions` row; a genuinely new attempt (post attempts-increment) does. |
| `test_claude_diagnosis.py` | 5 tests (added this session) — `ClaudeDiagnosis` exercised against a monkeypatched fake `anthropic.Anthropic` client (no network): tier-1 direct success, tier-1 repair-after-invalid-JSON, evidence-groundedness rejection, tier-2 taxonomy-prior fallback, tier-3 fail-closed on a genuinely unseen reason. |

**As of the last actual run** (before this session's 5 fixes + 1 deletion): 22/22
passing, including with the `anthropic` package uninstalled. **The two new test
files and the `DOWNTIME_DEFER`/`policy_veto_rate` code changes have not been
re-executed** — this document does not claim they pass, only that they exist and
what they assert.

## Discrepancies found by reading the code (not previously documented elsewhere)

1. **`agent/policy/rules.yaml` lines 11–13** comment: *"Checked twice independently:
   policy rule 1, and again pre-dispatch in the executor."* The second check does
   not exist anywhere in `agent/executors/simulated.py` — `SimulatedExecutor.execute()`
   has no kill-switch check at all; it trusts the caller passed an executable
   verdict (it does raise `ValueError` if `not verdict.is_executable`, which is a
   *different* guarantee than a second kill-switch read). The comment overstates
   what's implemented. `ARCHITECTURE.md` §9 already correctly lists this as
   "Phase 2" in its own table, so the inaccuracy is localized to the YAML comment.
2. **`Action.RECOVERY_LINK`** exists as an enum member (`agent/models.py:38`) but
   has zero behavior anywhere — no policy rule can produce it, no executor handles
   it. It is a reserved name, not a partially-built feature.
3. **`Decision.DOWNGRADE`** exists as an enum member (`agent/models.py:45`) and is
   never returned by `evaluate()` in the current rule set (no enabled rule uses it
   — `CONTACT_CAP`, which would, is disabled). Same status as above: reserved, inert.
4. **`agent/state.py`'s `QUARANTINED` state** is defined in the state machine and in
   `TERMINAL_STATES`, but nothing in `agent/pipeline.py` ever transitions a case
   into it. Unreachable in the current code path.
5. **`CaseState` values `SCHEDULED` and `EXECUTING`** are real, transitioned-through
   states, but `agent/pipeline.py:process_case()` executes them synchronously in
   the same function call — there is no observable window where a case sits in
   `SCHEDULED` waiting on a scheduler, because no scheduler process exists.

## Commands that exist and were confirmed to run this session

```
py -m venv .venv                              # NOT `python -m venv` — see below
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q          # 22 passed, confirmed pre-fix
.venv\Scripts\python.exe scripts\gen.py        # writes data/dev.db + data/dev_ground_truth.jsonl
.venv\Scripts\python.exe -m evalharness.run    # writes eval/report.md
.venv\Scripts\python.exe scripts\demo.py       # prints two decision traces to stdout
```

The `Makefile` targets (`make setup`, `make gen`, `make test`, `make eval`, `make
demo`, `make docs-check`, `make clean`) are written but `make` itself was never
invoked this session — all verification used the `.venv\Scripts\python.exe`
invocations directly. Whether GNU Make is available on this machine is unconfirmed.

## Environment fact (confirmed by reproduction, not assumption)

On this machine, `python -m venv .venv` (bare `python` on PATH) produces a
POSIX-style layout (`.venv/bin/`), not the Windows layout the Makefile assumes.
`py -m venv .venv` (the Windows launcher) produces the correct `.venv/Scripts/`
layout. This was hit and fixed once this session.

## Data artifacts currently on disk

`data/dev.db` and `data/dev_ground_truth.jsonl` exist from the last verification
run and are **already fully processed** (every case is in a terminal state).
Running `evalharness.run` against them again without first regenerating raises
`agent.state.IllegalTransition` — this was hit and is not a bug, it's the expected
behavior of a state machine with no re-entrant transitions out of terminal states.
`scripts/gen.py` must be re-run before `evalharness.run` each time.

## What "Phase 1 complete" actually means in this codebase

- The five-layer pipeline (ingest → triage → diagnose → policy → execute → audit)
  runs end to end, in one process, synchronously, against SQLite.
- Diagnosis is real code (`ClaudeDiagnosis`) but every measured number to date used
  `StubDiagnosis`, a hardcoded placeholder that always guesses `TRANSIENT_INFRA` on
  ambiguous cases. `ClaudeDiagnosis` has unit coverage against a fake client, not
  against the real Anthropic API.
- Execution is `SimulatedExecutor` only — outcomes are drawn from a hidden,
  generator-authored probability, not from any real payment system.
- 5 of 11 designed policy rules are enabled. The other 6 exist in `rules.yaml` as
  disabled entries with reserved `order` values.
- No web UI, no scheduler process, no circuit breaker, no calibration, no ablation
  arms, no sensitivity sweep exist in any form — not stubbed, not partially built.
