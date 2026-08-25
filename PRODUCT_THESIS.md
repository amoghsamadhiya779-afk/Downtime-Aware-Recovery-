<!-- last_verified: 2026-08-25 -->

# Product Thesis

> A merchant-side recovery agent that times bounded retries against Razorpay's live
> downtime signal, stops early on unrecoverable failures, and proves its rupees
> against a randomized holdout instead of a self-graded simulator.

Razorpay AI Buildathon 2026, Track 03 — AI Revenue Recovery. See [EVIDENCE.md](EVIDENCE.md)
for every external claim below and [ARCHITECTURE.md](ARCHITECTURE.md) for how it's built.

## PROBLEM

- Retries fire on fixed schedules that ignore whether the issuer is degraded right
  now, burning a capped attempt budget into windows where success is near-impossible.
- Terminal failures (fraud decline, closed account) are chased identically to
  transient ones, spending contact budget on revenue that was never recoverable.
- "Recovered revenue" is reported gross, so no one knows how much would have arrived
  with zero intervention at all.

## USER

Payments / growth ops owner at a mid-market Indian merchant carrying meaningful UPI
and netbanking failure volume. Current tooling: a fixed retry schedule, a dunning
template, a spreadsheet. Accountable for a rupee number they cannot attribute to
their own actions.

## CURRENT FAILURE

- Retries land inside issuer downtime and consume attempts NPCI caps at three for
  recurring mandates (E12 — unverified, see below).
- Customers are nudged for failures they cannot fix, because the failure was
  bank-side, not customer-side.
- Any payment that later succeeds is counted as recovered, including the ones the
  customer would have retried unaided.

## WHY EXISTING SOFTWARE IS INSUFFICIENT

- **Optimizer routes; it does not recover.** It selects the best gateway *before* an
  attempt (E4). Once a payment has failed, the question is no longer routing — it's
  whether, when, by what instrument, and whether to contact a human, under cost and
  compliance limits that live merchant-side.
- **Subscriptions auto-retry is a schedule, not a decision** — T+3, three attempts,
  daily (E5) — and scoped to subscriptions only, not one-time checkout or link failures.
- **Razorpay publishes downtime and stops there.** The Payment Downtime API exposes
  `severity`, `instrument`, `begin`/`end` (E6), and its own docs hand remediation to
  the merchant (E8). Detection is shipped; the decision layer is not.

### The question this project must survive

> *"Why doesn't Optimizer already do this?"*

Optimizer decides **before** an attempt. This decides what happens **after** one has
already failed. If that distinction can't be stated in 60 seconds, the submission is
dead regardless of code quality.

## AI ROLE

- Classify recoverability from `source × step × reason` only where the taxonomy is
  ambiguous or unseen — rules handle the clear majority (see `agent/triage.py`).
- Correlate a failure against concurrent downtime to separate "the bank is down"
  from "this instrument is bad."
- Write the rationale attached to every decision in the audit log.
  **It proposes; it never authorizes** — see `agent/diagnosis/port.py`.

## AGENT ACTION

Exactly three, enforced by `agent/policy/engine.py`:

- Schedule one bounded retry at time T, deferred past known downtime `end`.
- Issue a recovery link with an alternate instrument *(reserved — Phase 2, `Action.RECOVERY_LINK`)*.
- **STOP** — mark terminal, record the reason, spend nothing further.

## DETERMINISTIC CONTROLS

- Attempt caps, NPCI execution windows, contact caps, quiet hours — tested constants
  in `agent/policy/rules.yaml`, never prompt text.
- The policy engine holds veto and is zero-LLM; `tests/test_policy.py` passes with
  the Anthropic SDK uninstalled — verified this session.
- Idempotency keys, append-only hash-chained audit log, kill switch (Phase 1);
  shadow mode and circuit breaker (Phase 2).

## SUCCESS METRIC

- **Primary — incremental ₹ recovered per 1,000 at-risk vs. randomized holdout**,
  with bootstrap CI. Gross is always shown beside it; the gap is the argument.
- **Co-primary — wasted-attempt rate**: attempts spent on hidden-terminal cases.
- Every headline number re-reported across a sensitivity sweep of the response-model
  assumption (Phase 3).

## FAILURE SCENARIOS

- Model calls a terminal failure recoverable → wasted attempts, customer spam.
  **Contained by:** policy veto (`TERMINAL_CLASS`) plus `ATTEMPT_CAP`, which bind
  regardless of model confidence — proven in `tests/test_adversarial.py` with a
  model forced to `RETRY, confidence 1.0` on every case.
- Downtime signal arrives late or wrong → a retry lands in a dead window.
  **Contained by:** downtime is advisory input to *timing* only, never a sole gate.
- The simulator flatters the result → the entire number is an artifact.
  **Contained by:** the sensitivity sweep (Phase 3) and one genuinely real
  test-mode path (Phase 2).

## BUSINESS VALUE

- Recovers revenue on already-lost transactions with no additional traffic spend —
  marginal cost is one retry and at most one message.
- Converts an unattributable ops number into a defensible incremental one, which is
  what makes it budgetable.
- Cuts contact fatigue and compliance exposure by stopping early on cases that were
  never going to convert.

## 5-MINUTE DEMO

- Replay a seeded batch against a real downtime timeline: naive fixed-schedule arm
  vs. agent arm vs. untouched holdout, money counter moving, incremental gap widening.
- Open one decision trace end to end (`make demo`) — failure → triage → diagnosis →
  policy verdict (with fired rule IDs) → action → outcome — then a second case where
  the policy engine vetoed the model.
- Live test-mode: create order, fail it, agent issues a recovery link, payment
  succeeds (Phase 2). Then hit the kill switch mid-batch and show execution halt.

---

**Compliance disclosure:** the NPCI/TRAI constants this thesis references (E12–E15)
are secondhand claims, not primary-sourced. They execute in `rules.yaml` but back no
compliance claim anywhere in this repo until `EVIDENCE.md` carries a primary source.
See `DECISIONS.md` for the rejected alternatives that led here.
