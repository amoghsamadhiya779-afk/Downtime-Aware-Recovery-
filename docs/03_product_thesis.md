<!-- Reverse-engineered: the thesis as actually realized by the code on disk, not the
     aspirational version at the repo root. Where a claim in root PRODUCT_THESIS.md
     is not yet backed by running code, it is marked DESIGNED, NOT DEMONSTRATED below.
     This document exists so the gap between intent and reality is never implicit. -->

# Product Thesis (as-built)

## What the current code actually does, in one paragraph

Given a synthetic or real payment-failure record, the system deterministically
classifies the ~70% of cases where the failure reason maps unambiguously to a
cause, and for the remaining ~30% calls a diagnosis component (a hardcoded stub in
every run to date; a real Claude-backed implementation exists and is unit-tested
against a fake client but has never been called against the live API) to propose a
class and an action. A pure, five-rule policy function then independently decides
whether to retry, defer the retry past a concurrent downtime window, or stop —
regardless of what the diagnosis component proposed, provably so under an
adversarial model. Every step is written to a tamper-evident log. A separate
evaluation harness replays a batch of such cases and reports the difference in
recovered rupees between an acted-upon group and a held-back group, alongside a
mandatory list of things that look wrong about the run.

## Claims this thesis makes, and their current evidence status

| Claim | Status | Evidence |
|---|---|---|
| Retries can be timed against Razorpay's live downtime signal | **DESIGNED, PARTIALLY DEMONSTRATED** | `DOWNTIME_DEFER` computes correct deferral against `DowntimeContext` (7 passing boundary tests in `test_downtime.py`), and `scripts/demo.py` shows one hand-built case being correctly deferred. On the random n=300 dev corpus, it fired **zero times** — not a bug, but a real gap between "the mechanism works" and "the mechanism has been shown to matter at scale" |
| Terminal failures are stopped early, spending nothing | **DEMONSTRATED** | `TERMINAL_CLASS` rule + `test_adversarial.py`'s 60-case run + `scripts/demo.py`'s second trace all show zero attempts spent on a hidden-or-proposed-terminal case |
| Money recovered is measured against a randomized holdout, not reported gross | **DEMONSTRATED, mechanically** | `evalharness/metrics.py` computes both and prints them side by side every time; cohort assignment is DB-immutable | The *number itself* has only ever been computed against `StubDiagnosis` output, so the incremental figure produced so far describes the stub's behavior, not the intended system's |
| AI adds value over rules alone | **NOT DEMONSTRATED** | No ablation arm (rules-only vs. full) has ever been run. This is the single largest gap between the thesis and the evidence — see below |
| The diagnosis component reasons well about ambiguous failures | **NOT DEMONSTRATED** | Every macro-F1 number produced so far (e.g., 0.131 on the last real run) came from `StubDiagnosis`, which is a fixed function of `error.reason` alone and was never intended to be evaluated as if it were the real model. `ClaudeDiagnosis` exists and its *error-handling* is tested, but its *diagnostic quality* has zero measurement |
| The system survives an adversarial model without breaching safety limits | **DEMONSTRATED** | `test_adversarial.py` is a real, passing test (as of the last run) with a model forced to lie about recoverability on every case |
| A duplicate action doesn't double-spend | **DEMONSTRATED** (as of this session's addition) | `test_idempotency.py` |
| The system integrates with real Razorpay infrastructure | **NOT DEMONSTRATED** | Zero API calls to any Razorpay endpoint exist anywhere in the codebase. `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` are declared in `.env.example` but read by no code |

## The panel question, re-examined against the actual code

Root `PRODUCT_THESIS.md` states the system must survive: *"Why doesn't Optimizer
already do this?"* — with the answer being that Optimizer decides **before** an
attempt and this system decides **after** one has failed.

The current code is consistent with that framing (nothing in `agent/` performs
gateway selection; every decision in `agent/policy/engine.py` operates on an
already-failed `PaymentFailure`), but the framing itself is not something the code
can prove — it's an architectural positioning claim, not a measured one. It stands
or falls on the pitch, not on `eval/report.md`.

## What "AI role" means in the code today, precisely

The root thesis says the AI "classifies recoverability... on the ambiguous tail
only" and "proposes, never authorizes." Both halves of that sentence are
structurally true of the current code:

- **Never authorizes:** confirmed by type signature — `ExecutorPort.execute()`
  takes a `Verdict`, and nothing in the codebase constructs a `Verdict` from a
  `DiagnosisProposal` without passing through `agent/policy/engine.py:evaluate()`.
- **Ambiguous tail only:** confirmed by control flow — `process_case()`'s `if
  tr.is_ambiguous:` branch is the only call site of `diagnosis_port.diagnose()`.

What is *not* yet true: that this AI role is *necessary*. The architecture makes it
structurally cheap to answer that question (swap `StubDiagnosis` for a rules-only
stand-in that always predicts the triage majority class, or simply compare `A1`
against `A3` per the pre-registered ablation design), but the comparison has not
been run. Until it has, "AI necessity" is a claim the architecture *permits* being
measured, not a claim that *has been* measured.

## Honest summary

The control system the thesis describes — signal, classify, propose, gate, act,
measure, with a holdout and an adversarial-safety guarantee — exists and runs. The
part of the thesis that depends on the AI component actually being good at its one
job has not yet been tested, because every run to date substituted a hardcoded
placeholder for it. That is the accurate, current gap between this project's
architecture and its evidence, and closing it (real `ClaudeDiagnosis` runs, then
the rules-only ablation) is the highest-value remaining work per `STATE.md`.
