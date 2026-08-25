# CLAUDE.md

<!-- last_verified: 2026-08-25 -->

Downtime-aware payment recovery agent. Razorpay AI Buildathon 2026, **Track 03 — AI Revenue Recovery**.
Submission due **5 September 2026**: public repo + 5-minute pitch video + architecture.

## Read before you act

| Before you… | Read |
|---|---|
| change policy behaviour | `ARCHITECTURE.md` §5 and `agent/policy/rules.yaml` |
| cite any Razorpay / NPCI / TRAI fact | `EVIDENCE.md` — never assert one from memory |
| propose a feature, tool, or alternative | `DECISIONS.md` — it may already be rejected |
| resume work after a break or compaction | `STATE.md` |
| touch evaluation or report any number | `eval/PREREGISTRATION.md` |
| compare against other submissions | `research/COMPETITORS.md` |

Close every session by rewriting `STATE.md` and appending any new ADR to `DECISIONS.md`.

## Hard invariants

Violating any of these is a bug, not a tradeoff.

1. **One code path, two modes.** Live and replay differ only by an injected `Clock` and `ExecutorPort`.
2. **The LLM holds zero tools.** Pure function, structured in → structured out. No API, DB, filesystem, or network handle.
3. **No untrusted free text enters a prompt.** Enum and numeric fields only.
4. **`HOLDOUT_GUARD` is policy rule 2 and unconditional.** Cohort is immutable, enforced by DB trigger.
5. **Raw model confidence never gates.** Policy consumes `calibrated_confidence` only.
6. **Fail closed.** An unknown taxonomy combination becomes STOP + human queue, never an attempt.
7. **`agent/` must never import `datagen/`.** CI-enforced.
8. **`Verdict` is the only type an executor accepts.** Never a `DiagnosisProposal`.
9. **No hand-written numbers in docs.** The README quotes generated `eval/report.md`.
10. **Policy thresholds live in `rules.yaml` only.** A threshold appearing in prose is a bug.

## Anti-goals

Not a payment router — Razorpay Optimizer exists and is better (`EVIDENCE.md` E4).
Not a generic dunning bot — already a shipped Razorpay feature (E5).
Not a chatbot over payment data. No multi-agent orchestration where one deterministic function
suffices. Nothing offense-capable (Track 02's disqualifier, and a good rule regardless).

## The question this project must survive

> *"Why doesn't Optimizer already do this?"*

Optimizer routes **before** an attempt. This decides what happens **after** one has failed — whether,
when, by which instrument, and whether to contact a human — under cost, fatigue and compliance limits
that live merchant-side, not gateway-side. Full framing in `PRODUCT_THESIS.md`.

## Stack

Python 3.11+ · stdlib `sqlite3` (WAL) · Pydantic v2 · pytest + hypothesis.

AI-1 (diagnosis) has two interchangeable backends behind `DiagnosisPort`, sharing
one prompt/validation/fallback implementation (`agent/diagnosis/prompting.py`):
Anthropic SDK (Claude Sonnet 5, paid) and Groq SDK (`openai/gpt-oss-120b`, free
tier, no card — EVIDENCE.md E23/E24). Select via
`evalharness/run.py --provider {stub,claude,groq}`.

No Redis, Celery, vector DB, or agent framework — none serves a stated requirement. **Adding a
dependency requires an ADR in `DECISIONS.md`.**

## Layout

```
agent/          decision pipeline — ingest, triage, diagnosis, policy, executors
  policy/       pure code + rules.yaml (single source of truth for thresholds)
datagen/        synthetic corpora + hidden ground truth — NEVER imported by agent/
eval/           harness, pre-registration, generated report
web/            read-only UI
research/       competitive survey
```

## Working rules

- Evidence first. Label every external claim VERIFIED / INFERENCE / ASSUMPTION / UNKNOWN with a source.
- Prefer a narrow, excellent loop over breadth. Depth on payment-failure recovery is the whole bet.
- Every feature must answer: why necessary, why AI adds value, how measured, how it fails, how contained.
- If a build-day gate fails, cut scope — never cut the gate. The gates are the submission.
