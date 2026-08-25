/**
 * Payment Recovery Control Plane — Executive Dashboard Client
 * Handles real-time metric polling, interactive filtering, and audit trace visualization.
 */

document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const elRevenueAtRisk = document.getElementById("val-revenue-at-risk");
  const elRecoveredValue = document.getElementById("val-recovered-value");
  const elRecoveryRate = document.getElementById("val-recovery-rate");
  const elActionsExecuted = document.getElementById("val-actions-executed");
  const elActionsBlocked = document.getElementById("val-actions-blocked");
  const elAiConfidence = document.getElementById("val-ai-confidence");
  const elFailureRate = document.getElementById("val-failure-rate");

  const elTransactionCount = document.getElementById("transaction-count");
  const elTableBody = document.getElementById("table-body");
  const elInputSearch = document.getElementById("input-search");
  const elFilterCohort = document.getElementById("filter-cohort");
  const elFilterMethod = document.getElementById("filter-method");
  const elFilterState = document.getElementById("filter-state");
  const elBtnRefresh = document.getElementById("btn-refresh");

  const elTraceDrawer = document.getElementById("trace-drawer");
  const elDrawerOverlay = document.getElementById("drawer-overlay");
  const elBtnCloseDrawer = document.getElementById("btn-close-drawer");
  const elDrawerCaseId = document.getElementById("drawer-case-id");
  const elDrawerMetaBar = document.getElementById("drawer-meta-bar");
  const elTimelineContainer = document.getElementById("timeline-container");

  // Format INR currency
  function formatINR(amount) {
    if (amount === undefined || amount === null) return "₹0.00";
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      minimumFractionDigits: 2,
    }).format(amount);
  }

  // Format percentage
  function formatPercent(pct) {
    if (pct === undefined || pct === null) return "0.0%";
    return `${Number(pct).toFixed(1)}%`;
  }

  // Fetch & Render Metrics
  async function fetchMetrics() {
    try {
      const res = await fetch("/api/metrics");
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();

      elRevenueAtRisk.textContent = formatINR(data.revenue_at_risk_rupees);
      elRecoveredValue.textContent = formatINR(data.recovered_value_rupees);
      elRecoveryRate.textContent = formatPercent(data.recovery_rate_pct);
      elActionsExecuted.textContent = (data.actions_executed || 0).toLocaleString();
      elActionsBlocked.textContent = (data.actions_blocked || 0).toLocaleString();
      elAiConfidence.textContent = formatPercent(data.ai_confidence_pct);
      elFailureRate.textContent = formatPercent(data.failure_rate_pct);
    } catch (err) {
      console.error("Failed to load metrics:", err);
    }
  }

  // Fetch & Render Transactions
  async function fetchTransactions() {
    const search = elInputSearch.value.trim();
    const cohort = elFilterCohort.value;
    const method = elFilterMethod.value;
    const state = elFilterState.value;

    const params = new URLSearchParams({
      limit: "100",
      search: search || "",
      cohort_filter: cohort,
      method_filter: method,
      state_filter: state,
    });

    try {
      const res = await fetch(`/api/transactions?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();

      elTransactionCount.textContent = `${data.total} transactions`;
      renderTable(data.transactions || []);
    } catch (err) {
      console.error("Failed to load transactions:", err);
      elTableBody.innerHTML = `
        <tr>
          <td colspan="9" class="text-center text-muted" style="padding: 2rem;">
            Failed to load transactions. Check server connection.
          </td>
        </tr>
      `;
    }
  }

  // Render Table Rows
  function renderTable(transactions) {
    if (transactions.length === 0) {
      elTableBody.innerHTML = `
        <tr>
          <td colspan="9" class="text-center text-muted" style="padding: 2.5rem;">
            No transactions match the selected filters.
          </td>
        </tr>
      `;
      return;
    }

    elTableBody.innerHTML = transactions
      .map((tx) => {
        const stateClass = getStateBadgeClass(tx.state);
        const cohortClass = tx.cohort === "TREATED" ? "badge-treated" : "badge-holdout";

        return `
          <tr>
            <td>
              <div class="case-id-group">
                <span class="case-id-text">${escapeHTML(tx.case_id)}</span>
                <span class="order-id-text">${escapeHTML(tx.order_id)}</span>
              </div>
            </td>
            <td>
              <span class="mono-cell" style="text-transform: uppercase;">${escapeHTML(tx.method)}</span>
            </td>
            <td>
              <span class="amount-text">${formatINR(tx.amount_rupees)}</span>
            </td>
            <td>
              <span class="badge ${cohortClass}">${escapeHTML(tx.cohort)}</span>
            </td>
            <td>
              <span class="mono-cell text-muted" style="font-size: 0.8rem;">${escapeHTML(tx.error_reason)}</span>
            </td>
            <td>
              <div>
                <strong style="font-size: 0.8rem;">${escapeHTML(tx.ai_recoverability)}</strong>
                ${tx.ai_confidence !== null ? `<span class="text-muted" style="font-size: 0.75rem;"> (${tx.ai_confidence}%)</span>` : ""}
              </div>
            </td>
            <td>
              <div>
                <span style="font-weight: 600; font-size: 0.8rem; color: ${tx.policy_decision === "ALLOW" ? "var(--accent-emerald)" : tx.policy_decision === "REVIEW" ? "var(--accent-amber)" : "var(--accent-rose)"};">
                  ${escapeHTML(tx.policy_decision)}
                </span>
                ${tx.policy_action ? `<span class="text-muted" style="font-size: 0.75rem;"> (${escapeHTML(tx.policy_action)})</span>` : ""}
              </div>
            </td>
            <td>
              <span class="badge ${stateClass}">${escapeHTML(tx.state)}</span>
            </td>
            <td>
              <button class="btn-trace" data-case-id="${escapeHTML(tx.case_id)}">
                View Trace
              </button>
            </td>
          </tr>
        `;
      })
      .join("");

    // Attach click listeners for Trace button
    elTableBody.querySelectorAll(".btn-trace").forEach((btn) => {
      btn.addEventListener("click", () => {
        const caseId = btn.getAttribute("data-case-id");
        openTraceDrawer(caseId);
      });
    });
  }

  function getStateBadgeClass(state) {
    switch (state) {
      case "RECOVERED":
        return "badge-recovered";
      case "QUARANTINED":
        return "badge-quarantined";
      case "ABANDONED":
        return "badge-abandoned";
      case "HOLDOUT_CLOSED":
        return "badge-holdout-closed";
      case "SCHEDULED":
        return "badge-scheduled";
      case "EXECUTING":
        return "badge-executing";
      default:
        return "badge-scheduled";
    }
  }

  // Tab Switching
  const tabBtnJourney = document.getElementById("tab-btn-journey");
  const tabBtnAudit = document.getElementById("tab-btn-audit");
  const tabContentJourney = document.getElementById("tab-content-journey");
  const tabContentAudit = document.getElementById("tab-content-audit");
  const elPipelineContainer = document.getElementById("pipeline-container");

  tabBtnJourney.addEventListener("click", () => {
    tabBtnJourney.classList.add("active");
    tabBtnAudit.classList.remove("active");
    tabContentJourney.classList.add("active");
    tabContentAudit.classList.remove("active");
  });

  tabBtnAudit.addEventListener("click", () => {
    tabBtnAudit.classList.add("active");
    tabBtnJourney.classList.remove("active");
    tabContentAudit.classList.add("active");
    tabContentJourney.classList.remove("active");
  });

  // Open Trace Drawer & Fetch Event Sequence & 9-Phase Detail
  async function openTraceDrawer(caseId) {
    elDrawerCaseId.textContent = caseId;
    elPipelineContainer.innerHTML = '<div class="text-muted" style="padding: 1rem 0;">Loading 9-phase transaction journey...</div>';
    elTimelineContainer.innerHTML = '<div class="text-muted" style="padding: 1rem 0;">Loading cryptographic audit chain...</div>';
    elTraceDrawer.classList.add("open");
    elTraceDrawer.setAttribute("aria-hidden", "false");

    // Fetch 9-phase detail and timeline in parallel
    try {
      const [detailRes, traceRes] = await Promise.all([
        fetch(`/api/transaction/${encodeURIComponent(caseId)}`),
        fetch(`/api/trace/${encodeURIComponent(caseId)}`),
      ]);

      if (!detailRes.ok) throw new Error(`HTTP error ${detailRes.status}`);
      const detail = await detailRes.json();
      const trace = traceRes.ok ? await traceRes.json() : null;

      // Render Meta Bar
      elDrawerMetaBar.innerHTML = `
        <div class="meta-item">
          <span class="meta-item-label">Order ID</span>
          <span class="meta-item-value">${escapeHTML(detail.event.order_id)}</span>
        </div>
        <div class="meta-item">
          <span class="meta-item-label">Amount</span>
          <span class="meta-item-value">${formatINR(detail.event.amount_rupees)}</span>
        </div>
        <div class="meta-item">
          <span class="meta-item-label">Cohort / State</span>
          <span class="meta-item-value">${escapeHTML(detail.context.cohort)} &bull; ${escapeHTML(detail.outcome.final_state)}</span>
        </div>
      `;

      // Render 9-Phase Journey
      render9PhaseJourney(detail);

      // Render Timeline
      renderAuditTimeline(trace || detail.audit_trail);
    } catch (err) {
      console.error("Failed to load transaction detail:", err);
      elPipelineContainer.innerHTML = '<div class="text-muted" style="color: var(--accent-rose);">Failed to load journey details.</div>';
      elTimelineContainer.innerHTML = '<div class="text-muted" style="color: var(--accent-rose);">Failed to load trace details.</div>';
    }
  }

  // Render the 9-Phase Journey Cards
  function render9PhaseJourney(d) {
    const ev = d.event;
    const ctx = d.context;
    const diag = d.ai_diagnosis;
    const evi = d.evidence;
    const prop = d.proposed_action;
    const pol = d.policy_result;
    const exec = d.execution;
    const out = d.outcome;
    const aud = d.audit_trail;

    elPipelineContainer.innerHTML = `
      <!-- Phase 1: Event -->
      <div class="phase-card">
        <div class="phase-header">
          <div class="phase-title-group">
            <span class="phase-num">1</span>
            <span class="phase-title">Event & Signal Ingested</span>
          </div>
          <span class="badge badge-scheduled mono-cell">${escapeHTML(ev.method)}</span>
        </div>
        <div class="phase-grid">
          <div class="phase-item">
            <span class="phase-item-label">Error Code</span>
            <span class="phase-item-value mono">${escapeHTML(ev.error_code)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Error Step</span>
            <span class="phase-item-value">${escapeHTML(ev.error_step)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Error Reason</span>
            <span class="phase-item-value mono" style="color: var(--accent-rose);">${escapeHTML(ev.error_reason)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Amount</span>
            <span class="phase-item-value amount-text">${formatINR(ev.amount_rupees)}</span>
          </div>
        </div>
        ${ev.error_description ? `<div class="rationale-quote">"${escapeHTML(ev.error_description)}"</div>` : ""}
      </div>

      <!-- Phase 2: Context -->
      <div class="phase-card">
        <div class="phase-header">
          <div class="phase-title-group">
            <span class="phase-num">2</span>
            <span class="phase-title">Operational Context</span>
          </div>
          <span class="badge ${ctx.cohort === "TREATED" ? "badge-treated" : "badge-holdout"}">${escapeHTML(ctx.cohort)}</span>
        </div>
        <div class="phase-grid">
          <div class="phase-item">
            <span class="phase-item-label">Attempt Count</span>
            <span class="phase-item-value">Attempt #${ctx.attempt_no}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Prior Failures</span>
            <span class="phase-item-value">${ctx.prior_failures_count}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Triage Route</span>
            <span class="phase-item-value">${ctx.triage_is_ambiguous ? "Ambiguous (AI Guided)" : `Deterministic (${escapeHTML(ctx.triage_matched)})`}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Recurring Mandate</span>
            <span class="phase-item-value">${ctx.is_recurring ? "Yes" : "No"}</span>
          </div>
        </div>
      </div>

      <!-- Phase 3: AI Diagnosis -->
      <div class="phase-card">
        <div class="phase-header">
          <div class="phase-title-group">
            <span class="phase-num">3</span>
            <span class="phase-title">AI Diagnosis</span>
          </div>
          <span class="badge badge-recovered">${escapeHTML(diag.recoverability)}</span>
        </div>
        <div class="phase-grid">
          <div class="phase-item">
            <span class="phase-item-label">Recoverability</span>
            <span class="phase-item-value">${escapeHTML(diag.recoverability)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Confidence Score</span>
            <span class="phase-item-value">${diag.confidence_pct !== null ? `${diag.confidence_pct}%` : "100.0% (Rules)"}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Fallback Tier</span>
            <span class="phase-item-value">Tier ${diag.fallback_tier}</span>
          </div>
        </div>
        ${diag.confidence_pct !== null ? `
          <div class="confidence-bar-wrap">
            <div class="confidence-bar-fill" style="width: ${Math.min(diag.confidence_pct, 100)}%;"></div>
          </div>
        ` : ""}
        <div class="rationale-quote">${escapeHTML(diag.rationale)}</div>
      </div>

      <!-- Phase 4: Evidence -->
      <div class="phase-card">
        <div class="phase-header">
          <div class="phase-title-group">
            <span class="phase-num">4</span>
            <span class="phase-title">Evidence & Grounding</span>
          </div>
          <span class="badge ${evi.is_grounded ? "badge-recovered" : "badge-holdout-closed"}">
            ${evi.is_grounded ? "Grounded" : "Taxonomy Prior"}
          </span>
        </div>
        <span class="phase-item-label">Cited Input Fields:</span>
        <div class="tags-list">
          ${(evi.cited_fields && evi.cited_fields.length > 0)
            ? evi.cited_fields.map(f => `<span class="evidence-chip">${escapeHTML(f)}</span>`).join("")
            : '<span class="text-muted" style="font-size: 0.8rem;">No explicit field citations (deterministic prior)</span>'}
        </div>
        ${(evi.risks && evi.risks.length > 0) ? `
          <div style="margin-top: 0.65rem;">
            <span class="phase-item-label">Identified Risks:</span>
            <div class="tags-list">
              ${evi.risks.map(r => `<span class="risk-chip">${escapeHTML(r.category || r)}</span>`).join("")}
            </div>
          </div>
        ` : ""}
      </div>

      <!-- Phase 5: Proposed Action -->
      <div class="phase-card">
        <div class="phase-header">
          <div class="phase-title-group">
            <span class="phase-num">5</span>
            <span class="phase-title">Proposed Action</span>
          </div>
          <span class="badge ${prop.proposed_action === "RETRY" ? "badge-recovered" : "badge-abandoned"}">
            ${escapeHTML(prop.proposed_action)}
          </span>
        </div>
        <div class="phase-grid">
          <div class="phase-item">
            <span class="phase-item-label">Action</span>
            <span class="phase-item-value">${escapeHTML(prop.proposed_action)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Proposed Delay</span>
            <span class="phase-item-value">${prop.proposed_delay_minutes} min</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Expected Success P(succ)</span>
            <span class="phase-item-value">${prop.expected_success_probability_pct !== null ? `${prop.expected_success_probability_pct}%` : "N/A"}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Horizon</span>
            <span class="phase-item-value">${prop.expected_horizon_minutes} min</span>
          </div>
        </div>
      </div>

      <!-- Phase 6: Policy Result -->
      <div class="phase-card">
        <div class="phase-header">
          <div class="phase-title-group">
            <span class="phase-num">6</span>
            <span class="phase-title">Zero-LLM Policy Result</span>
          </div>
          <span class="badge ${pol.policy_decision === "ALLOW" ? "badge-recovered" : pol.policy_decision === "REVIEW" ? "badge-quarantined" : "badge-abandoned"}">
            ${escapeHTML(pol.policy_decision)}
          </span>
        </div>
        <div class="phase-grid">
          <div class="phase-item">
            <span class="phase-item-label">Policy Decision</span>
            <span class="phase-item-value">${escapeHTML(pol.policy_decision)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Authorized Action</span>
            <span class="phase-item-value">${escapeHTML(pol.authorized_action)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Rules Version</span>
            <span class="phase-item-value">v${pol.policy_version}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Is Executable</span>
            <span class="phase-item-value">${pol.is_executable ? "Yes (Dispatched)" : "No (Blocked)"}</span>
          </div>
        </div>
        ${(pol.fired_rules && pol.fired_rules.length > 0) ? `
          <div style="margin-top: 0.5rem;">
            <span class="phase-item-label">Fired Safety Rules:</span>
            <div class="tags-list">
              ${pol.fired_rules.map(r => `<span class="rule-chip">${escapeHTML(r)}</span>`).join("")}
            </div>
          </div>
        ` : ""}
        <div class="rationale-quote">Policy Verdict Reason: "${escapeHTML(pol.reason)}"</div>
      </div>

      <!-- Phase 7: Execution -->
      <div class="phase-card">
        <div class="phase-header">
          <div class="phase-title-group">
            <span class="phase-num">7</span>
            <span class="phase-title">Execution Dispatch</span>
          </div>
          <span class="badge ${exec.is_dispatched ? "badge-scheduled" : "badge-holdout-closed"}">
            ${exec.is_dispatched ? "Dispatched" : "Not Executed"}
          </span>
        </div>
        <div class="phase-grid">
          <div class="phase-item">
            <span class="phase-item-label">Idempotency Key</span>
            <span class="phase-item-value mono" style="font-size: 0.75rem;">${exec.idempotency_key ? escapeHTML(exec.idempotency_key.substring(0, 16)) + "…" : "N/A"}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Execution Mode</span>
            <span class="phase-item-value uppercase">${escapeHTML(exec.execution_mode)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Replayed</span>
            <span class="phase-item-value">${exec.replayed ? "Yes (Idempotent)" : "No"}</span>
          </div>
        </div>
      </div>

      <!-- Phase 8: Outcome -->
      <div class="phase-card">
        <div class="phase-header">
          <div class="phase-title-group">
            <span class="phase-num">8</span>
            <span class="phase-title">Final Case Outcome</span>
          </div>
          <span class="badge ${getStateBadgeClass(out.final_state)}">
            ${escapeHTML(out.final_state)}
          </span>
        </div>
        <div class="phase-grid">
          <div class="phase-item">
            <span class="phase-item-label">Final State</span>
            <span class="phase-item-value">${escapeHTML(out.final_state)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Outcome Status</span>
            <span class="phase-item-value">${escapeHTML(out.outcome_status)}</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">Succeeded</span>
            <span class="phase-item-value">${out.succeeded === true ? "True (Recovered)" : out.succeeded === false ? "False (Failed)" : "None"}</span>
          </div>
        </div>
        ${out.abandon_reason ? `<div class="rationale-quote">Abandon Reason: "${escapeHTML(out.abandon_reason)}"</div>` : ""}
      </div>

      <!-- Phase 9: Audit Trail Summary -->
      <div class="phase-card">
        <div class="phase-header">
          <div class="phase-title-group">
            <span class="phase-num">9</span>
            <span class="phase-title">Cryptographic Audit Record</span>
          </div>
          <span class="badge ${aud.chain_valid ? "badge-recovered" : "badge-abandoned"}">
            ${aud.chain_valid ? "🛡️ Chain Verified" : "⚠️ Integrity Failure"}
          </span>
        </div>
        <div class="phase-grid">
          <div class="phase-item">
            <span class="phase-item-label">Total Audit Events</span>
            <span class="phase-item-value">${aud.total_events} recorded</span>
          </div>
          <div class="phase-item">
            <span class="phase-item-label">SHA-256 Ledger Status</span>
            <span class="phase-item-value" style="color: var(--accent-emerald);">Immutable Valid</span>
          </div>
        </div>
      </div>
    `;
  }

  // Render the Audit Trail Timeline
  function renderAuditTimeline(data) {
    const timeline = data.timeline || data.events || [];
    if (timeline.length === 0) {
      elTimelineContainer.innerHTML = '<div class="text-muted">No audit events recorded for this case.</div>';
      return;
    }

    elTimelineContainer.innerHTML = timeline
      .map((evt) => {
        let nodeClass = "";
        if (evt.event_type.includes("RESULT") || evt.event_type === "RECONCILIATION_RESOLVED" || evt.event_type === "DECISION_RECORDED") {
          nodeClass = "node-success";
        } else if (evt.event_type.includes("DENY") || evt.event_type === "ACTION_REFUSED") {
          nodeClass = "node-deny";
        } else if (evt.event_type.includes("UNCERTAIN") || evt.event_type.includes("REVIEW")) {
          nodeClass = "node-review";
        }

        const shortHash = evt.hash ? `${evt.hash.substring(0, 10)}…` : "N/A";
        const shortPrev = evt.prev_hash ? `${evt.prev_hash.substring(0, 8)}…` : "GENESIS";

        return `
          <div class="timeline-step">
            <div class="timeline-node ${nodeClass}"></div>
            <div class="timeline-card">
              <div class="timeline-card-header">
                <span class="event-type-badge">#${evt.seq} ${escapeHTML(evt.event_type)}</span>
                <span class="event-actor">${escapeHTML(evt.actor)}</span>
              </div>
              <div class="timeline-payload">${escapeHTML(JSON.stringify(evt.payload, null, 2))}</div>
              <div class="hash-info-row">
                <span>prev: ${shortPrev}</span>
                <span class="hash-badge">hash: ${shortHash}</span>
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function closeTraceDrawer() {
    elTraceDrawer.classList.remove("open");
    elTraceDrawer.setAttribute("aria-hidden", "true");
  }

  function escapeHTML(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Event Listeners
  elBtnCloseDrawer.addEventListener("click", closeTraceDrawer);
  elDrawerOverlay.addEventListener("click", closeTraceDrawer);

  elBtnRefresh.addEventListener("click", () => {
    fetchMetrics();
    fetchTransactions();
  });

  // Debounced Search
  let searchTimeout;
  elInputSearch.addEventListener("input", () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(fetchTransactions, 300);
  });

  // Developer Demo Controls
  const demoButtons = document.querySelectorAll(".btn-demo");
  demoButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const scenario = btn.getAttribute("data-scenario");
      if (!scenario) return;

      btn.classList.add("loading");
      const origContent = btn.innerHTML;
      btn.innerHTML = `<span style="font-size: 0.85rem;">⏳ Triggering ${escapeHTML(scenario)}...</span>`;

      try {
        const res = await fetch("/api/demo/trigger", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scenario }),
        });

        if (!res.ok) throw new Error(`Demo trigger error ${res.status}`);
        const data = await res.json();

        // Refresh metrics and transaction ledger
        await Promise.all([fetchMetrics(), fetchTransactions()]);

        // Auto-open 9-Phase Transaction Detail Drawer for the generated case
        if (data.case_id) {
          openTraceDrawer(data.case_id);
        }
      } catch (err) {
        console.error("Demo scenario trigger failed:", err);
        alert(`Failed to trigger scenario: ${err.message}`);
      } finally {
        btn.classList.remove("loading");
        btn.innerHTML = origContent;
      }
    });
  });

  // Initial Load
  fetchMetrics();
  fetchTransactions();
});

