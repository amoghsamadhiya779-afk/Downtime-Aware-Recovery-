# EVIDENCE.md

<!-- last_verified: 2026-08-25 -->

Every external claim this project relies on, with a label and a source. **Nothing about Razorpay,
NPCI, TRAI, or the Buildathon may be asserted anywhere in this repo unless it has an ID here.**

Labels: **VERIFIED** (primary source read) · **INFERENCE** (reasoned from verified facts) ·
**ASSUMPTION** (chosen, not established) · **UNKNOWN** (open).

---

## Buildathon program

| ID | Claim | Label | Source |
|---|---|---|---|
| E1 | Student-only hiring funnel for AI Builder Intern. ₹75,000/month, 6 or 12 months, in-person Bangalore, starting September. Applications close 5 Sep 2026. | VERIFIED | https://razorpay.com/buildathon/ |
| E2 | Submission = public repo + 5-minute pitch video + architecture. Then panel. No resume screen, no aptitude test, no group discussion. | VERIFIED | https://razorpay.com/buildathon/ |
| E3 | Track 03 brief: *"Build an agent that detects revenue at risk, determines the right intervention, and executes a bounded recovery workflow: from payment failures and checkout abandonment to overdue receivables."* Bar: *"Don't just identify the problem. Show measured money recovered across a batch, with compliant escalation, stopping rules, and an audit trail."* | VERIFIED | https://razorpay.com/buildathon/ |
| E3b | All five track bars are measurement statements (precision/recall on held-out sets; money recovered across a batch; match rate plus honest exception list; *"One cherry-picked match proves nothing"*). | VERIFIED | https://razorpay.com/buildathon/ |
| E3c | Track 02 states *"Strictly defense-only: anything offense-capable is disqualified"* — the only explicit disqualifier published. | VERIFIED | https://razorpay.com/buildathon/ |
| E3d | Razorpay describes the AI Builder role as someone who can *"turn ambiguous business and product problems into working AI systems"* and who sees *"every workflow as an agent loop."* | VERIFIED | https://razorpay.com/ai-builders/ |
| E3e | The application also asks what broke during development and how it was solved. | VERIFIED | secondary aggregators; **re-confirm on the application form itself** |
| E3f | No scoring rubric, weights, or criteria list is published beyond the per-track bar sentences. | VERIFIED (absence) | https://razorpay.com/buildathon/ |
| E3g | The build must be complete by 5 Sep, because the application requires the artifacts. | INFERENCE | from E1 + E2 |
| E3h | Post-application timeline for pitch and panel rounds. | UNKNOWN | not published |

## Razorpay platform surface

| ID | Claim | Label | Source |
|---|---|---|---|
| E4 | **Optimizer** performs AI/ML smart routing across 100+ payment providers using ~150 parameters and ~600M data points, claiming up to ~10% success-rate uplift. | VERIFIED | https://razorpay.com/docs/payments/optimizer/ and Razorpay blog |
| E5 | **Subscriptions** auto-retries failed recurring payments on a fixed schedule (T+3, three attempts, once daily excluding the charge date) and emails the customer a card-update link. Subscription goes `pending` during retries, `halted` after exhaustion. | VERIFIED | https://razorpay.com/docs/payments/subscriptions/payment-retries/ |
| E6 | **Payment Downtime entity** fields: `id`, `entity`, `method` (card/netbanking/upi), `begin`, `end` (nullable when unknown), `status` (scheduled/started/resolved/updated), `scheduled` (bool), `severity` (high/medium/low), `instrument` (`bank` \| `network`+`type` \| `vpa_handle`), `flow` (collect/intent/in_app), `created_at`, `updated_at`. | VERIFIED | https://razorpay.com/docs/api/payments/downtime/entity/ |
| E7 | Downtime webhooks: `payment.downtime.started`, `.updated`, `.resolved`. Payment webhooks: `payment.authorized`, `.captured`, `.failed`. | VERIFIED | https://razorpay.com/docs/webhooks/payloads/payments/ |
| E8 | Razorpay's downtime documentation tells merchants to poll or subscribe and then *"plan the remediation steps accordingly"* — detection is shipped, the decision layer is left to the merchant. | VERIFIED | https://razorpay.com/docs/api/payments/downtime/ |
| E9 | Error responses carry `code`, `description`, `field`, `source`, `step`, `reason`, `metadata`. `source` values vary by method — cards: customer/business/internal/gateway/issuer_bank; UPI adds customer_psp/network/beneficiary_bank; netbanking: customer/business/internal/issuer_bank; emandate adds bank/gateway. | VERIFIED | https://razorpay.com/docs/errors/payments/payment-methods-error-parameters/ |
| E10 | Razorpay publishes an official MCP server. | VERIFIED | https://github.com/razorpay/razorpay-mcp-server |
| E11 | Exhaustive list of `reason` string values across all methods. | UNKNOWN | docs paginate; **harvest from the golden set instead of guessing** |

## Regulatory — ⚠ ALL UNVERIFIED, BLOCKING

| ID | Claim | Label | Status |
|---|---|---|---|
| **E12** | NPCI caps UPI Autopay retries at 3 per mandate. | **ASSUMPTION** | Taken secondhand from a competitor repo (`atharavmahangade-spec/mandate-rescue`), **not** from an NPCI circular. |
| **E13** | NPCI execution windows restrict mandate presentation to defined time bands. | **ASSUMPTION** | Same secondhand source. |
| **E14** | RBI e-mandate AFA thresholds (₹15,000 general; higher for SIP/insurance/credit card). | **ASSUMPTION** | Same secondhand source. |
| **E15** | TRAI/DND quiet hours for commercial communication. | **ASSUMPTION** | Not sourced at all. |

**Blocking rule:** rules E12–E15 ship in `rules.yaml` with `citation: null` and `verified: false`, and
are **excluded from every compliance claim in the README, the architecture doc, and the pitch video**
until a primary NPCI / RBI / TRAI source is read and recorded here. Encoding a constraint is fine;
*claiming regulatory compliance* on a secondhand number is not.

## Competitive field

| ID | Claim | Label | Source |
|---|---|---|---|
| E16 | 218 public GitHub repositories match "razorpay buildathon" as of 25 Aug 2026, many updated within minutes of each other. | VERIFIED | GitHub repository search |
| E17 | Across a 7-repo deep sample plus ~15 by description: no project uses real Razorpay APIs, none consumes the Payment Downtime API, none runs a randomized holdout, all grade themselves with a self-authored response model, and only one reports calibration. | VERIFIED | see `research/COMPETITORS.md` |
| E18 | Track popularity 03 ≫ 02 > 04 ≫ 01. | INFERENCE | sample distribution, not a published figure |

## AI providers

| ID | Claim | Label | Source |
|---|---|---|---|
| E23 | Groq's free API tier requires no credit card and charges no per-token cost, gated only by rate limits: ~30 req/min, up to ~14,400 req/day organization-wide (varies by model). | VERIFIED | web search this session, cross-referenced against multiple sources; see DECISIONS.md ADR-011 |
| E24 | Groq deprecated their Llama chat models (including `llama-3.3-70b-versatile`) in favor of the `gpt-oss` line; confirmed live via `GET /openai/v1/models` with a real API key on 2026-08-25 — available models included `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.6-27b`, no `llama-3.3*` variant. | VERIFIED — checked directly against the live API, not a search result | live API call, this session |
| E25 | Google Gemini's free API tier states prompts/responses "may be used to improve Google's products." | VERIFIED | web search this session |
| E26 | Gemini free tier (as of the search): Gemini 2.5 Flash-Lite 15 req/min / 1,000 req/day; Gemini 2.5 Flash 10 req/min / 250 req/day. | VERIFIED, dated — these change often | web search this session |

## Project assumptions

| ID | Claim | Label |
|---|---|---|
| E19 | Builder is an enrolled student (eligible per E1). | ASSUMPTION — user-stated |
| E20 | Razorpay test-mode account with API keys is obtainable. | ASSUMPTION — user-stated, verify Day 1 |
| E21 | ~6+ hours/day available until 5 Sep. | ASSUMPTION — user-stated |
| E22 | Baseline organic recovery rate ~30%, used only for the power calculation. | ASSUMPTION — not measured; if wrong, the MDE changes and `eval/report.md` must say so |
