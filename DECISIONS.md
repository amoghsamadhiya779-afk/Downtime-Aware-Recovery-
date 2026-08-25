<!-- last_verified: 2026-08-25 -->

# Decisions

Append-only. One entry per decision that could plausibly be re-proposed after
compaction. Each names what was rejected and why — the goal is to stop killed ideas
from returning, not just to record what shipped.

## ADR-001 — Track selection: 03 (AI Revenue Recovery)

**Chosen:** downtime-aware recovery agent, measured against a randomized holdout.

**Rejected:**
- *Prompt-injection firewall (Track 02).* Higher raw panel score (68) but carries a
  disqualification tail — Track 02 explicitly bars "anything offense-capable," and
  an attack corpus is readable as such. Not worth the variance when a same-ratio
  alternative has none.
- *Promise-to-pay tracker (Track 03).* Its entire advantage was irreducible AI
  (extracting conditional promises from Hinglish B2B threads), but no public corpus
  of such threads exists — it would have to be self-authored with an LLM, which
  reintroduces exactly the self-graded-simulator flaw this project exists to avoid.
- *Delegated Pay Mandate (Track 01).* Razorpay already ships Agentic Payments, an
  Agentic Platform, and Agent Studio — this would demo token-scoping design to the
  team that ships token scoping. The crypto/policy core also has no AI in it.
- *Compliance-as-Code Gates (Open).* Proudly contains no model; wrong competition
  for an AI buildathon. Absorbed as a component (rules.yaml) instead of standing alone.
- *Card-testing fraud detector (Track 02).* A public competitor
  (`Aahan0605/Razorpay_ps`) already built a better-instrumented version — being the
  second-best public clone of a solved thing is worse than building something else.
- *Payment router / smart routing.* Razorpay Optimizer already does this at a scale
  no student build can match (~150 params, ~600M data points). See `EVIDENCE.md` E4.
- *Generic subscription dunning bot.* Duplicates a shipped feature (E5).

## ADR-002 — Measurement: incremental ₹ vs. holdout, not gross

**Chosen:** primary KPI is `(Σ₹ᵗ/nᵗ − Σ₹ʰ/nʰ) × 1000`, gross always printed beside it.

**Rejected:** reporting gross recovered ₹ alone, as every sampled competitor does
(`research/COMPETITORS.md`). Gross cannot distinguish the agent's effect from organic
recovery that would have happened anyway — it is the field's central, shared flaw.

## ADR-003 — No Redis, Celery, vector DB, or agent framework

**Chosen:** stdlib `sqlite3` + a synchronous pipeline function.

**Rejected:** a message broker for the scheduler (C6) — Phase 1 needs a table and a
polling loop, not a broker; adding one would add operational surface with no
requirement behind it. Same reasoning excluded LangGraph/CrewAI-style orchestration:
one deterministic router function is strictly simpler and equally correct for three
possible actions.

## ADR-004 — The LLM holds zero tools

**Chosen:** `DiagnosisPort` is a pure function; structured input, structured output.

**Rejected:** giving AI-1 function-calling access to the database or executor.
Gating N tool calls is strictly worse than gating one proposal once, downstream, in
a pure policy function that's independently unit-testable with the model entirely
absent.

## ADR-005 — Organic-recovery counterfactual computed at eval time, not execution time

**Chosen:** `evalharness/metrics.py:_organic_recovered()` draws a deterministic
outcome from hidden `p_organic` for any case where no action was taken (ABANDONED,
HOLDOUT_CLOSED), so both arms have a real counterfactual instead of holdout cases
defaulting to "never recovered."

**Rejected:** having the agent or executor decide organic recovery. That would put a
measurement-only concept into the live path, violating the Measurement layer's
"does not own anything in the live path" boundary (`ARCHITECTURE.md` §2).

## ADR-006 — `HOLDOUT_CLOSED` is reached from `DIAGNOSED`, not `DETECTED`

**Found during implementation, not design.** The original state machine draft listed
holdout closure as a transition directly from `DETECTED`. But the architecture
requires holdout cases to be diagnosed (so diagnosis quality is measurable on both
arms) before being denied at the policy step — meaning every case, holdout included,
passes through `DIAGNOSED` first. `agent/state.py:VALID_TRANSITIONS` was corrected
before any test ran against it. Left here because it's exactly the kind of drift
this file exists to catch before it recurs.

## ADR-007 — Bootstrap resamples: 2,000 for Phase 1, 10,000 committed for Phase 3

**Chosen:** `evalharness/metrics.py:bootstrap_incremental` defaults to `n_boot=2000`
on the n=300 dev corpus (speed; the CI width is dominated by `n`, not resample count
at this scale).

**Not a walk-back:** the plan's eval framework commits to 10,000 resamples on the
sealed n=1,000 test corpus. Stated explicitly in both the function docstring and
`ARCHITECTURE.md` §10 so the two numbers are never quietly conflated in the README.

## ADR-008 — `NullExecutor` (shadow mode) removed after review

**Found on self-review, not during design.** The approved Phase 1 plan explicitly
listed "null executor / shadow mode" under *deferred out of Phase 1*. It got built
into `agent/executors/simulated.py` anyway during implementation — small, harmless
on its own, but unwired (nothing constructed it), untested, and a direct violation
of both the approved plan and `CLAUDE.md`'s "don't add features beyond what the task
requires" rule.

**Rejected:** keeping it "since it's already written and doesn't hurt anything."
Dead code that contradicts an explicit scope decision is exactly the kind of drift
this file and `STATE.md` exist to catch — keeping it because it's cheap to keep is
how scope creep compounds. Removed; shadow mode returns when Phase 2 actually
schedules it, alongside the pre-dispatch kill-switch check it's meant to pair with.

## ADR-009 — `DOWNTIME_DEFER` only "fires" when it changes the schedule

**Found on self-review.** The original implementation appended `DOWNTIME_DEFER` to
`fired_rules` (and overwrote `reason`) whenever downtime was merely active and
instrument-matched — even on the branch where the computed candidate time didn't
exceed the already-planned `execute_at`, meaning the decision stayed `ALLOW` while
the audit trail claimed a defer happened. This also fed `evalharness/run.py`'s
`outcome_fn`, which keys off `fired_rules` to choose between `p_retry_now` and
`p_retry_after_downtime`.

**Chosen:** move both the `fired_rules` append and the `reason` assignment inside
the `if candidate > execute_at:` branch, so "fired" means "changed the outcome," not
"was consulted." An audit trail that records a rule firing when it had no effect is
a correctness bug in exactly the component (`agent/audit.py`) this project's whole
thesis depends on being trustworthy.

## ADR-010 — `policy_veto_rate` computed and reported

**Found on self-review.** `eval/PREREGISTRATION.md` locked a [5%, 40%] target band
for policy veto rate as a safety invariant before Phase 1 code existed. The metric
was never actually implemented in `evalharness/metrics.py` — a real gap between what
the pre-registration document claimed was measured and what the code measured.
`docs_check.py` didn't catch it because it only checks rule-id citations, not metric
presence, which is a real (accepted) limitation of that script, not something fixed
here.

**Chosen:** `policy_veto_rate()` counts DENY verdicts against RETRY proposals only —
a proposed STOP that gets denied was never going to spend, so it isn't the gate
overriding the model. Wired into `build_report()` and into the adverse-findings
section when the run has ≥10 RETRY proposals and falls outside the band.

## ADR-011 — Groq added as a second, interchangeable AI-1 backend

**Chosen:** `agent/diagnosis/groq_diagnosis.py` (`GroqDiagnosis`), free-tier, no
credit card, rate-limited only. Prompt construction, evidence-groundedness
validation, and the fallback ladder were extracted out of `claude.py` into
`agent/diagnosis/prompting.py` so both providers share exactly one copy of that
logic — the part that actually matters for safety — rather than risking two
implementations silently drifting apart. `ClaudeDiagnosis` was kept, not replaced;
`DiagnosisPort` exists precisely so either can be swapped in with zero change to
`agent/pipeline.py`. Selectable via `evalharness/run.py --provider {stub,claude,groq}`.

**Rejected:** Gemini — also free, but its free-tier terms state prompts/responses
"may be used to improve Google's products," a worse fit for a payments-adjacent
pitch even with synthetic data. Confirmed via web search this session (not from
memory), alongside Groq's terms: 30 req/min, up to ~14,400 req/day org-wide
(model-dependent), no data-sharing clause found in Groq's free-tier terms.

**Two real bugs found getting this working, not just claimed clean:**

1. Default model `llama-3.3-70b-versatile` returned `404 model_not_found` on the
   real API — Groq had deprecated their Llama chat models in favor of the
   `gpt-oss` line. Found by bypassing the fallback ladder's silent
   `except Exception: continue` to surface the real error, then confirmed the
   current model list live via `GET /openai/v1/models` with the actual key rather
   than trusting a search result. Fixed: `MODEL = "openai/gpt-oss-120b"`.
2. Both `tests/test_claude_diagnosis.py` and the new `tests/test_groq_diagnosis.py`
   had a latent mock bug: the fake client's response list was copied
   (`list(responses)`) on every construction, but a fresh SDK client — and
   therefore a fresh fake client — is legitimately constructed on every `_call()`.
   Every repair attempt was silently re-consuming the *first* canned response
   instead of continuing to drain toward the second, so both "repair succeeds"
   tests were actually exercising the tier-3 fail-closed path and asserting the
   wrong thing without noticing, because they'd never been executed since being
   written under a "do not test" instruction. Caught the moment they were finally
   run. Fixed by sharing the list by reference instead of copying it.

**End-to-end verification:** a live call against `openai/gpt-oss-120b` (ambiguous
UPI failure, active high-severity downtime) returned `TRANSIENT_INFRA`,
confidence 0.92, `RETRY` at 5 minutes, with evidence citing only real input fields
— `fallback_tier=0`, no fallback needed. First time any real model has been
exercised this session; every number before this was `StubDiagnosis`.

## ADR-012 — `datagen/generate.py`: `is_recurring` and `mandate_id` were two independent coin flips

**Found by auditing existing data, not by reading the code first.** Asked to find
bugs in data already on disk, so `data/dev.db` was queried directly rather than
starting from a code review — the query surfaced 130/300 cases (43.3%) where
`is_recurring` and `mandate_id` disagreed, before any line of the generator had
been re-read.

**Root cause:** `datagen/generate.py` (the *other* corpus generator, distinct from
`scripts/generate_data.py`) had:
```python
is_recurring=rng.random() < 0.3,
mandate_id=f"mandate_{i:05d}" if rng.random() < 0.3 else None,
```
Two separate `rng.random()` calls, each independently true ~30% of the time — not
the same condition read twice. A mandate implies recurring and vice versa; there
is no other valid combination (the same invariant `scripts/validate_data.py`
checks for the other generator's output).

**Not the same bug as ADR-011's mandate/customer binding issue** in
`scripts/generate_data.py`, despite the surface similarity — this generator gives
every mandate_id a unique per-record suffix (`mandate_{i:05d}`) and never reuses
one across records at all, so no cross-customer collision is possible here. The
bug here is purely the two-independent-flips inconsistency.

**Chosen:** draw `is_recurring` once, derive `mandate_id` from it.

**Data fixed, not just code:** `data/dev.db` and `data/dev_ground_truth.jsonl`
regenerated from the corrected generator (same seed=42) and re-verified: 0
mismatches, 0 orphans between cases and ground truth, 0 TERMINAL records with
nonzero recovery probability, 0 CLEAN-reason/true_class disagreements, 0
instrument/method shape mismatches, full 34/34 test suite still passes. The stale
`eval/report.md` from before this fix (and before the generator existed in its
current form) was deleted rather than regenerated — regenerating it means running
real evaluation work, which is explicitly deferred to when the user resumes.

**Also cleaned up as stale/redundant, not bugs but clutter:** `data/synthetic/`
(an early smoke-test output directory, identical seed to and superseded by
`data/dataset/dev/` — see docs/06_evaluation.md).

## ADR-013 — `DiagnosisProposal` extended: expected_outcome, risks, missing_information

**Chosen:** three new fields on AI-1's output, all required (no default — the model
must state them on every call, even as an empty list, rather than silently omit
them):

- `expected_outcome: ExpectedOutcome` — `{probability_of_success, horizon_minutes}`.
  Deliberately a different axis from `confidence`: confidence is how sure the model
  is about the *diagnosis*; `probability_of_success` is how likely it thinks the
  *proposed action* is to work. A live Groq response this session demonstrated
  exactly why the distinction is real, not academic: `CUSTOMER_FIXABLE` at
  confidence 0.78, but `probability_of_success` only 0.3, because being sure of the
  diagnosis doesn't mean the action will succeed on this attempt.
- `risks: list[RiskFlag]` — closed `RiskCategory` enum + a 140-char note, not free text.
- `missing_information: list[MissingInfoCategory]` — closed enum, what the model
  would have wanted but the input didn't carry.

**Rejected:** free-text risk/missing-information strings. The instruction driving
this change was explicit — "no free-form execution commands" — and a field a model
can fill with arbitrary text is exactly the kind of field that could carry an
instruction through the audit trail undetected. Every new field is either a closed
enum, a bounded numeric, or a short bounded string paired with a closed enum.
`proposed_action` was already a closed enum (RETRY/STOP) and stays that way — this
ADR doesn't touch it, just confirms it satisfies the same constraint the new fields
were held to.

**Field renamed vs. kept:** the requirement listed "diagnosis" as a required field
name. Kept the existing `recoverability` name rather than renaming — a rename would
have touched the enum's own name, `agent/triage.py`, `agent/policy/engine.py`,
`evalharness/metrics.py`, `datagen/schema.py`'s `GroundTruth.true_class`, and every
test, for a purely cosmetic difference with no functional benefit. `recoverability`
*is* the diagnosis; documented as such rather than churned.

**Every construction site updated** (Pydantic required fields with no default
means every one had to be touched, not just the new-code paths):
`agent/diagnosis/stub.py` (all three fixtures), `agent/diagnosis/prompting.py`
(`tier2_fallback`), `agent/pipeline.py` (both triage-resolved construction sites),
`tests/test_policy.py`, and the `_valid_json()` fixtures in both provider test
files. Full suite re-run clean after each site: 34/34.

**Real bug found verifying this against the live API, not just the mocks:**
`openai/gpt-oss-120b` is a reasoning model — hidden reasoning tokens count against
`max_tokens`. At the old `max_tokens=400` with no `reasoning_effort` set, live
calls confirmed `finish_reason: "length"` with 350–398 of the 400 tokens consumed
by `reasoning_tokens` alone, leaving truncated or empty JSON on **every single
real call** — silently falling through to the tier-3 fail-closed path every time,
which the mocked tests could never have caught since they don't exercise real
token accounting at all. Fixed with `reasoning_effort="low"` and `max_tokens=600`;
reasoning-token consumption dropped to ~100 tokens and both live test cases
produced genuinely good, schema-compliant, `fallback_tier=0` output. Claude's
`max_tokens` bumped to 600 too, defensively — no reasoning-token issue there, but
the schema is genuinely bigger now regardless of provider.

## ADR-014 — AI-1: two real "use available context" gaps closed, three "avoid unsupported conclusions" gates added

**Scope discipline:** every change in this ADR lives in `agent/diagnosis/` plus
one line in `agent/pipeline.py` that only threads an existing field
(`pf.is_recurring`) into `DiagnosisInput` construction. Nothing in
`agent/policy/` or `agent/executors/` was touched, per the instruction driving
this change.

**Context gaps found by reading the code, not assumed:**

- `is_recurring` was available on `PaymentFailure` and used throughout the
  pipeline, but never made it into `DiagnosisInput` at all — the diagnosis layer
  had no way to know whether a failure was on a recurring mandate (different
  NPCI/billing-cycle failure profile) versus a one-off checkout. Added to
  `DiagnosisInput`, `build_prompt()`, and `evidence_fields()`.
- `DowntimeContext.instrument_match` was computed by `DowntimeStore.context_at()`
  but never sent to the model — the prompt said "downtime is active" without ever
  saying whether it actually covers this payment's instrument. **Caught on
  verification, not assumed fixed:** re-reading `agent/downtime.py` after making
  this change showed `active_at()` already filters to matching instruments before
  returning a window at all, so `instrument_match` is currently *always* equal to
  `active` in the live system — this fix adds zero new information today. Kept it
  anyway for two honest reasons, not to inflate the fix's value: it's
  forward-compatible if `active_at()` ever starts surfacing same-method,
  different-instrument windows as advisory context, and omitting a field that
  exists on `DowntimeContext` would leave the prompt's downtime block silently
  incomplete relative to the schema. Confirmed live afterward that the model does
  cite it as evidence when reasoning about downtime, even though it's currently
  redundant with `active`.

**Three new validation gates in `prompting.validate()`, all following the
existing pattern** (raise `ValueError` -> caught by the existing repair-retry
loop -> falls through to tier-2/tier-3 on exhaustion — no new code path added to
either provider):

1. `confidence >= 0.7` requires at least one `evidence[]` entry. A confidence
   score with nothing behind it is an assertion, not a diagnosis.
2. `confidence >= 0.85` requires empty `missing_information[]`. Claiming
   near-certainty while admitting a relevant gap is the model's own contradiction,
   not a defensible nuanced position.
3. `recoverability=TERMINAL` requires `proposed_action=STOP`. `agent/policy/`
   already independently denies a TERMINAL retry via `TERMINAL_CLASS` regardless
   of what the model proposes — that enforcement is untouched — but a model whose
   own proposal contradicts its own diagnosis is producing an unsupported
   conclusion at the diagnosis layer itself, worth catching before it ever
   reaches policy, not just after.

The system prompt was updated to state these three rules explicitly (told, not
just silently enforced after the fact) — the model should be steered away from
these responses, not merely punished for them.

**Verified live, not just unit-tested:** three real cases against
`openai/gpt-oss-120b` (recurring mandate + active downtime, one-off checkout with
thin signal, repeat customer with high contact count) — 3/3 answered directly
(`fallback_tier=0`), zero validation-rule violations, and every case showed
`confidence` and `expected_outcome.probability_of_success` diverging sensibly
(e.g. confidence 0.9 in a CUSTOMER_FIXABLE diagnosis paired with only 0.1
probability the proposed STOP-then-wait path succeeds soon) rather than
collapsing to one number. Full suite still 34/34 after every change.

## ADR-015 — AI output validation: unsupported-action gap closed, malformed-input robustness added, failure reasons made auditable

**Real bug found by reading `agent/policy/engine.py::evaluate()` closely, not
assumed fine because the types looked right:** its final line was
`return verdict(decision, Action.RETRY, reason, execute_at)` — a bare fallthrough
for "anything that reached this point," not an explicit check that the proposal
actually said RETRY. `Action.RECOVERY_LINK` is a real, schema-valid enum member
(reserved for a future phase, zero implementation anywhere) — a model proposing
it would pass Pydantic validation and then be **silently reinterpreted as RETRY**
by this fallthrough. That is not failing safely; it is failing silently wrong,
which is a materially worse failure mode than a crash, since nothing would ever
signal that it happened.

**Chosen — two independent lines of defense, not one:**

1. `agent/diagnosis/prompting.py::validate()` now rejects any `proposed_action`
   outside `SUPPORTED_ACTIONS = {RETRY, STOP}`, raising the same way every other
   validation failure does — caught by the existing repair-retry loop, falling
   through to tier-2/tier-3 fallback on exhaustion. First line of defense: reject
   at the source, before the proposal exists as anything but raw model output.
2. `agent/policy/engine.py::evaluate()` gained a new structural guard — rule 0,
   checked even before the kill switch, deliberately **not** a `rules.yaml` entry
   since it's a precondition on the function's input, not a tunable business
   threshold. Any `proposed_action` outside `{RETRY, STOP}` is denied with
   `Action.STOP` and `"UNSUPPORTED_ACTION"` recorded in `fired_rules`. Second,
   independent line of defense for any `DiagnosisProposal` that reaches `evaluate()`
   by a path that skips (1) — a hand-constructed proposal, a future third
   provider, a bug in (1) itself.

**Also added, scoped to the diagnosis layer:**

- `_strip_code_fence()` in `prompting.py` — models frequently wrap JSON in
  ` ```json ... ``` ` despite explicit instructions not to; that's a formatting
  habit, not a content problem, and treating it as malformed was rejecting
  otherwise-valid responses for a reason worth engineering around rather than
  just retrying and hoping. Parsing is more tolerant; validation is not — every
  field is still fully checked after stripping.
- `tier2_fallback()` / `tier3_fallback()` now accept `last_error: str | None` and
  fold it into the fallback's `rationale`. Both provider `diagnose()` loops now
  capture `f"{type(e).__name__}: {e}"` from the final failed attempt and pass it
  through. Previously the exception was silently swallowed by
  `except Exception: continue` — a human reading the audit trail could see *that*
  a fallback fired but never *why*. Now they can.

**New test file, `tests/test_ai_output_validation.py` (28 tests)** — maps 1:1 to
the five required categories (malformed output, missing fields, invalid enum
values including nested ones, impossible confidence including
`expected_outcome.probability_of_success`, unsupported actions) plus the actual
"fails safely" property checked at both layers: `test_recovery_link_rejected_at_diagnosis_layer`
and `test_policy_fails_safely_on_unsupported_action_defense_in_depth` (the latter
constructs a `DiagnosisProposal` directly, bypassing `validate()` entirely, to
prove the policy-layer guard holds independently) plus
`test_fails_safely_on_total_exhaustion_no_clean_prior` (confirms total exhaustion
lands on `UNKNOWN`/`STOP`/tier 3, never a crash, never a guessed RETRY).

**Verified live after implementing:** a real call against `openai/gpt-oss-120b`
with all new validation layered on still returned a direct, correct answer
(`fallback_tier=0`) — the added strictness doesn't cause spurious rejection of
genuinely good output. Full suite: 62/62 (34 prior + 28 new).

## ADR-016 — Non-AI baseline arm added; first real A1-vs-A3 comparison run; the comparison is currently unanswerable and here is why

**Built:** `agent/diagnosis/baseline.py::BaselineDiagnosis` — a `DiagnosisPort`
like every other, so swapping it in changes exactly one component and the
comparison isolates the diagnosis layer rather than measuring some other
difference between two pipelines. It is deliberately context-blind: every
ambiguous case gets `TRANSIENT_INFRA`, retry once, fixed 60-minute delay. No
branching on reason, downtime, amount, or attempt history.

**Rejected: a "smarter" baseline that branches on `error.reason`.** That is
precisely what `agent/triage.py` already does for the ~70% CLEAN majority, and
those cases never reach a `DiagnosisPort` at all. A reason-branching baseline
would silently borrow the same taxonomy the AI arm uses, and `A3 - A1` would then
measure "LLM vs. lookup table on the residual" instead of "does asking why help at
all?". `tests/test_baseline.py` (6 tests) asserts the context-blindness property
directly, so a future edit can't quietly make the baseline smart and invalidate
every comparison built on it.

**Bug found on the first comparison run — the AI arm had never actually run.**
`evalharness/run.py` read `GROQ_API_KEY` from `os.environ`, but nothing loaded
`.env` (earlier smoke tests parsed it manually, which is why they worked). All 88
ambiguous cases failed closed to tier-3 UNKNOWN with
`"GroqError: The api_key client option must be set"`, producing macro-F1 exactly
0.000 and 122 abandoned cases — which reads as a catastrophic model result rather
than a missing config value. Two things worked exactly as designed here: the
fallback ladder failed closed under total API failure instead of guessing, and
ADR-015's `last_error` surfacing made this diagnosable in a single audit-log
query rather than a hunt. Fixed with a minimal stdlib `load_dotenv()` (no
python-dotenv dependency for ~8 lines) plus a **fail-fast guard**: `--provider
groq|claude` now refuses to start without its key rather than producing a
plausible-looking but meaningless report.

**Results, same seed, same corpus, same policy/executor/ledger — only the
`DiagnosisPort` differs:**

| Metric | Baseline (A1) | Groq AI (A3) | Reading |
|---|---|---|---|
| Incremental ₹/1,000 | 5,266,945 | 4,343,291 | **Baseline higher** |
| 95% CI | [2.24M, 8.00M] | [1.29M, 6.98M] | Overlap almost entirely |
| Gross recovery rate (treated) | 29.5% | 27.3% | Baseline higher |
| Wasted-attempt rate | 6.7% (12/178) | 5.9% (9/153) | AI slightly better |
| Cases abandoned, zero spend | 49 | 74 | AI more conservative |
| Ambiguous macro-F1 | 0.151 | 0.260 | AI higher — but see below |

**Honest conclusion: the AI arm does not beat the baseline here, and this corpus
cannot answer whether it would.** Two independent reasons, both worth stating
plainly rather than burying:

1. **The CIs overlap almost entirely**, and the point estimate favours the
   baseline. At n=300 with a 25% holdout this design cannot resolve a difference
   of this size — consistent with the ≈10pp MDE already documented in
   `docs/06_evaluation.md`. The mechanism is legible: the baseline retries more
   (178 vs 153 attempts), and under the current response model more retries
   mechanically recovers more gross money, while the AI arm's extra caution (74 vs
   49 abandoned) trades recovered rupees for a lower wasted-attempt rate.

2. **The macro-F1 comparison is not measuring diagnosis quality at all.**
   `datagen/generate.py::_pick_true_class()` assigns AMBIGUOUS labels from a fixed
   weight distribution with **zero dependence on any input feature** — not reason,
   not downtime, not amount, not attempt history. The label is noise with respect
   to everything the model can see, so chance is the ceiling by construction. The
   observed numbers are exactly what chance predicts: always-guess-majority scores
   ≈0.143 (baseline observed 0.151), guess-proportionally scores ≈0.25 (AI
   observed 0.260). The AI's apparent macro-F1 "win" is the arithmetic gap between
   two chance strategies, not evidence of better reasoning.

**Not fixed in this ADR, deliberately.** Making AMBIGUOUS labels depend on latent
features the model could actually infer is a data-generator redesign, not a
baseline implementation, and doing it while looking at these results risks tuning
the generator until the AI wins — exactly the failure `eval/PREREGISTRATION.md`
exists to prevent. Recorded as the top blocker for Phase 3 instead. The
`data/dataset/eval/` held-out split is untouched by this work and remains sealed.

Full suite after all changes: 68/68 (62 prior + 6 baseline).

## ADR-017 — Policy engine v2: ALLOW/DENY/REVIEW, four required decision fields, four new gates, and one real LLM-bypass fix

**Decision vocabulary reduced to three, as specified.** `DEFER` and `DOWNGRADE`
are gone. "Permitted, but later" is an `ALLOW` carrying a later `execute_at` — the
timing already lived in the Verdict's own field, and *that* a deferral happened
already lived in `fired_rules`, which is where `evalharness/metrics.py` reads it
from. So nothing downstream lost information. `DOWNGRADE` was never returned by
any rule (documented as inert in `docs/00_project_state.md`) and was deleted
rather than carried. Fewer outcomes means fewer states a caller can mishandle.
`REVIEW` is new and routes to `QUARANTINED` — a state that existed in the state
machine but was previously **unreachable**, which `docs/00_project_state.md` had
already flagged as dead. `CONFIDENCE_FLOOR` gives it its purpose.

**Every decision now carries four fields.** `rules_version` and `decided_at` are
required on `Verdict` with **no defaults**. That is deliberate beyond
record-keeping: constructing a Verdict outside the policy engine is now an
explicit act that must supply both, rather than something that can happen by
accident and silently produce an authorization nothing authorized. It is not a
cryptographic guarantee — `Verdict` is still a plain Pydantic model — but it
removes the accidental-forgery path.

**`rules.yaml` bumped to version 2, and the v1 promise was broken knowingly.**
v1's comment promised that enabling a reserved rule would never renumber the
others. That held for *enabling* — but three genuinely new gates
(`REQUIRED_STATE`, `SUPPORTED_ACTION`, `DUPLICATE_ACTION`) had to sit ahead of the
existing ones, which renumbers. The version bump is exactly the mechanism for
signalling that, and since every Verdict records `rules_version`, decisions made
under v1 remain interpretable.

**Nine gates, ordered so that rule order is itself the safety argument:**
input validity (`REQUIRED_STATE`, `SUPPORTED_ACTION`) → operator override
(`KILL_SWITCH`) → measurement integrity (`HOLDOUT_GUARD`) → business gates
(`TERMINAL_CLASS`, `ATTEMPT_CAP`, `DUPLICATE_ACTION`, `EV_FLOOR`) →
`CONFIDENCE_FLOOR` last, because **a DENY must always beat a REVIEW**: a terminal
case that is also low-confidence must be refused outright, not queued for a human
as though it were merely uncertain. `tests/test_policy_engine.py` asserts that
ordering directly rather than trusting it.

**`SUPPORTED_ACTION` promoted from hardcoded guard to named rule.** ADR-015 added
it as an unconditional structural check; it is now a real `rules.yaml` entry with
its allowed set as a parameter, so the fired-rule id in the audit trail matches a
rule that actually exists in the config. The `fired_rules` id changed from
`UNSUPPORTED_ACTION` to `SUPPORTED_ACTION`, matching how every other rule records
itself by its own name rather than by its violation.

### Architecture review: LLM → proposal → policy → executor

**Traced every path. No bypass exists.** Verified by grep across the whole tree,
not by assumption:

- **Exactly one production executor call site** — `agent/pipeline.py:process_case`.
  Both production entry points (`evalharness/run.py`, `scripts/demo.py`) reach it
  through that one function.
- **Exactly one production `Verdict` construction site** — inside
  `agent/policy/engine.py::evaluate()`. The variable passed to the executor is
  always the return value of `evaluate()`; there is no branch that builds one
  another way.
- **`ExecutorPort.execute()` accepts `Verdict` only**, and `SimulatedExecutor`
  re-checks `verdict.is_executable` itself rather than trusting its caller —
  proper defense in depth, and `REVIEW` correctly evaluates as non-executable
  under the new enum.
- **The LLM holds zero tools** (invariant 2), so its only channel is the
  `DiagnosisProposal` fields.

**Every LLM-controlled field, traced to what it can reach:**

| Field | Reaches | Can it bypass a control? |
|---|---|---|
| `proposed_action` | Re-derived by policy; never passed through | No — `SUPPORTED_ACTION` + explicit action on every return |
| `recoverability` | `TERMINAL_CLASS` | Can lie to *avoid* a deny, but `ATTEMPT_CAP`/`EV_FLOOR` still bind — this is the adversarial case already covered by `tests/test_adversarial.py` |
| `confidence` | `CONFIDENCE_FLOOR` | Only via the `calibrated_confidence` seam; raising it can only move DENY→REVIEW→ALLOW *within* gates that still bind |
| `expected_outcome.probability_of_success` | **Nothing** | Deliberately: see below |
| `proposed_delay_minutes` | `execute_at` | **Was a real hole — fixed, see below** |
| `evidence`, `risks`, `missing_information`, `rationale` | Audit log only | No |

**Real bug found and fixed: unbounded `proposed_delay_minutes` crashed the policy
function.** It is an LLM-controlled integer with `ge=0` and no upper bound,
flowing straight into `timedelta(minutes=...)`. Confirmed empirically rather than
theorised: `timedelta(minutes=10**15)` raises
`OverflowError: Python int too large to convert to C int`. A model returning a
large enough delay would take `evaluate()` down mid-case — defeating the gate by
crashing it rather than by passing it. Fixed with a `max_delay_minutes` clamp
(7 days) in `rules.yaml`; `tests/test_policy_engine.py::test_absurd_proposed_delay_is_clamped_not_crashed`
covers it. Note the *direction* was already safe — the existing `max(...)` floor
meant the model could only ever push a retry later, never sooner — so this was an
availability hole, not a spend hole.

**Design choice made because of this review: `EV_FLOOR` ignores the model's own
success estimate.** The natural implementation would compute expected value from
`proposal.expected_outcome.probability_of_success` — which would let the model
inflate its way past a financial control simply by claiming a higher chance of
success. `assumed_success_rate` is a `rules.yaml` constant instead, so the rule is
blind to what the model believes. `test_ev_floor_ignores_the_models_own_success_estimate`
asserts a proposal claiming `probability_of_success=1.0` is still denied below
break-even.

**`CONFIDENCE_FLOOR` respects invariant 5** ("raw model confidence never gates").
`evaluate()` takes an explicit `calibrated_confidence` keyword; when the caller
passes nothing it falls back to `proposal.confidence` with the identity mapping
Phase 3 will replace. That is the honest current state — a real seam that exists
in code, rather than pretending a calibration step is already there.

**Not fixed, reported instead:** `Verdict` remains a plain Pydantic model, so
nothing *cryptographically* proves a given Verdict came from `evaluate()`. No such
forgery path exists in production today, and the required-fields change removes
the accidental version. A signed or engine-private token would close it fully;
that is a real hardening option, not a present vulnerability, and it was out of
scope for "fix only the paths where the LLM can bypass policy."

Full suite: **89/89** (68 prior + 21 new policy-engine tests).

## ADR-018 — Typed action contracts, and a real double-spend closed

**Built:** `agent/executors/contracts.py` declares, for every executable action,
the five things an executor must honour — input model, validation, output, typed
error states, idempotency key.

**Scope, stated honestly:** there is exactly **one** executable action today,
`Action.RETRY`. `Action.STOP` is a state transition that never reaches an executor
(`is_executable` is False for it). `Action.RECOVERY_LINK` is a reserved enum
member with no implementation anywhere, and is deliberately given **no contract**
— writing one against no implementation and no stated requirements is speculation,
not specification. Same reasoning that removed `NullExecutor` in ADR-008.

**The contract preserves invariant 8.** `ExecutorPort.execute()` still accepts a
`Verdict` and nothing else. The per-action input (`RetryInput`) is *derived* from
the Verdict under validation rather than replacing it as the port's parameter, so
each action gets its own typed parameter object without the authorization envelope
being bypassable.

| Contract element | Where |
|---|---|
| Input | `RetryInput` — frozen, `attempt_no >= 1`, `amount_paise > 0`, non-empty `case_id`/`order_id` |
| Validation | `build_retry_input()` — one implementation, so no executor can skip a precondition by accident |
| Output | `ActionResult` with typed `ActionOutcome` (SUCCEEDED/FAILED) plus a separate `replayed` flag |
| Error states | `ActionRefused(ActionErrorCode)` — six codes, partitioned into terminal vs retryable via `.retryable` |
| Idempotency key | `verdict.idempotency_key` — a pure function of the authorization |

### The bug this surfaced

**`SimulatedExecutor` derived the idempotency key from a live `attempts` read at
dispatch time, not from the Verdict.** The module docstring claimed this "makes
at-least-once scheduler delivery safe." It did the opposite:

```
execute(V)   -> key = f(case, RETRY, 1)  -> spends
attempts += 1                             (pipeline does this after execution)
execute(V)   -> key = f(case, RETRY, 2)  -> spends AGAIN
```

One authorization, two spends — triggered by exactly the re-delivery pattern
at-least-once dispatch produces. Not reachable in Phase 1 (execution is
synchronous, nothing re-delivers), but Phase 2's scheduler is precisely what
introduces it, and the code already claimed to be safe against it.

**Fixed** by binding `attempt_no` onto `Verdict` at authorization time (set by
`evaluate()` from the state it actually evaluated) and deriving the key from the
Verdict alone. Re-delivery now always maps to the same key.

**`ActionOutcome` deliberately has no REPLAYED member.** Collapsing replay into
the outcome would lose whether the *original* attempt succeeded; `replayed` is a
separate boolean and `outcome` always carries the real result.

**Refusal vs failure is now a type-level distinction.** `ActionRefused` means the
action never ran and must not consume attempt budget; a `FAILED` ActionResult
means it ran and did. Previously both were expressed as a bare `ValueError` or a
`succeeded=False` result, which conflated them.

### `tests/test_idempotency.py` deleted, not fixed

Its `test_different_attempt_numbers_are_not_deduplicated` **asserted the buggy
behaviour as intended** — it claimed to test "a genuinely new attempt" but built
that scenario by re-delivering the *same* verdict after mutating `attempts`, which
is not a new authorization at all. Both of its tests are superseded by
`tests/test_action_contracts.py`, which covers the same ground correctly:
re-delivery of one authorization must spend once
(`test_redelivery_after_attempts_incremented_does_not_double_spend`), while two
distinct verdicts must both run (`test_a_genuinely_new_authorization_is_not_deduplicated`).
Deleting was the right call over editing, because keeping a test that asserts the
defect alongside one that asserts the fix would leave the suite self-contradictory.

Full suite: **105/105** (89 prior − 2 deleted + 18 new contract tests).

## ADR-019 — Executor implemented against the contracts; two more rejection paths closed

Auditing `SimulatedExecutor` against the four required rejections found two
already covered and two genuinely missing:

| Rejection | Before | After |
|---|---|---|
| Invalid commands | ✓ `INVALID_PARAMS` | unchanged |
| Unauthorized commands | ✓ `NOT_AUTHORIZED` | unchanged |
| Duplicate commands | partial — only *completed* duplicates | **`DUPLICATE_IN_FLIGHT`** added |
| Invalid state transitions | **absent** | **`ILLEGAL_STATE`** added |

**Gap 1 — the executor never read `cases.state`.** It trusted that the policy
engine's `REQUIRED_STATE` rule had checked it. That defeats defense in depth for a
concrete reason, not a theoretical one: `REQUIRED_STATE` checks state at
*authorization* time, and time passes before dispatch. A case can reach a terminal
state between the two, and an executor that trusts the verdict to still be current
has no way to notice. Added `check_executable_state()` to the contract, with
`EXECUTABLE_CASE_STATES = {SCHEDULED, EXECUTING}` — the two states from which a
dispatch legitimately arrives (the pipeline moves a case to EXECUTING immediately
before calling; a Phase 2 scheduler would hand one over in SCHEDULED).

**Gap 2 — an in-flight duplicate fell through and executed.** The idempotency
lookup filtered on `executed_at IS NOT NULL`, so a row that was *dispatched but
not yet completed* did not match, execution proceeded, and the subsequent
`INSERT OR REPLACE` silently overwrote the in-flight row. Now refused with
`DUPLICATE_IN_FLIGHT`, classified **retryable** — once the in-flight attempt
completes, a later delivery lands on the replay path instead of conflicting.

**Check ordering is load-bearing, and is the one design judgment here.** The
completed-duplicate replay is checked **before** the state check, deliberately.
After a successful attempt the case is legitimately `RECOVERED`; if the state
check ran first, a re-delivery would be refused with `ILLEGAL_STATE`, a scheduler
would read that as failure, and it would retry forever. Returning the original
result is what makes at-least-once delivery *converge* rather than loop.
`test_completed_duplicate_replays_even_from_a_terminal_state` pins that ordering
so a future refactor cannot quietly invert it.

**On "reject duplicate commands" — a judgment call worth surfacing.** Exact
re-delivery of a *completed* authorization is still answered with an idempotent
replay rather than a rejection, because that is what makes at-least-once dispatch
safe (a rejection would be read as failure). "Reject" is honoured for the case
where it is genuinely correct: a conflicting, still-in-flight duplicate, where
there is no original result to return. If the intent was that *all* duplicates
raise, this is the line to revisit.

**Verified beyond unit tests:** a full `evalharness` run over the 300-case corpus
produced numbers **identical** to the pre-change baseline (incremental
₹5,266,944.63, 178 attempts, 49 abandoned, holdout contamination 0, chain
verifies, counters reconcile) — confirming the new rejections block nothing the
pipeline legitimately dispatches.

Full suite: **115/115** (105 prior + 10 new).

## ADR-020 — State machine typed and closed; the orphaned-case gap solved

### The gap that mattered

`agent/pipeline.py` moves a case to `EXECUTING` and *then* calls the executor.
ADR-019 gave the executor six ways to raise `ActionRefused` — and **`EXECUTING`
had no edge to anywhere those refusals could land**. Its allowed set was
`{RECOVERED, FAILED_ATTEMPT, ABANDONED}`, all reachable only via `transition()`
calls the function never reaches because the exception escaped. A refused command
stranded the case in a **non-terminal state with no way out**, permanently.

Not hypothetical: it is the direct consequence of the raise paths added one ADR
earlier. It never fired in the dev corpus only because `SimulatedExecutor` had no
reason to refuse.

**Fixed at both ends.** Two new edges — `EXECUTING -> SCHEDULED` (retryable
refusal, back to the queue) and `EXECUTING -> QUARANTINED` (terminal refusal,
needs a human) — plus a `try/except ActionRefused` in the pipeline that routes on
`refusal.retryable`, records a new `ACTION_REFUSED` audit event, and returns a
`DecisionTrace` instead of propagating.

`ACTION_REFUSED` is a **distinct event type from `ACTION_RESULT`** on purpose: a
refusal means nothing ran and no attempt was consumed. Conflating them would
corrupt `audit.replay()`'s attempt count, which `verify_counters()` checks against
the denormalised column — so the bug would have surfaced as a confusing counter
mismatch rather than as what it is.

### Three sources of truth for "terminal", collapsed to one

Terminality was encoded in three places that could drift independently:
`agent/models.py:TERMINAL_STATES` (a frozenset that **nothing ever read** — dead
code), the empty sets in `VALID_TRANSITIONS`, and a hand-written string set in
`tests/test_adversarial.py`. Now derived once from the transition table
(`TERMINAL_STATES = {s for s, targets in VALID_TRANSITIONS.items() if not targets}`),
the dead constant deleted, and the test importing the real one. This matters
beyond tidiness: `QUARANTINED` is semantically "awaiting human review" and will
*stop* being terminal the moment a resolution path is implemented — derived
terminality follows that automatically, three hand-maintained copies would not.

### Typed, not stringly-typed

`VALID_TRANSITIONS` is now keyed by `CaseState` rather than raw strings, and
`transition()` coerces its target to `CaseState` first. Consequence worth naming:
a typo like `"RECOVERD"` previously raised `IllegalTransition` — a misleading
diagnosis, since the transition was not illegal, the state did not exist. It now
raises `ValueError` naming the bad value.

### Tests

`tests/test_state_machine.py` (98 tests) is **exhaustive over the full 9x9 state
product** rather than illustrative: every pair is asserted allowed or rejected, so
adding a state or an edge without deciding what it means for every other state
fails the suite instead of passing silently. Plus table-integrity properties — no
self-transitions, every target is a real state, and **every non-terminal state can
reach a terminal one** (a fixed-point search, which is precisely the property
`EXECUTING` violated).

`tests/test_refusal_recovery.py` (11 tests) covers the pipeline half: each of the
eight error codes lands the case in the right state, a refusal consumes no attempt
budget, the refusal is auditable, and the hash chain still verifies.

One fixture bug found while writing them: the first version used `seed=7`, which
put the test case in the **holdout** arm, so `HOLDOUT_GUARD` denied it before it
ever reached an executor and no refusal could occur. The corrected fixture asserts
`assign_cohort(...) is TREATED` rather than assuming it.

**Verified end to end:** a full `evalharness` run produced numbers identical to
the pre-change baseline (₹5,266,944.63, 178 attempts, 49 abandoned, contamination
0, chain verifies, counters reconcile).

Full suite: **224/224** (115 prior + 98 state machine + 11 refusal recovery).
