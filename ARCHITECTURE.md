<!-- last_verified: 2026-08-25 -->

# Architecture

Implements [PRODUCT_THESIS.md](PRODUCT_THESIS.md). Ten sections, matching the design
review this system was built from. Phase 1 status is called out per component —
see `STATE.md` for what's currently on disk versus deferred to Phase 2/3.

## 1. System Architecture

Two execution modes over **one code path** — the load-bearing decision. If live and
replay ran different code, the eval numbers wouldn't describe the shipped system.

```
                    +-----------------------------------------------+
  Razorpay          |                 CORE PIPELINE                 |
  test-mode --+     |                                               |
  webhooks    +-->  |  Ingest -> Triage -> [Diagnose] -> Policy -> Exec |--> Executor
              |     |            (rules)   (LLM,        (pure     |      Port
  Seeded  ----+     |                     ambiguous      code,    |        +-- Live (Phase 2)
  batch replay      |                      tail only)    veto)    |        +-- Simulated (Phase 1)
                    |                                               |
                    +----------------------+------------------------+
                                           |
                    +----------------------v------------------------+
                    |  Append-only hash-chained AUDIT LOG            |
                    |  State store . Ledger (cohorts)                |
                    +-------------------------------------------------+
                                           |
                                Eval harness --> report.md
```

Injected `Clock` (`agent/clock.py`: `RealClock` / `VirtualClock`) and injected
`ExecutorPort` (`agent/executors/port.py`) are the only differences between modes.
`agent/pipeline.py` never branches on which mode it's in.

**Stack:** Python 3.11+ · stdlib `sqlite3` (no ORM — raw SQL keeps the immutability
triggers visible) · Pydantic v2 for every boundary schema · Anthropic SDK · pytest +
hypothesis. No Redis, Celery, vector DB, or agent framework — none serves a stated
requirement (see `DECISIONS.md` ADR-003).

## 2. Components

| # | Component | File | Owns | Does NOT own | Phase |
|---|---|---|---|---|---|
| C1 | Ingest/Normalizer | `agent/pipeline.py:ingest` | Unify webhooks + batch into one event | Judgement | 1 |
| C2 | Downtime Store | `agent/downtime.py` | "Was (method, instrument) degraded at T?" | What to do about it | 1 |
| C3 | Triage | `agent/triage.py` | Deterministic majority classification | Ambiguous/unseen combos | 1 |
| C4 | Diagnosis Agent (AI-1) | `agent/diagnosis/` | Propose class + action + rationale, ambiguous tail only | Authorization, timing, execution | 1 (stub used for eval numbers; `ClaudeDiagnosis`'s fallback ladder unit-tested with a mocked client, `tests/test_claude_diagnosis.py`), 2 (called live against the real API) |
| C5 | Policy Engine | `agent/policy/engine.py` | Veto over every action | Reasoning, I/O, clock | 1 (5 of 11 rules) |
| C6 | Scheduler | — | Durable `retry@T` | Choosing T | **2** (Phase 1 executes synchronously; `execute_at` is computed and audited but not literally waited on) |
| C7 | Executor Port | `agent/executors/` | Perform the bounded action | Choosing it | 1 (Simulated), 2 (Live) |
| C8 | State Store | `agent/state.py` | Case state machine, counters, idempotency | History (audit log's job) | 1 |
| C9 | Audit Log | `agent/audit.py` | Append-only, hash-chained, replayable | Mutation | 1 |
| C10 | Ledger | `agent/ledger.py` | Seeded cohort assignment | ₹ attribution (currently in `evalharness/metrics.py`) | 1 |
| C11 | Eval Harness | `evalharness/` | Scoring, bootstrap CI, adverse findings | Running in production | 1 (core), 3 (ablations, sweep) |
| C12 | Read-only UI | — | At-risk queue, decision trace | Any write path | **Deferred — Phase 2** |

## 3. Data Flow

```
1  payment.failed (or replayed record)   -> C1 emits PaymentFailure
2  C10 assigns cohort ONCE, at case creation -> TREATED | HOLDOUT (immutable, DB-enforced)
3  C2  attaches DowntimeContext{active, severity, scheduled, instrument_match, expected_end}
4  C3  taxonomy lookup -> CLEAN class | AMBIGUOUS | unseen
5  AMBIGUOUS only -> C4 LLM -> DiagnosisProposal
6  C5  policy.evaluate(proposal, case, rules, now, downtime) -> Verdict
7  Verdict ALLOW/DEFER -> C7 executes; DENY -> case transitions to ABANDONED/HOLDOUT_CLOSED
8  C7 executes with idempotency_key -> ActionResult
9  C8 transitions state; evalharness attributes rupees to the arm
10 Every step 1-9 appends to C9 with case_id as correlation id
```

Holdout cases traverse steps 1–6 and are denied at policy rule 2 (`HOLDOUT_GUARD`).
They ARE diagnosed but never acted on — diagnosis quality is measurable on both arms
while the counterfactual stays clean. Verified live: `tests/test_adversarial.py`
asserts zero holdout contamination even under an adversarial model.

## 4. Agent / Tool Boundaries

**The LLM has zero tools.** `agent/diagnosis/port.py`'s `DiagnosisPort` Protocol has
no method for calling a tool, reading a database, or touching the network — nothing
implementing it can either.

| Boundary | Enforcement |
|---|---|
| No tool access | SDK call made without a `tools` parameter (`agent/diagnosis/claude.py`) |
| No untrusted text in prompts | Only enum/numeric fields reach C4 (`DiagnosisInput`) — never customer or merchant free text. The injection surface is designed out, not filtered |
| No PII | `customer_id` is opaque-random, never a hash of real data (a salted hash over a small ID space is brute-forceable and isn't anonymization) |
| Output cannot reach an executor | `ExecutorPort.execute()` accepts a `Verdict` only, never a `DiagnosisProposal` — enforced by type signature (`agent/executors/port.py`) |
| No self-authorization | C4 emits `proposed_action`; C5 independently derives the allowed set. Disagreement is a recorded `POLICY_VERDICT` with `fired_rules` |

## 5. Deterministic Policy Layer

Pure function, `agent/policy/engine.py:evaluate()`. No I/O, no ambient clock, no
model. Thresholds live in `agent/policy/rules.yaml` — the single source of truth
(CLAUDE.md invariant 10). First DENY wins; order is fixed by the yaml, not by code.

**Phase 1 ships 5 of 11 rules** — the ones the thesis rests on:

| Order | Rule | Verified? |
|---|---|---|
| 1 | `KILL_SWITCH` | yes |
| 2 | `HOLDOUT_GUARD` — unconditional, cannot be overridden by any later rule | yes |
| 3 | `TERMINAL_CLASS` | yes |
| 4 | `ATTEMPT_CAP` | **no — E12, secondhand** |
| 5 | `DOWNTIME_DEFER` | yes |

Reserved, disabled, ids fixed so enabling them later never renumbers the rules
above: `CONTACT_CAP`, `EXECUTION_WINDOW` (E13, unverified), `QUIET_HOURS` (E15,
unverified), `COOLDOWN`, `EV_FLOOR`, `CONFIDENCE_FLOOR` (needs a fitted calibrator —
Phase 3).

`tests/test_policy.py` is hypothesis-based property testing and **passes with the
Anthropic SDK uninstalled** — confirmed this session. That is the standing proof the
gate is real rather than decorative.

## 6. State Management

```
DETECTED -> DIAGNOSED -+-> SCHEDULED -> EXECUTING -+-> RECOVERED         (terminal)
                        |                            +-> FAILED_ATTEMPT -+ (loops back to DIAGNOSED)
                        +-> ABANDONED(reason)                            (terminal)
                        +-> HOLDOUT_CLOSED                               (terminal)
                        +-> QUARANTINED                                  (terminal, unused in Phase 1)
```

`agent/state.py:VALID_TRANSITIONS` enforces this explicitly — diagnosis runs even on
holdout cases (they're denied at the policy step, not before), so `HOLDOUT_CLOSED` is
reached from `DIAGNOSED`, not directly from `DETECTED`. This was caught and fixed
during Phase 1 implementation (see `DECISIONS.md` ADR-006).

Idempotency: `key = sha256(case_id, action, attempt_no)`, unique index on `actions`.
`cohort` is immutable via a DB trigger (`agent/db.py:cohort_is_immutable`), not
application-level discipline.

## 7. Audit Trail

`agent/audit.py`. Single append-only table, hash-chained:
`hash = sha256(prev_hash || canonical_json(payload))`. Enforced two ways, tested
both: a DB trigger blocks any `UPDATE`/`DELETE` outright
(`tests/test_audit.py::test_append_only_trigger_blocks_*`), and even if that trigger
were bypassed, `verify_chain()` independently detects a single altered byte
(`test_chain_detects_single_byte_tamper_even_if_trigger_bypassed`) — defense in depth,
verified rather than assumed.

`replay(case_id)` rebuilds state from the event stream alone;
`agent/state.py:verify_counters()` asserts it matches the state store. Both wired
into `evalharness/run.py` and printed in every report.

## 8. Observability

Not yet instrumented as metrics (`/metrics` endpoint is Phase 2). Phase 1's
observability is the audit log itself plus the eval report's safety-invariant
section, which surfaces exactly the numbers a metrics endpoint would: holdout
contamination, cap breaches, chain integrity, counter agreement.

## 9. Failure Handling

| Failure | Containment | Status |
|---|---|---|
| LLM timeout / malformed / refusal | 3-tier fallback ladder (`agent/diagnosis/claude.py`): repair retry -> taxonomy prior -> UNKNOWN/STOP | Built, not yet live-tested (needs Day 2 API key) |
| LLM confidently wrong | Policy caps bind regardless of confidence | **Proven** — `tests/test_adversarial.py` |
| Duplicate scheduler delivery | Idempotency key, unique index | Built |
| Kill switch | Checked in policy rule 1 | Built (pre-dispatch executor-side check is Phase 2) |
| Shadow mode | — | **Deferred — Phase 2.** An earlier `NullExecutor` was built ahead of schedule and removed on review (DECISIONS.md ADR-008) — it was unwired and untested scope creep against the approved Phase 1 plan |
| Razorpay outage / circuit breaker | — | **Deferred — Phase 2** |
| Simulator flatters results | Sensitivity sweep | **Deferred — Phase 3** |

## 10. Evaluation Harness

`evalharness/` + `scripts/gen.py`. `make gen && make eval` regenerates the seeded
dev corpus and scores it — confirmed byte-for-byte reproducible across two full runs
this session.

- **Primary KPI:** incremental ₹/1,000 vs. holdout, bootstrap CI (2,000 resamples on
  the Phase 1 dev corpus; the plan commits to 10,000 on the sealed n=1,000 test
  corpus in Phase 3 — stated so the two are never conflated).
- **AI quality:** macro-F1 on the AMBIGUOUS subset only (overall accuracy is
  deliberately not reported — inflated by the CLEAN majority).
- **Safety invariants:** holdout contamination, cap breaches, chain verification,
  counter agreement, **policy veto rate** (target band [5%, 40%], flagged as an
  adverse finding when out of band) — all printed as build-relevant numbers, not
  descriptive color.
- **Adverse findings:** mandatory, non-empty section. The first real run surfaced
  two genuine findings (macro-F1 below random-guess baseline because `StubDiagnosis`
  always guesses `TRANSIENT_INFRA`; zero downtime deferrals on this corpus's low
  overlap rate) — both are printed rather than hidden.
- **Not yet built:** ablation arms (A0–A3), negative control (S3), sensitivity
  sweep, calibration (ECE/Brier). Deferred to Phase 3 per the plan.

`datagen/` and `agent/` are import-isolated in both directions that matter:
`tests/test_isolation.py` statically asserts nothing under `agent/` imports
`datagen/`, so the hidden response model (`p_organic`, `p_retry_now`, ...) has no
code path into the live decision.
