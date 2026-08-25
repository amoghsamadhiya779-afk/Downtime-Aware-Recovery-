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
