"use strict";

/* ============================================================================
   Recovery Control Plane — dashboard client
   Talks to the endpoints in scripts/serve_dashboard.py exactly as they exist:
     GET  /api/health
     GET  /api/metrics
     GET  /api/transactions?limit&offset&search&cohort_filter&method_filter&state_filter
     GET  /api/transaction/<case_id>   -> 9-phase detail (agent/dashboard.py)
     GET  /api/trace/<case_id>
     POST /api/demo/trigger  { scenario }
   No framework, no build step — this file is served as-is by the stdlib server.
   ========================================================================= */

const state = {
  limit: 25,
  offset: 0,
  total: 0,
  search: "",
  filters: { state: "ALL", method: "ALL", cohort: "ALL" },
  rows: [],
};

const DEMOS = [
  {
    key: "duplicate_event",
    title: "Duplicate event",
    desc: "Re-deliver the same authorization twice. Must return the original result, not spend again.",
    icon: '<path d="M8 8h10v10H8zM6 6h10v2M6 6v10h2"/>',
  },
  {
    key: "invalid_ai_output",
    title: "Invalid AI output",
    desc: "Malformed model response. Must fail closed to a queued case, never a guessed action.",
    icon: '<path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
  },
  {
    key: "policy_rejection",
    title: "Policy veto",
    desc: "A confident model asks to retry past the attempt cap. Policy must deny regardless of confidence.",
    icon: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="M9.5 12.5 11 14l3.5-3.5"/>',
  },
  {
    key: "execution_timeout",
    title: "Gateway timeout",
    desc: "The executor cannot confirm outcome. Must quarantine for reconciliation, never assume success.",
    icon: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
  },
];

const STATE_BADGE = {
  RECOVERED: "ok",
  FAILED_ATTEMPT: "bad",
  ABANDONED: "mute",
  QUARANTINED: "warn",
  HOLDOUT_CLOSED: "info",
  SCHEDULED: "info",
  EXECUTING: "info",
  DIAGNOSED: "mute",
  DETECTED: "mute",
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function fmtINR(rupees) {
  if (rupees === null || rupees === undefined) return "—";
  const n = Number(rupees);
  if (Math.abs(n) >= 10000000) return "₹" + (n / 10000000).toFixed(2) + " Cr";
  if (Math.abs(n) >= 100000) return "₹" + (n / 100000).toFixed(2) + " L";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
function fmtINRFull(rupees) {
  if (rupees === null || rupees === undefined) return "—";
  return "₹" + Number(rupees).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPct(v, digits = 1) {
  if (v === null || v === undefined) return "—";
  return Number(v).toFixed(digits) + "%";
}
function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function titleCase(s) {
  return String(s ?? "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

// ---------------------------------------------------------------- toasts ---

function toast(title, message, kind = "ok") {
  const stack = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast is-${kind}`;
  el.innerHTML = `<div><div class="tt">${esc(title)}</div><div class="tm">${esc(message)}</div></div>`;
  stack.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .2s ease";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 220);
  }, 4200);
}

// -------------------------------------------------------------- health -----

async function loadHealth() {
  const dot = $("#health-dot"), text = $("#health-text");
  const chainChip = $("#chip-chain"), chainText = $("#chain-text");
  try {
    const h = await fetchJSON("/api/health");
    const ok = h.status === "healthy";
    dot.classList.toggle("is-bad", !ok);
    $("#chip-health").classList.toggle("is-ok", ok);
    $("#chip-health").classList.toggle("is-bad", !ok);
    text.textContent = ok ? "Healthy" : "Degraded";
    const chainOk = !!h.audit_chain_valid;
    chainChip.classList.toggle("is-ok", chainOk);
    chainChip.classList.toggle("is-bad", !chainOk);
    chainText.textContent = chainOk ? "Chain verified" : "Chain broken";
  } catch (e) {
    dot.classList.add("is-bad");
    $("#chip-health").classList.add("is-bad");
    text.textContent = "Unreachable";
  }
}

// -------------------------------------------------------------- metrics ----

function kpiCard({ accent, icon, label, value, unit, foot }) {
  return `
    <div class="kpi" data-accent="${accent}">
      <div class="kpi-label">${icon}<span>${esc(label)}</span></div>
      <div class="kpi-value">${value}${unit ? `<span class="unit">${esc(unit)}</span>` : ""}</div>
      ${foot ? `<div class="kpi-foot">${foot}</div>` : ""}
    </div>`;
}

const ICONS = {
  risk: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2 2 20h20L12 2Z"/><path d="M12 9v5m0 3h.01"/></svg>',
  recovered: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"/></svg>',
  rate: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/></svg>',
  bolt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/></svg>',
  brain: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 2a3 3 0 0 0-3 3v.3A3 3 0 0 0 4 8v1a3 3 0 0 0-1 5.6V16a3 3 0 0 0 3 3h1"/><path d="M15 2a3 3 0 0 1 3 3v.3A3 3 0 0 1 20 8v1a3 3 0 0 1 1 5.6V16a3 3 0 0 1-3 3h-1"/><path d="M9 2h6v18a2 2 0 0 1-2 2h-2a2 2 0 0 1-2-2V2Z"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/></svg>',
};

function renderMetrics(m) {
  const grid = $("#kpi-grid");
  grid.innerHTML = [
    kpiCard({
      accent: "blue", icon: ICONS.risk, label: "Revenue at risk",
      value: fmtINR(m.revenue_at_risk_rupees),
      foot: `${m.total_cases ?? 0} cases &middot; full: ${fmtINRFull(m.revenue_at_risk_rupees)}`,
    }),
    kpiCard({
      accent: "green", icon: ICONS.recovered, label: "Recovered value",
      value: fmtINR(m.recovered_value_rupees),
      foot: `${m.recovered_cases ?? 0} cases recovered`,
    }),
    kpiCard({
      accent: "green", icon: ICONS.rate, label: "Recovery rate",
      value: fmtPct(m.recovery_rate_pct),
      foot: "value-weighted, not case-weighted",
    }),
    kpiCard({
      accent: "blue", icon: ICONS.bolt, label: "Actions executed",
      value: (m.actions_executed ?? 0).toLocaleString("en-IN"),
      foot: "dispatched and ran",
    }),
    kpiCard({
      accent: "amber", icon: ICONS.shield, label: "Actions blocked",
      value: (m.actions_blocked ?? 0).toLocaleString("en-IN"),
      foot: "denied, reviewed, or stopped by policy",
    }),
    kpiCard({
      accent: "blue", icon: ICONS.brain, label: "AI confidence",
      value: fmtPct(m.ai_confidence_pct),
      foot: "mean over diagnosed cases",
    }),
    kpiCard({
      accent: "red", icon: ICONS.x, label: "Failure rate",
      value: fmtPct(m.failure_rate_pct),
      foot: "not recovered, any reason",
    }),
  ].join("");

  renderBars("#methods", Object.entries(m.methods || {}).sort((a, b) => b[1].total - a[1].total), (name, v) => ({
    name: name.toUpperCase(),
    val: `${v.recovered}/${v.total} · ${fmtPct(v.recovery_rate_pct, 0)}`,
    pct: v.recovery_rate_pct,
    cls: v.recovery_rate_pct >= 50 ? "is-ok" : v.recovery_rate_pct >= 20 ? "" : "is-warn",
  }));

  const maxErr = Math.max(1, ...(m.errors || []).map((e) => e.total));
  renderBars("#errors", (m.errors || []).map((e) => [e.reason, e]), (name, e) => ({
    name: titleCase(name),
    val: `${e.total}`,
    pct: (e.total / maxErr) * 100,
    cls: "",
  }));

  const states = $("#states");
  const order = ["RECOVERED", "SCHEDULED", "EXECUTING", "DIAGNOSED", "DETECTED", "FAILED_ATTEMPT", "QUARANTINED", "ABANDONED", "HOLDOUT_CLOSED"];
  const entries = Object.entries(m.states || {}).sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
  states.innerHTML = entries.length
    ? entries.map(([s, n]) => `
        <div class="state-row">
          <span class="badge badge-${STATE_BADGE[s] || "mute"}">${titleCase(s)}</span>
          <span class="n">${n}</span>
        </div>`).join("")
    : `<div class="empty">No cases yet</div>`;

  $("#foot-meta").textContent = `${m.total_cases ?? 0} cases · ${Object.keys(m.cohorts || {}).length} arms · updated ${new Date().toLocaleTimeString("en-IN")}`;
}

function renderBars(sel, entries, mapFn) {
  const el = $(sel);
  if (!entries.length) { el.innerHTML = `<div class="empty">No data</div>`; return; }
  el.innerHTML = entries.map(([key, v]) => {
    const { name, val, pct, cls } = mapFn(key, v);
    return `
      <div class="bar-row">
        <span class="bar-name">${esc(name)}</span>
        <span class="bar-val">${esc(val)}</span>
        <div class="bar-track"><div class="bar-fill ${cls}" style="width:${Math.min(100, Math.max(2, pct || 0))}%"></div></div>
      </div>`;
  }).join("");
}

// -------------------------------------------------------------- demos ------

function renderDemoCards() {
  $("#demos").innerHTML = DEMOS.map((d) => `
    <button class="demo-card" data-scenario="${d.key}">
      <div class="t"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${d.icon}</svg>${esc(d.title)}</div>
      <div class="d">${esc(d.desc)}</div>
    </button>`).join("");

  $$(".demo-card").forEach((btn) => btn.addEventListener("click", () => runDemo(btn)));
}

async function runDemo(btn) {
  const scenario = btn.dataset.scenario;
  const label = btn.querySelector(".t").textContent;
  btn.disabled = true;
  try {
    const result = await fetchJSON("/api/demo/trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario }),
    });
    toast(result.title || label, result.message || "Scenario executed and recorded.", "ok");
    await Promise.all([loadMetrics(), loadTransactions()]);
    if (result.case_id) openDrawer(result.case_id);
  } catch (e) {
    toast(`${label} failed`, e.message, "bad");
  } finally {
    btn.disabled = false;
  }
}

// -------------------------------------------------------------- table ------

function rowHTML(t) {
  const conf = t.ai_confidence;
  const confLow = conf !== null && conf !== undefined && conf < 50;
  return `
    <tr data-case="${esc(t.case_id)}">
      <td class="id">${esc(t.case_id)}<span class="sub">${esc(t.order_id)}</span></td>
      <td class="amount">${fmtINRFull(t.amount_rupees)}</td>
      <td>${t.method ? t.method.toUpperCase() : "—"}<span class="sub">${esc(t.instrument_type || "")}</span></td>
      <td>${titleCase(t.error_reason)}</td>
      <td>${t.ai_recoverability && t.ai_recoverability !== "N/A" ? `<span class="badge badge-info">${titleCase(t.ai_recoverability)}</span>` : `<span class="badge badge-mute">Rules only</span>`}</td>
      <td>${conf !== null && conf !== undefined
        ? `<div class="conf-cell"><div class="conf-track"><div class="conf-fill ${confLow ? "is-low" : ""}" style="width:${conf}%"></div></div><span class="conf-num">${conf.toFixed(0)}%</span></div>`
        : `<span class="sub">—</span>`}</td>
      <td>${policyBadge(t.policy_decision)}</td>
      <td><span class="badge ${t.cohort === "HOLDOUT" ? "badge-mute" : "badge-info"}">${t.cohort === "HOLDOUT" ? "Holdout" : "Treated"}</span></td>
      <td><span class="badge badge-${STATE_BADGE[t.state] || "mute"}">${titleCase(t.state)}</span></td>
    </tr>`;
}

function policyBadge(decision) {
  if (decision === "ALLOW") return `<span class="badge badge-ok">Allow</span>`;
  if (decision === "DENY") return `<span class="badge badge-bad">Deny</span>`;
  if (decision === "REVIEW") return `<span class="badge badge-warn">Review</span>`;
  return `<span class="badge badge-mute">—</span>`;
}

function renderRowsSkeleton() {
  $("#rows").innerHTML = Array.from({ length: 8 }).map(() => `
    <tr><td colspan="9"><div class="skel" style="height:16px;width:${60 + Math.random() * 30}%"></div></td></tr>
  `).join("");
}

function renderRows() {
  const tbody = $("#rows");
  if (!state.rows.length) {
    tbody.innerHTML = `<tr><td colspan="9"><div class="empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
      <div>No transactions match these filters</div>
    </div></td></tr>`;
    return;
  }
  tbody.innerHTML = state.rows.map(rowHTML).join("");
  $$("#rows tr[data-case]").forEach((tr) => tr.addEventListener("click", () => openDrawer(tr.dataset.case)));
}

async function loadTransactions() {
  renderRowsSkeleton();
  const params = new URLSearchParams({
    limit: state.limit, offset: state.offset,
    state_filter: state.filters.state, method_filter: state.filters.method, cohort_filter: state.filters.cohort,
  });
  if (state.search) params.set("search", state.search);
  try {
    const data = await fetchJSON(`/api/transactions?${params}`);
    state.rows = data.transactions || [];
    state.total = data.total || 0;
    renderRows();
    const from = state.total ? state.offset + 1 : 0;
    const to = Math.min(state.offset + state.limit, state.total);
    $("#page-info").textContent = `${from}–${to} of ${state.total}`;
    $("#btn-prev").disabled = state.offset === 0;
    $("#btn-next").disabled = to >= state.total;
  } catch (e) {
    $("#rows").innerHTML = `<tr><td colspan="9"><div class="empty">Could not load transactions — ${esc(e.message)}</div></td></tr>`;
  }
}

async function loadMetrics() {
  try {
    renderMetrics(await fetchJSON("/api/metrics"));
  } catch (e) {
    $("#kpi-grid").innerHTML = `<div class="empty">Could not load metrics — ${esc(e.message)}</div>`;
  }
}

// -------------------------------------------------------------- drawer -----

function phase(n, title, bodyHTML) {
  return `
    <div class="phase">
      <div class="phase-head"><span class="phase-n">${n}</span><h4>${esc(title)}</h4></div>
      <div class="phase-body">${bodyHTML}</div>
    </div>`;
}
function kv(pairs) {
  return `<dl class="kv">` + pairs.map(([k, v, mono]) => `<dt>${esc(k)}</dt><dd${mono ? ' class="mono"' : ""}>${v ?? "—"}</dd>`).join("") + `</dl>`;
}

function renderDetail(d) {
  const body = $("#drawer-body");
  $("#drawer-case").textContent = d.case_id;

  const parts = [];

  parts.push(phase(1, "Signal", kv([
    ["Order", esc(d.event.order_id), true],
    ["Customer", esc(d.event.customer_id), true],
    ["Method", (d.event.method || "").toUpperCase()],
    ["Amount", fmtINRFull(d.event.amount_rupees)],
    ["Recurring", d.event.is_recurring ? `Yes${d.event.mandate_id ? " · " + esc(d.event.mandate_id) : ""}` : "No"],
    ["Error", `${esc(d.event.error_code)} — ${esc(d.event.error_reason)}`],
    ["Source / step", `${esc(d.event.error_source)} / ${esc(d.event.error_step)}`],
  ])));

  parts.push(phase(2, "Context", kv([
    ["Cohort", `<span class="badge ${d.context.cohort === "HOLDOUT" ? "badge-mute" : "badge-info"}">${titleCase(d.context.cohort)}</span>`],
    ["Attempt", `#${d.context.attempt_no} (${d.context.prior_failures_count} prior)`],
    ["Triage", `${titleCase(d.context.triage_matched)} → ${titleCase(d.context.triage_recoverability)}${d.context.triage_is_ambiguous ? " (ambiguous → model)" : " (clean, rule-resolved)"}`],
  ])));

  const diag = d.ai_diagnosis;
  parts.push(phase(3, "AI diagnosis", `
    ${kv([
      ["Recoverability", `<span class="badge badge-info">${titleCase(diag.recoverability)}</span>`],
      ["Confidence", diag.confidence_pct !== null ? fmtPct(diag.confidence_pct) : "—"],
      ["Fallback tier", diag.fallback_tier === 0 ? "0 — direct answer" : `${diag.fallback_tier} — degraded`],
    ])}
    <p class="rationale">${esc(diag.rationale)}</p>
  `));

  const ev = d.evidence;
  parts.push(phase(4, "Evidence", `
    ${kv([["Grounded", ev.is_grounded ? "Yes — cites real input fields" : "No evidence cited"]])}
    ${ev.cited_fields?.length ? `<div class="chips" style="margin-top:8px">${ev.cited_fields.map((f) => `<span class="chip">${esc(f)}</span>`).join("")}</div>` : ""}
    ${ev.risks?.length ? `<div style="margin-top:10px"><dt style="font-size:11.5px;color:var(--slate-light);margin-bottom:6px">Risks flagged</dt><div class="chips">${ev.risks.map((r) => `<span class="chip">${esc(r.category)}: ${esc(r.note)}</span>`).join("")}</div></div>` : ""}
    ${ev.missing_information?.length ? `<div style="margin-top:10px"><dt style="font-size:11.5px;color:var(--slate-light);margin-bottom:6px">Missing information</dt><div class="chips">${ev.missing_information.map((m) => `<span class="chip">${esc(m)}</span>`).join("")}</div></div>` : ""}
  `));

  const pa = d.proposed_action;
  parts.push(phase(5, "Proposed action", kv([
    ["Action", titleCase(pa.proposed_action)],
    ["Delay", `${pa.proposed_delay_minutes ?? 0} min`],
    ["P(success)", pa.expected_success_probability_pct !== null ? fmtPct(pa.expected_success_probability_pct) : "—"],
    ["Horizon", `${pa.expected_horizon_minutes ?? 0} min`],
  ])));

  const pr = d.policy_result;
  parts.push(phase(6, "Policy result — zero-LLM gate", `
    ${kv([
      ["Decision", policyBadge(pr.policy_decision)],
      ["Authorized action", titleCase(pr.authorized_action)],
      ["Rules version", `v${pr.policy_version}`],
      ["Execute at", pr.execute_at ? fmtDate(pr.execute_at) : "—"],
    ])}
    ${pr.fired_rules?.length ? `<div class="chips" style="margin-top:9px">${pr.fired_rules.map((r) => `<span class="chip is-rule">${esc(r)}</span>`).join("")}</div>` : ""}
    <p class="rationale" style="margin-top:9px">${esc(pr.reason)}</p>
  `));

  const ex = d.execution;
  parts.push(phase(7, "Execution", kv([
    ["Dispatched", ex.is_dispatched ? "Yes" : "No"],
    ["Idempotency key", ex.idempotency_key ? esc(ex.idempotency_key.slice(0, 20)) + "…" : "—", true],
    ["Mode", ex.execution_mode ? ex.execution_mode.toUpperCase() : "—"],
    ["Executed at", ex.executed_at ? fmtDate(ex.executed_at) : "—"],
    ["Replayed", ex.replayed ? "Yes — idempotent, no re-spend" : "No"],
  ])));

  const oc = d.outcome;
  const outcomeBadge = oc.succeeded === true ? "badge-ok" : oc.succeeded === false ? "badge-bad" : "badge-warn";
  parts.push(phase(8, "Outcome", `
    ${kv([
      ["Final state", `<span class="badge badge-${STATE_BADGE[oc.final_state] || "mute"}">${titleCase(oc.final_state)}</span>`],
      ["Status", `<span class="badge ${outcomeBadge}">${titleCase(oc.outcome_status)}</span>`],
      ["Reason", esc(oc.abandon_reason || oc.error_detail || "—")],
      ["Retryable", oc.retryable === null || oc.retryable === undefined ? "—" : oc.retryable ? "Yes" : "No"],
    ])}
  `));

  parts.push(phase(9, "Audit trail", `
    ${kv([
      ["Chain", d.audit_trail.chain_valid ? `<span class="badge badge-ok">Verified</span>` : `<span class="badge badge-bad">Broken</span>`],
      ["Events", d.audit_trail.total_events],
    ])}
    <div class="timeline" style="margin-top:14px">
      ${d.audit_trail.timeline.map((e) => `
        <div class="tl-item">
          <div class="tl-head">
            <span class="tl-type">${esc(e.event_type)}</span>
            <span class="tl-actor">${esc(e.actor)}</span>
          </div>
          <div class="tl-hash">${fmtDate(e.timestamp)} · ${esc(e.hash?.slice(0, 16))}…</div>
        </div>`).join("")}
    </div>
  `));

  body.innerHTML = parts.join("");
}

async function openDrawer(caseId) {
  const scrim = $("#scrim"), drawer = $("#drawer");
  scrim.classList.add("open");
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  $("#drawer-body").innerHTML = `<div class="loading">Loading trace…</div>`;
  $("#drawer-case").textContent = caseId;
  try {
    renderDetail(await fetchJSON(`/api/transaction/${encodeURIComponent(caseId)}`));
  } catch (e) {
    $("#drawer-body").innerHTML = `<div class="empty">Could not load trace — ${esc(e.message)}</div>`;
  }
}
function closeDrawer() {
  $("#scrim").classList.remove("open");
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
}

// -------------------------------------------------------------- wiring -----

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function init() {
  renderDemoCards();
  loadHealth();
  loadMetrics();
  loadTransactions();

  $("#btn-refresh").addEventListener("click", () => { loadHealth(); loadMetrics(); loadTransactions(); });
  $("#scrim").addEventListener("click", closeDrawer);
  $("#btn-close").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
    if (e.key.toLowerCase() === "r" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      loadHealth(); loadMetrics(); loadTransactions();
    }
  });

  $("#q").addEventListener("input", debounce((e) => {
    state.search = e.target.value.trim();
    state.offset = 0;
    loadTransactions();
  }, 320));

  const filterMap = { "#f-state": "state", "#f-method": "method", "#f-cohort": "cohort" };
  Object.entries(filterMap).forEach(([sel, key]) => {
    $(sel).addEventListener("change", (e) => {
      state.filters[key] = e.target.value;
      state.offset = 0;
      loadTransactions();
    });
  });

  $("#btn-prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadTransactions(); });
  $("#btn-next").addEventListener("click", () => { state.offset += state.limit; loadTransactions(); });

  setInterval(loadHealth, 30000);
}

document.addEventListener("DOMContentLoaded", init);
