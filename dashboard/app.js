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
    key: "successful_recovery",
    title: "Successful Recovery",
    desc: "Transient UPI failure diagnosed, approved by policy (ALLOW), and successfully recovered (₹2,499.00).",
    icon: '<path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/><path d="m9 12 2 2 4-4"/>',
  },
  {
    key: "policy_rejection",
    title: "Policy Veto (Adversarial AI)",
    desc: "A 100% confident AI retry on an exhausted attempt budget is vetoed by the Zero-LLM Policy Gate (Rule: ATTEMPT_CAP).",
    icon: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="M9.5 12.5 11 14l3.5-3.5"/>',
  },
  {
    key: "execution_timeout",
    title: "Gateway Timeout & Quarantine",
    desc: "Netbanking gateway timeout intercepted safely into QUARANTINED state for reconciliation.",
    icon: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
  },
  {
    key: "live_proof",
    title: "Live Razorpay API Proof",
    desc: "Dispatches a real test-mode Payment Link against Razorpay API with idempotency key forwarding.",
    icon: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  },
  {
    key: "duplicate_event",
    title: "Idempotent Replay Guard",
    desc: "Re-deliver the same authorization twice. Returns original record with replayed=true, avoiding double-charging.",
    icon: '<path d="M8 8h10v10H8zM6 6h10v2M6 6v10h2"/>',
  },
  {
    key: "invalid_ai_output",
    title: "Malformed AI Fallback",
    desc: "Corrupted LLM response safely caught by Tier-3 fail-closed fallback to UNKNOWN (ABANDONED).",
    icon: '<path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
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

const REDUCE_MOTION = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ============================================================================
   viz — a small, self-contained chart module.
   Every form/color/interaction choice here follows the dataviz skill loaded
   for this pass: sequential blue for magnitude ranking, categorical (validated,
   fixed order) only for true part-to-whole identity, emphasis (accent vs gray)
   for the treated-vs-holdout comparison, status tokens only for state/policy
   badges. No dependency — hand-rolled so it matches this exact palette.
   ========================================================================= */

const viz = (() => {
  const CAT = ["--viz-cat-1", "--viz-cat-2", "--viz-cat-3", "--viz-cat-4", "--viz-cat-5", "--viz-cat-6", "--viz-cat-7", "--viz-cat-8"];
  const root = getComputedStyle(document.documentElement);
  const cssvar = (name) => root.getPropertyValue(name).trim();

  // ---- count-up: RAF easing, snaps instantly under reduced-motion ----
  function countUp(el, to, { prefix = "", suffix = "", decimals = 0, duration = 900 } = {}) {
    if (!el) return;
    const from = 0;
    if (REDUCE_MOTION || !isFinite(to)) {
      el.textContent = prefix + to.toLocaleString("en-IN", { maximumFractionDigits: decimals, minimumFractionDigits: decimals }) + suffix;
      return;
    }
    const t0 = performance.now();
    const ease = (t) => 1 - Math.pow(1 - t, 3); // cubic ease-out
    function frame(now) {
      const p = Math.min(1, (now - t0) / duration);
      const v = from + (to - from) * ease(p);
      el.textContent = prefix + v.toLocaleString("en-IN", { maximumFractionDigits: decimals, minimumFractionDigits: decimals }) + suffix;
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  // ---- shared tooltip singleton ----
  let tipEl = null;
  function tip() {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "viz-tooltip";
      tipEl.setAttribute("role", "tooltip");
      document.body.appendChild(tipEl);
    }
    return tipEl;
  }
  function showTip(target, rows) {
    const el = tip();
    el.innerHTML = "";
    rows.forEach(({ label, value }) => {
      const line = document.createElement("div");
      const vSpan = document.createElement("span");
      vSpan.className = "vt-value";
      vSpan.textContent = value; // textContent only — labels/values trace to data
      const lSpan = document.createElement("span");
      lSpan.className = "vt-label";
      lSpan.textContent = " " + label;
      line.appendChild(vSpan);
      line.appendChild(lSpan);
      el.appendChild(line);
    });
    const r = target.getBoundingClientRect();
    el.classList.add("is-visible");
    // measure after content is set, then clamp inside the viewport
    const tw = el.offsetWidth, th = el.offsetHeight;
    let left = r.left + r.width / 2 - tw / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));
    let top = r.top - th - 10;
    if (top < 8) top = r.bottom + 10;
    el.style.left = left + "px";
    el.style.top = top + "px";
  }
  function hideTip() {
    if (tipEl) tipEl.classList.remove("is-visible");
  }

  // ---- table-view twin: renders a plain <table> beside every chart ----
  function renderTable(tableEl, headers, rows) {
    if (!tableEl) return;
    const thead = `<thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>`;
    const tbody = `<tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td class="${i > 0 ? "num" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody>`;
    tableEl.innerHTML = thead + tbody;
  }
  function wireToggle(btn) {
    const key = btn.dataset.toggle;
    const mount = document.getElementById(key);
    const table = document.getElementById(key + "-table");
    btn.addEventListener("click", () => {
      const showingTable = btn.getAttribute("aria-pressed") === "true";
      btn.setAttribute("aria-pressed", String(!showingTable));
      mount.classList.toggle("is-hidden", !showingTable);
      table.classList.toggle("is-visible", !showingTable);
    });
  }

  // ---- ranked bar: sequential magnitude, one hue, direct label at tip ----
  function rankedBar(mountEl, tableEl, items, { valueFmt, tooltipRows, headers, tableRows }) {
    if (!items.length) {
      mountEl.innerHTML = `<div class="empty" style="padding:18px 0">No data yet</div>`;
      return;
    }
    const max = Math.max(...items.map((i) => i.value), 1);
    mountEl.innerHTML = `<div class="rbar-list">${items
      .map((it, idx) => {
        const pct = Math.max(4, (it.value / max) * 100);
        return `
        <div class="rbar-row" tabindex="0" data-idx="${idx}" aria-label="${esc(it.name)}">
          <span class="rbar-name">${esc(it.name)}</span>
          <div class="rbar-track">
            <div class="rbar-fill ${pct < 18 ? "is-tiny" : ""}" style="width:0" data-target="${pct}">
              <span class="rbar-tip">${esc(valueFmt(it))}</span>
            </div>
          </div>
        </div>`;
      })
      .join("")}</div>`;

    requestAnimationFrame(() => {
      $$(".rbar-fill", mountEl).forEach((f) => {
        const w = f.dataset.target + "%";
        if (REDUCE_MOTION) f.style.width = w;
        else requestAnimationFrame(() => (f.style.width = w));
      });
    });

    $$(".rbar-row", mountEl).forEach((row) => {
      const it = items[Number(row.dataset.idx)];
      const track = $(".rbar-track", row);
      const enter = () => showTip(track, tooltipRows(it));
      row.addEventListener("pointerenter", enter);
      row.addEventListener("focus", enter);
      row.addEventListener("pointerleave", hideTip);
      row.addEventListener("blur", hideTip);
    });

    renderTable(tableEl, headers, tableRows(items));
  }

  // ---- stacked bar: categorical part-to-whole, validated fixed hue order ----
  function stackedBar(mountEl, legendEl, tableEl, segments, { headers, tableRows }) {
    const total = segments.reduce((s, x) => s + x.value, 0);
    if (!total) {
      mountEl.innerHTML = `<div class="empty" style="padding:18px 0">No cases yet</div>`;
      return;
    }
    const withColor = segments.map((s, i) => ({ ...s, color: `var(${CAT[i % CAT.length]})` }));

    mountEl.innerHTML = `
      <div class="sbar-track">
        ${withColor.map((s, i) => `<div class="sbar-seg" tabindex="0" data-idx="${i}" style="width:0;background:${s.color}" aria-label="${esc(s.name)}"></div>`).join("")}
      </div>
      <div class="sbar-legend">
        ${withColor.map((s) => `<span class="sbar-key"><span class="swatch" style="background:${s.color}"></span>${esc(s.name)} <span class="n">${s.value}</span></span>`).join("")}
      </div>`;

    requestAnimationFrame(() => {
      $$(".sbar-seg", mountEl).forEach((seg, i) => {
        const pct = (withColor[i].value / total) * 100;
        const w = pct + "%";
        if (REDUCE_MOTION) seg.style.width = w;
        else requestAnimationFrame(() => (seg.style.width = w));
      });
    });

    $$(".sbar-seg", mountEl).forEach((seg) => {
      const s = withColor[Number(seg.dataset.idx)];
      const pct = ((s.value / total) * 100).toFixed(1);
      const enter = () => showTip(seg, [{ label: s.name, value: `${s.value} (${pct}%)` }]);
      seg.addEventListener("pointerenter", enter);
      seg.addEventListener("focus", enter);
      seg.addEventListener("pointerleave", hideTip);
      seg.addEventListener("blur", hideTip);
    });

    renderTable(tableEl, headers, tableRows(segments, total));
  }

  // ---- funnel: ordinal ramp, stage-over-stage drop-off ----
  function funnel(mountEl, stages) {
    const max = Math.max(...stages.map((s) => s.value), 1);
    const steps = ["--viz-seq-650", "--viz-seq-450", "--viz-seq-250"];
    mountEl.innerHTML = `<div class="funnel">${stages
      .map((s, i) => {
        const pct = Math.max(6, (s.value / max) * 100);
        const drop = i > 0 ? stages[i - 1].value - s.value : null;
        const dropPct = i > 0 && stages[i - 1].value > 0 ? ((drop / stages[i - 1].value) * 100).toFixed(0) : null;
        return `
        <div class="funnel-row" tabindex="0" data-idx="${i}">
          <span class="funnel-label">${esc(s.name)}</span>
          <div class="funnel-track"><div class="funnel-fill" style="width:0;background:var(${steps[i % steps.length]})" data-target="${pct}"></div></div>
          <span class="funnel-val">${s.value.toLocaleString("en-IN")}</span>
        </div>
        ${drop !== null && drop > 0 ? `<div class="funnel-drop">↓ ${drop.toLocaleString("en-IN")} (${dropPct}%) did not reach this stage</div>` : ""}`;
      })
      .join("")}</div>`;

    requestAnimationFrame(() => {
      $$(".funnel-fill", mountEl).forEach((f) => {
        const w = f.dataset.target + "%";
        if (REDUCE_MOTION) f.style.width = w;
        else requestAnimationFrame(() => (f.style.width = w));
      });
    });

    $$(".funnel-row", mountEl).forEach((row) => {
      const s = stages[Number(row.dataset.idx)];
      const track = $(".funnel-track", row);
      const enter = () => showTip(track, [{ label: s.name, value: s.value.toLocaleString("en-IN") }]);
      row.addEventListener("pointerenter", enter);
      row.addEventListener("focus", enter);
      row.addEventListener("pointerleave", hideTip);
      row.addEventListener("blur", hideTip);
    });
  }

  return { countUp, showTip, hideTip, wireToggle, rankedBar, stackedBar, funnel, cssvar, CAT };
})();

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

let _kpiAnimQueue = [];

function kpiCard({ accent, icon, label, raw, fmt, unit, foot }) {
  const idx = _kpiAnimQueue.length;
  _kpiAnimQueue.push({ raw, fmt });
  return `
    <div class="kpi" data-accent="${accent}">
      <div class="kpi-label">${icon}<span>${esc(label)}</span></div>
      <div class="kpi-value"><span data-countup-idx="${idx}">${esc(fmt(0))}</span>${unit ? `<span class="unit">${esc(unit)}</span>` : ""}</div>
      ${foot ? `<div class="kpi-foot">${foot}</div>` : ""}
    </div>`;
}

/** Animate a KPI value through its own formatter each frame — handles ₹/Cr/% suffixes
    correctly, unlike a generic prefix+suffix count-up. */
function animateKpiValues(container) {
  _kpiAnimQueue.forEach(({ raw, fmt }, idx) => {
    const el = container.querySelector(`[data-countup-idx="${idx}"]`);
    if (!el) return;
    if (REDUCE_MOTION || !isFinite(raw)) { el.textContent = fmt(raw); return; }
    const t0 = performance.now();
    const ease = (t) => 1 - Math.pow(1 - t, 3);
    const duration = 850;
    (function frame(now) {
      const p = Math.min(1, (now - t0) / duration);
      el.textContent = fmt(raw * ease(p));
      if (p < 1) requestAnimationFrame(frame);
    })(t0);
  });
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
  _kpiAnimQueue = [];
  const grid = $("#kpi-grid");
  grid.innerHTML = [
    kpiCard({
      accent: "blue", icon: ICONS.risk, label: "Revenue at risk",
      raw: m.revenue_at_risk_rupees ?? 0, fmt: fmtINR,
      foot: `${m.total_cases ?? 0} cases &middot; full: ${fmtINRFull(m.revenue_at_risk_rupees)}`,
    }),
    kpiCard({
      accent: "green", icon: ICONS.recovered, label: "Recovered value",
      raw: m.recovered_value_rupees ?? 0, fmt: fmtINR,
      foot: `${m.recovered_cases ?? 0} cases recovered`,
    }),
    kpiCard({
      accent: "green", icon: ICONS.rate, label: "Recovery rate",
      raw: m.recovery_rate_pct ?? 0, fmt: (v) => fmtPct(v),
      foot: "value-weighted, not case-weighted",
    }),
    kpiCard({
      accent: "blue", icon: ICONS.bolt, label: "Actions executed",
      raw: m.actions_executed ?? 0, fmt: (v) => Math.round(v).toLocaleString("en-IN"),
      foot: "dispatched and ran",
    }),
    kpiCard({
      accent: "amber", icon: ICONS.shield, label: "Actions blocked",
      raw: m.actions_blocked ?? 0, fmt: (v) => Math.round(v).toLocaleString("en-IN"),
      foot: "denied, reviewed, or stopped by policy",
    }),
    kpiCard({
      accent: "blue", icon: ICONS.brain, label: "AI confidence",
      raw: m.ai_confidence_pct ?? 0, fmt: (v) => fmtPct(v),
      foot: "mean over diagnosed cases",
    }),
    kpiCard({
      accent: "red", icon: ICONS.x, label: "Failure rate",
      raw: m.failure_rate_pct ?? 0, fmt: (v) => fmtPct(v),
      foot: "not recovered, any reason",
    }),
  ].join("");
  animateKpiValues(grid);

  renderHero(m);

  // ---- recovery by method: sequential magnitude, one hue ----
  const methodItems = Object.entries(m.methods || {})
    .sort((a, b) => b[1].recovery_rate_pct - a[1].recovery_rate_pct)
    .map(([name, v]) => ({ name: name.toUpperCase(), value: v.recovery_rate_pct, raw: v }));
  viz.rankedBar($("#methods"), $("#methods-table"), methodItems, {
    valueFmt: (it) => `${fmtPct(it.value, 0)}`,
    tooltipRows: (it) => [
      { label: "recovered / total", value: `${it.raw.recovered} / ${it.raw.total}` },
      { label: "value recovered", value: fmtINR(it.raw.recovered_rupees) },
    ],
    headers: ["Method", "Recovered", "Total", "Rate"],
    tableRows: (items) => items.map((it) => [it.name, it.raw.recovered, it.raw.total, fmtPct(it.value, 1)]),
  });

  // ---- top failure reasons: sequential magnitude ----
  const errorItems = (m.errors || []).map((e) => ({ name: titleCase(e.reason), value: e.total, raw: e }));
  viz.rankedBar($("#errors"), $("#errors-table"), errorItems, {
    valueFmt: (it) => it.value.toLocaleString("en-IN"),
    tooltipRows: (it) => [
      { label: "occurrences", value: it.value.toLocaleString("en-IN") },
      { label: "recovered", value: `${it.raw.recovered} of ${it.value}` },
    ],
    headers: ["Reason", "Occurrences", "Recovered"],
    tableRows: (items) => items.map((it) => [it.name, it.value, it.raw.recovered]),
  });

  // ---- case states: categorical part-to-whole ----
  const stateOrder = ["RECOVERED", "SCHEDULED", "EXECUTING", "DIAGNOSED", "DETECTED", "FAILED_ATTEMPT", "QUARANTINED", "ABANDONED", "HOLDOUT_CLOSED"];
  const stateSegments = Object.entries(m.states || {})
    .sort((a, b) => stateOrder.indexOf(a[0]) - stateOrder.indexOf(b[0]))
    .map(([s, n]) => ({ name: titleCase(s), value: n }));
  viz.stackedBar($("#states"), null, $("#states-table"), stateSegments, {
    headers: ["State", "Count", "Share"],
    tableRows: (segs, total) => segs.map((s) => [s.name, s.value, fmtPct((s.value / total) * 100, 1)]),
  });

  // ---- recovery funnel ----
  viz.funnel($("#funnel"), [
    { name: "At risk", value: m.total_cases ?? 0 },
    { name: "Actioned", value: m.actions_executed ?? 0 },
    { name: "Recovered", value: m.recovered_cases ?? 0 },
  ]);

  $("#foot-meta").textContent = `${m.total_cases ?? 0} cases · ${Object.keys(m.cohorts || {}).length} arms · updated ${new Date().toLocaleTimeString("en-IN")}`;
}

/** Hero: incremental impact, emphasis form (accent vs. de-emphasis gray) — never
    categorical/donut. Holdout is context, not a peer series. */
function renderHero(m) {
  const c = m.cohorts || {};
  const t = c.TREATED, h = c.HOLDOUT;
  const figEl = $("#hero-figure"), capEl = $("#hero-caption"), cmpEl = $("#hero-compare");

  if (!t || !h || !t.cases || !h.cases) {
    figEl.textContent = "—";
    figEl.className = "hero-figure is-flat";
    capEl.textContent = "Needs cases in both the treated and holdout arms to compute — trigger a failure drill below to populate data.";
    cmpEl.innerHTML = "";
    return;
  }

  const tRate = (t.recovered / t.cases) * 100;
  const hRate = (h.recovered / h.cases) * 100;
  const delta = tRate - hRate;
  const sign = delta > 0.05 ? "+" : delta < -0.05 ? "" : "±";
  figEl.className = "hero-figure " + (delta > 0.05 ? "is-up" : delta < -0.05 ? "is-down" : "is-flat");
  figEl.innerHTML = `<span class="sign">${sign}</span><span data-hero-num>0.0</span><span class="unit" style="font-size:0.5em;margin-left:2px">pp</span>`;

  const numEl = figEl.querySelector("[data-hero-num]");
  if (REDUCE_MOTION) {
    numEl.textContent = Math.abs(delta).toFixed(1);
  } else {
    const t0 = performance.now();
    const ease = (x) => 1 - Math.pow(1 - x, 3);
    (function frame(now) {
      const p = Math.min(1, (now - t0) / 900);
      numEl.textContent = (Math.abs(delta) * ease(p)).toFixed(1);
      if (p < 1) requestAnimationFrame(frame);
    })(t0);
  }

  capEl.innerHTML = `Treated recovers at <strong>${fmtPct(tRate, 1)}</strong> vs. <strong>${fmtPct(hRate, 1)}</strong> in the untouched holdout — the gap is what the agent can actually claim credit for, not the gross recovered total.`;

  const maxRate = Math.max(tRate, hRate, 1);
  cmpEl.innerHTML = `
    <div class="hc-row">
      <span class="hc-label"><span class="swatch" style="background:var(--rzp-blue)"></span>Treated</span>
      <div class="hc-track" data-tip="treated"><div class="hc-fill is-accent" style="width:0" data-target="${(tRate / maxRate) * 100}"></div></div>
      <span class="hc-val">${fmtPct(tRate, 1)}</span>
    </div>
    <div class="hc-sub">${t.recovered.toLocaleString("en-IN")} of ${t.cases.toLocaleString("en-IN")} cases &middot; ${fmtINR(t.amount_rupees)} at risk</div>
    <div class="hc-row">
      <span class="hc-label"><span class="swatch" style="background:var(--viz-emphasis-gray)"></span>Holdout</span>
      <div class="hc-track" data-tip="holdout"><div class="hc-fill is-muted" style="width:0" data-target="${(hRate / maxRate) * 100}"></div></div>
      <span class="hc-val">${fmtPct(hRate, 1)}</span>
    </div>
    <div class="hc-sub">${h.recovered.toLocaleString("en-IN")} of ${h.cases.toLocaleString("en-IN")} cases &middot; no intervention &middot; ${fmtINR(h.amount_rupees)} at risk</div>
  `;
  requestAnimationFrame(() => {
    $$(".hc-fill", cmpEl).forEach((f) => {
      const w = f.dataset.target + "%";
      if (REDUCE_MOTION) f.style.width = w;
      else requestAnimationFrame(() => (f.style.width = w));
    });
  });
  $$(".hc-track", cmpEl).forEach((track) => {
    const isT = track.dataset.tip === "treated";
    const arm = isT ? t : h;
    const rate = isT ? tRate : hRate;
    const enter = () => viz.showTip(track, [
      { label: "recovery rate", value: fmtPct(rate, 1) },
      { label: "cases", value: `${arm.recovered} / ${arm.cases}` },
      { label: "value", value: fmtINR(arm.amount_rupees) },
    ]);
    track.addEventListener("pointerenter", enter);
    track.addEventListener("focus", enter);
    track.addEventListener("pointerleave", viz.hideTip);
    track.addEventListener("blur", viz.hideTip);
  });
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
  // hold the previous render dimmed during refetch — no skeleton, no flash
  const dimTargets = [$("#kpi-grid"), $(".hero-panel"), $(".grid-3"), $("#funnel")].filter(Boolean);
  const isRefetch = dimTargets.some((el) => el.children.length > 0);
  if (isRefetch) dimTargets.forEach((el) => el.classList.add("is-refetching"));
  try {
    renderMetrics(await fetchJSON("/api/metrics"));
  } catch (e) {
    $("#kpi-grid").innerHTML = `<div class="empty">Could not load metrics — ${esc(e.message)}</div>`;
  } finally {
    dimTargets.forEach((el) => el.classList.remove("is-refetching"));
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

  $$(".chart-toggle").forEach(viz.wireToggle);

  setInterval(loadHealth, 30000);
}

document.addEventListener("DOMContentLoaded", init);
