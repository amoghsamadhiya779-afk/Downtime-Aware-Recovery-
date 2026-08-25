<!-- Reverse-engineered: requirements as evidenced by what the code actually enforces
     and depends on, not as originally specified. Each item below is traceable to a
     specific file. Items with no code backing are marked UNENFORCED. -->

# Requirements (as-built)

## Runtime dependencies (from `pyproject.toml`)

| Package | Version | What actually uses it |
|---|---|---|
| `pydantic` | ≥2.6 | Every type in `agent/models.py`, `datagen/schema.py` |
| `pyyaml` | ≥6.0 | `agent/policy/engine.py:load_rules()` only |
| `anthropic` | ≥0.40 | `agent/diagnosis/claude.py` only, imported lazily inside a method — confirmed absent from every other module by `test_isolation.py`-style reasoning (not literally checked by that test, but by direct inspection: no other file has `import anthropic`) |

Dev-only: `pytest`≥8.0, `hypothesis`≥6.98. Python `>=3.11` declared; `3.12.11`
(POSIX-layout `python`) and `3.12.0` (`py` launcher) both present on the dev
machine — only the latter produces a working Windows venv.

No web framework, no ORM, no task queue, no vector store appear anywhere in the
dependency list or in any import statement in the codebase.

## Functional requirements enforced by code

### Signal ingestion

- A `PaymentFailure` requires: `case_id`, `customer_id`, `order_id`, `created_at`,
  `method` ∈ {card, netbanking, upi, emandate}, `instrument`, `amount_paise` > 0,
  `attempt_no` ≥ 1, `error` (with `code`, `source`, `step`, `reason`; `description`
  optional). Enforced by Pydantic field constraints in `agent/models.py`.
- `ingest()` (`agent/pipeline.py`) requires a `seed` and a `Rules` object at call
  time — cohort assignment is not deferrable.

### Classification (triage)

- `agent/triage.py` hardcodes 16 `reason` strings to a definite class (the `CLEAN`
  dict) and 5 `reason` strings to `AMBIGUOUS`. Any `reason` not in either set
  triages to `matched="unseen"`.
- This vocabulary is authored, not derived from any external data source — it is
  not validated against a real Razorpay error-reason list (`EVIDENCE.md` E11
  documents that no exhaustive public list exists).

### Diagnosis (AI-1)

- Only invoked when triage returns `is_ambiguous=True`. Enforced structurally in
  `agent/pipeline.py:process_case()` — the `elif tr.matched == "clean"` and `else`
  (unseen) branches construct a `DiagnosisProposal` directly without calling
  `diagnosis_port.diagnose()` at all.
- `DiagnosisPort` (`agent/diagnosis/port.py`) is a `Protocol` with a single method,
  `diagnose(inp: DiagnosisInput) -> DiagnosisProposal`. No method for tool use,
  I/O, or state exists on the Protocol — an implementation *could* technically add
  one, but nothing in `agent/pipeline.py` would ever call it.
- `DiagnosisInput` fields are: `method`, `error` (full `ErrorObj`, including
  `description`), `amount_paise`, `attempt_no`, `prior_failures`, `downtime`,
  `contact_count_7d`. **`error.description` is present on the object** but
  `agent/diagnosis/claude.py:_build_prompt()` explicitly omits it when constructing
  the prompt payload — the free-text field reaches `DiagnosisInput` but not the LLM.
- `ClaudeDiagnosis._validate()` requires every string in `evidence[]` to be a member
  of a fixed 11-name set of dotted field paths (`_evidence_fields()`); any other
  string raises `ValueError`, which the caller treats identically to a JSON parse
  failure (triggers the repair retry).
- Fallback ladder, as actually coded: 2 total attempts at calling the model
  (`for attempt in range(2)`) → on exhaustion, if `inp.error.reason` is in
  `agent/triage.py`'s `CLEAN` dict, return a `confidence=0.3` proposal sourced from
  that dict (`fallback_tier=2`) → otherwise return `UnknownDiagnosis`'s fixed output
  with `fallback_tier` forced to 3.

### Policy

- `Rules` is loaded once from `agent/policy/rules.yaml` via `load_rules()`; there is
  no runtime rule-mutation path — the only override is the `kill_switch` keyword
  argument to `load_rules()`, used by `tests/test_policy.py`.
- `evaluate()` (`agent/policy/engine.py`) requires exactly these five positional
  concerns to compute a verdict: a `DiagnosisProposal`, a `CaseView`, a `Rules`, a
  `datetime`, and a `DowntimeContext`. No database handle, no clock object, no
  network call is reachable from inside this function — confirmed by reading every
  line; it imports only `dataclasses`, `datetime`, `pathlib`, `typing`, `yaml`, and
  `agent.models`.
- Five rules are `enabled: true` in the current `rules.yaml`: `KILL_SWITCH` (order
  1), `HOLDOUT_GUARD` (order 2, unconditional — no `enabled` gate at all in the
  code, it always runs if `case.cohort is Cohort.HOLDOUT`), `TERMINAL_CLASS` (order
  3, `verified: true`), `ATTEMPT_CAP` (order 4, **`verified: false`**), `DOWNTIME_DEFER`
  (order 5, `verified: true`). Six more rules exist with `enabled: false` and fixed
  `order` values 6–11.
- `ATTEMPT_CAP` reads a per-method cap from `rules.yaml`: emandate=3, upi=3, card=4,
  netbanking=4, default=3. These numbers are **not independently verified against
  any primary NPCI source** — `EVIDENCE.md` E12 labels this a secondhand claim.
- `DOWNTIME_DEFER` only actually appends itself to `fired_rules` and overrides
  `execute_at` when the computed candidate time exceeds the already-planned
  execute time (`if candidate > execute_at:`). Being "active and instrument-matched"
  alone is not sufficient to mark the rule as fired — this was corrected during
  this session's review; verify against `agent/policy/engine.py` lines 146–165
  directly if this document and the code ever diverge.

### Execution

- `ExecutorPort` (`agent/executors/port.py`) has one method, `execute(verdict:
  Verdict) -> ActionResult`. The only implementation in the codebase is
  `SimulatedExecutor` (`agent/executors/simulated.py`).
- `SimulatedExecutor.execute()` raises `ValueError` if given a non-executable
  verdict (`decision` not in `{ALLOW, DEFER}`, or `action == STOP`) — this is
  enforced at the executor boundary, not just trusted from the caller.
- Idempotency key = `sha256(case_id:action:attempt_no)`, where `attempt_no` is read
  fresh from `cases.attempts + 1` at call time, not from any value stored on the
  verdict. A duplicate key with a non-null `executed_at` short-circuits to a replay
  result without consulting `outcome_fn` or the RNG — confirmed by
  `tests/test_idempotency.py`.
- `outcome_fn` is injected as `(Verdict) -> float`; the executor has no knowledge
  of what determines that probability. This is the enforced boundary that keeps
  `agent/` from importing `datagen/` — the hidden response model is a closure
  built in `evalharness/run.py`, not a value the executor ever loads itself.

### State

- `agent/state.py:VALID_TRANSITIONS` is the sole source of truth for legal state
  changes; `transition()` raises `IllegalTransition` on any other request, and uses
  an optimistic-concurrency `version` column (`UPDATE ... WHERE case_id = ? AND
  version = ?`) that raises `IllegalTransition` on a zero-row update.
- `DETECTED` can only reach `DIAGNOSED`, `ABANDONED`, or `QUARANTINED` — not
  `HOLDOUT_CLOSED` directly. Holdout cases pass through `DIAGNOSED` first, because
  `process_case()` always runs triage and diagnosis before evaluating policy,
  regardless of cohort.

### Audit

- `agent/audit.py:EVENTS` is a closed set of 8 strings; `append()` raises
  `ValueError` on any other `event_type`.
- The database schema (`agent/db.py`) defines two triggers: `cohort_is_immutable`
  (blocks `UPDATE ... SET cohort` when the new value differs from the old) and
  `audit_no_update`/`audit_no_delete` (block any `UPDATE`/`DELETE` on
  `audit_events` unconditionally). Both raise `sqlite3.IntegrityError` via
  `RAISE(ABORT, ...)`, confirmed by test.
- `verify_chain()` recomputes every hash from `GENESIS` forward and returns `False`
  on the first mismatch — it does not report *which* row was altered, only whether
  the whole chain is intact.

### Data generation

- `datagen/generate.py:generate()` is a pure function of its keyword arguments —
  no file I/O, no DB access. It returns records, downtime windows, and a manifest.
- The hidden `GroundTruth.p_organic`, `p_retry_now`, `p_retry_after_downtime` are
  computed per-record by `_hidden_probs()`, which branches on the *true* class
  (never the triaged/diagnosed class) and, for `TRANSIENT_INFRA` only, on whether
  downtime was active at record-creation time. The other three classes' hidden
  probabilities do not depend on downtime at all — this is a modeling choice, not
  a limitation of the schema.
- `write_operational_db()` routes every generated record through
  `agent.pipeline.ingest()` — the generator does not construct `cases` rows
  directly, so every generated case has a real `SIGNAL_RECEIVED` /
  `COHORT_ASSIGNED` audit trail from the moment it exists.

## Non-functional requirements enforced by code

| Requirement | Enforcement mechanism | Where |
|---|---|---|
| Reproducibility | Cohort assignment is `sha256(seed:case_id)`-derived, not RNG-stream-order-derived; organic-recovery draws use the same pattern | `agent/ledger.py`, `evalharness/metrics.py:_organic_recovered` |
| No free text to the LLM | `_build_prompt()` selects fields explicitly, never passes `error.description` or any customer-supplied string | `agent/diagnosis/claude.py` |
| No PII in the model | `customer_id` is generator-assigned (`cust_00042` pattern), never a hash of anything real | `datagen/generate.py` |
| `agent/` ↛ `datagen/` | Asserted by AST walk over every `.py` file under `agent/` | `tests/test_isolation.py` |
| Append-only audit | DB triggers, not application discipline | `agent/db.py` |
| Bounded spend under an adversarial model | Explicit test with a model that always proposes `RETRY, confidence=1.0` | `tests/test_adversarial.py` |

## Requirements that are documented elsewhere but UNENFORCED in code

- "Checked twice independently" kill switch (`rules.yaml` comment) — only one check
  exists.
- Policy veto rate in [5%, 40%] (`eval/PREREGISTRATION.md`) — now *computed and
  reported* (`evalharness/metrics.py:policy_veto_rate`), but nothing in the code
  enforces the band; it is surfaced as an adverse finding when violated, not blocked.
- Quiet hours, execution windows, contact caps, EV floor, confidence floor — rule
  entries exist in `rules.yaml` with `enabled: false`; zero logic for any of them
  exists in `agent/policy/engine.py` beyond the disabled flag itself (i.e., turning
  `enabled: true` on `CONTACT_CAP` today would do nothing, because `evaluate()` has
  no branch that reads that rule id at all — the reservation is name-and-order
  only, not a stubbed implementation).
