"use strict";

const icons = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  sliders:
    '<path d="M4 7h8m4 0h4M4 17h3m4 0h9"/><circle cx="14" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  nodes:
    '<circle cx="5" cy="6" r="2.5"/><circle cx="19" cy="6" r="2.5"/><circle cx="12" cy="19" r="2.5"/><path d="m6.5 8 4 8.5m7-8.5-4 8.5M8 6h8"/>',
  external:
    '<path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
  flask:
    '<path d="M9 3h6M10 3v7L4 20a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1l-6-10V3M8 14h8"/>',
  shield:
    '<path d="m12 3 8 3v5c0 5-8 10-8 10S4 16 4 11V6l8-3Z"/><path d="m8 11 3 3 5-5"/>',
  alert: '<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3v.1"/>',
  flag: '<path d="M5 21V4m0 0c5-4 9 4 14 0v10c-5 4-9-4-14 0"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  search: '<circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  chart: '<path d="M4 3v17h17M8 16v-5m5 5V8m5 8V4"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
};
function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.info}</svg>`;
}
document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icon(el.dataset.icon);
});

const state = {
  health: null,
  cases: [],
  rules: null,
  selected: "txn_spike",
  view: "workspace",
  filter: "all",
  tab: "assessment",
  reports: new Map(),
  histories: new Map(),
  historyLoading: new Set(),
  historyErrors: new Map(),
  busy: null,
  startedAt: 0,
};
const app = document.getElementById("app");
const money = (cents) =>
  new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" }).format(
    cents / 100,
  );
const date = (value) =>
  new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(value)) + " UTC";
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const risk = (level) =>
  ["low", "medium", "high"].includes(level) ? level : "low";
const badge = (level, suffix = "risk") =>
  `<span class="badge ${risk(level)}">${escape(level)} ${suffix}</span>`;
const selectedCase = () =>
  state.cases.find((row) => row.transaction.transaction_id === state.selected);
const reportFor = () => state.reports.get(state.selected);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { Accept: "application/json" },
  });
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(
      "The service returned an unreadable response. Please check the server and retry.",
    );
  }
  if (!response.ok) {
    const details =
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status}).`;
    const error = new Error(details);
    error.status = response.status;
    throw error;
  }
  return body;
}

function notice(message = "", isError = false) {
  const element = document.getElementById("notice");
  element.hidden = !message;
  element.className = `notice ${isError ? "error" : ""}`;
  element.innerHTML = `<span>${escape(message)}</span><button class="text-button" data-action="dismiss" aria-label="Dismiss notification">Dismiss</button>`;
}
function announce(message) {
  document.getElementById("announcement").textContent = message;
}
function modeDescription() {
  return state.health.mode === "demo"
    ? "Demo mode · Deterministic explanation, real MCP calls. No LLM is called."
    : `Live LLM · ${state.health.model} via Groq. Each run uses your API quota.`;
}

function heading(eyebrow, title, subtitle) {
  return `<section class="page-heading"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${subtitle}</p></div><span class="heading-mark">${icon("shield")}</span></section>`;
}
function stats() {
  const items = [
    ["Demo cases", state.cases.length, "grid", ""],
    [
      "Flagged for review",
      state.cases.filter((c) => c.detection.flagged).length,
      "flag",
      "medium",
    ],
    [
      "High screening risk",
      state.cases.filter((c) => c.detection.risk_level === "high").length,
      "alert",
      "high",
    ],
    ["Investigated this session", state.reports.size, "check", "low"],
  ];
  return `<div class="stats">${items.map(([label, count, symbol, tone]) => `<div class="stat"><div><div class="stat-label">${label}</div><div class="stat-value">${count.toString().padStart(2, "0")}</div></div><span class="stat-icon ${tone}">${icon(symbol)}</span></div>`).join("")}</div>`;
}
function queue() {
  const cases = state.cases.filter(
    (row) => state.filter !== "flagged" || row.detection.flagged,
  );
  return `<div><section class="panel queue" aria-label="Demo case queue">
    <div class="panel-head"><h2>Case queue</h2><span class="count-tag">${state.cases.length} demo cases</span></div>
    <p class="queue-subtitle">Four scenarios. Different signals.</p>
    <div class="filters" aria-label="Filter cases">
      <button class="filter ${state.filter === "all" ? "active" : ""}" data-filter="all" aria-pressed="${state.filter === "all"}">All cases</button>
      <button class="filter ${state.filter === "flagged" ? "active" : ""}" data-filter="flagged" aria-pressed="${state.filter === "flagged"}">Flagged only</button>
    </div><div class="case-list">${cases
      .map((row) => {
        const tx = row.transaction;
        return `<button class="case-card ${tx.transaction_id === state.selected ? "active" : ""}" data-case="${escape(tx.transaction_id)}" aria-pressed="${tx.transaction_id === state.selected}">
        <div class="case-top"><span class="mono">${escape(tx.transaction_id)}</span>${badge(row.detection.risk_level, "")}</div>
        <div class="case-title">${escape(tx.merchant)}</div><div class="case-story">${escape(row.demo_label)}</div>
        <div class="case-bottom"><span class="case-amount">${money(tx.amount_cents)}</span>${state.reports.has(tx.transaction_id) ? `<span class="case-complete">${icon("check")} Reviewed</span>` : `<span class="case-chevron">${icon("chevron")}</span>`}</div>
      </button>`;
      })
      .join("")}</div>
    <div class="queue-note">${icon("info")}<span>All cases use fictional data. Screening scores are rule weights, not fraud probabilities.</span></div>
  </section><div class="queue-guide"><div class="eyebrow">DEMO TIP</div><p>A large payment isn’t always unusual. Try the business case to see why account history matters.</p><button data-case="txn_business">Explore the business payment →</button></div></div>`;
}
function historyChart(row) {
  const tx = row.transaction;
  const history = state.histories.get(tx.account_id);
  if (!history) {
    const error = state.historyErrors.get(tx.account_id);
    return `<div class="history-area"><div class="history-error">${error ? `${escape(error)} <button class="text-button" data-action="retry-history">Retry history</button>` : "Loading account history…"}</div></div>`;
  }
  const prior = history.transactions.filter(
    (t) =>
      t.transaction_id !== tx.transaction_id &&
      new Date(t.timestamp) < new Date(tx.timestamp),
  );
  const plotted = [...prior.slice(-9), tx];
  const max = Math.max(...plotted.map((t) => t.amount_cents));
  return `<div class="history-area"><div class="history-heading"><strong>Spending in context</strong><span>Prior mean: ${row.detection.baseline_average_cents === null ? "Not available" : money(row.detection.baseline_average_cents)}</span></div>
    <div class="history-chart" role="img" aria-label="Last ${plotted.length - 1} prior payments and selected payment; the largest is ${escape(money(max))}">${plotted.map((t) => `<div class="bar-group" title="${escape(`${t.transaction_id}: ${money(t.amount_cents)} · ${date(t.timestamp)}`)}"><div class="bar ${t.transaction_id === tx.transaction_id ? `target ${risk(row.detection.risk_level)}` : ""}" style="height:${Math.max(2, (t.amount_cents / max) * 100).toFixed(2)}%"></div></div>`).join("")}</div>
    <div class="history-legend"><span class="legend-key">Prior payments</span><span class="legend-key target-key ${risk(row.detection.risk_level)}">Selected payment →</span></div>
    <p class="history-caption">${prior.length} prior payments · ${escape(history.account.name.replace(" (fictional)", ""))} · ${escape(history.account.account_type)} account</p>
  </div>`;
}
function transactionPanel(row) {
  const tx = row.transaction,
    detection = row.detection;
  return `<section class="panel" aria-label="Selected transaction">
    <div class="transaction-head"><div><div class="eyebrow">TRANSACTION OVERVIEW</div><h2>${escape(tx.merchant)}</h2><span class="mono">${escape(tx.transaction_id)} / ${escape(tx.account_id)}</span></div><div class="transaction-amount"><strong>${money(tx.amount_cents)}</strong><small>${escape(tx.currency)} · ${escape(tx.channel.replaceAll("_", " "))}</small></div></div>
    <div class="facts"><div class="fact"><span class="fact-label">Transaction date</span><span class="fact-value">${escape(date(tx.timestamp))}</span></div><div class="fact"><span class="fact-label">Payment country</span><span class="fact-value">${escape(new Intl.DisplayNames(["en"], { type: "region" }).of(tx.country))} <span class="muted">(${escape(tx.country)})</span></span></div><div class="fact"><span class="fact-label">Recent activity</span><span class="fact-value">${detection.recent_transaction_count} payments / ${state.rules.velocity_window_minutes} min</span></div></div>
    <div class="screening"><div class="score-block"><div class="score-heading">Rule score</div><div class="score-number ${risk(detection.risk_level)}">${detection.risk_score}<span>/100</span></div>${badge(detection.risk_level)}<div class="score-scale"><i class="${risk(detection.risk_level)}" style="width:${detection.risk_score}%"></i></div></div><div class="screening-signals"><h3>${detection.matched_rules.length ? `${detection.matched_rules.length} detection rules triggered` : "No detection rules triggered"}</h3><div class="signal-chips">${detection.matched_rules.map((rule) => `<span class="signal-chip" title="${escape(rule.explanation)}">${escape(rule.title)} <strong>+${rule.points}</strong></span>`).join("")}</div><p>${detection.flagged ? "Flagged for review. Gather the account context to understand these signals." : "No screening threshold was reached. You can still investigate this payment."}</p></div></div>
    ${historyChart(row)}
  </section>`;
}
function assessment(report) {
  const result = report.assessment;
  const mismatch = result.risk_level !== report.detection.risk_level;
  return `<div class="report-body" id="report-panel" role="tabpanel" aria-labelledby="tab-assessment">
    <div class="verdict-heading"><h3>Contextual assessment</h3>${badge(result.risk_level)}</div>
    <p class="report-summary">${escape(result.summary)}</p>
    ${mismatch ? `<p class="history-caption">The contextual assessment differs from the ${escape(report.detection.risk_level)} rule-based rating. Both are retained for review.</p>` : ""}
    <div class="report-section-title">SUPPORTING EVIDENCE</div><div class="evidence-list">${result.evidence.map((item) => `<div class="evidence-item">${escape(item.observation)}<div class="evidence-ids">${item.transaction_ids.map((id) => `<code>${escape(id)}</code>`).join("")}</div></div>`).join("")}</div>
    <div class="report-section-title">RECOMMENDED NEXT STEPS</div><ul class="actions-list">${result.recommended_actions.map((action) => `<li>${icon("arrow")}<span>${escape(action)}</span></li>`).join("")}</ul>
    <div class="limitations"><strong>Scope & limitations</strong>${result.limitations.map((line) => `<p>${escape(line)}</p>`).join("")}<p>Recommendations only. No payment or account actions have been taken.</p></div>
  </div>`;
}
function tracePanel(report) {
  return `<div class="report-body" id="report-panel" role="tabpanel" aria-labelledby="tab-trace"><p class="trace-intro">Actual completed MCP calls, in execution order. Expand a call to inspect the inputs and returned evidence.</p>${report.tool_trace.map((trace) => `<details class="trace-entry"><summary><span class="trace-index">${trace.sequence}</span><code>${escape(trace.tool)}</code><span class="trace-time">${trace.duration_ms.toFixed(0)} ms</span></summary><div class="trace-content"><p>ARGUMENTS</p><pre class="json-block">${escape(JSON.stringify(trace.arguments, null, 2))}</pre><p>RETURNED EVIDENCE</p><pre class="json-block">${escape(JSON.stringify(trace.result, null, 2))}</pre></div></details>`).join("")}</div>`;
}
function jsonPanel(report) {
  return `<div class="report-body" id="report-panel" role="tabpanel" aria-labelledby="tab-json"><div class="download-row"><button class="secondary-button" data-action="download">${icon("download")} Download JSON</button></div><pre class="json-block">${escape(JSON.stringify(report, null, 2))}</pre></div>`;
}
function investigationPanel() {
  const report = reportFor(),
    busyHere = state.busy === state.selected;
  const noKey = state.health.mode === "groq" && !state.health.live_configured;
  return `<section class="panel" aria-label="Investigation" aria-busy="${busyHere}">
    <div class="investigation-top"><div class="investigation-title">${icon("nodes")}<div><h2>Evidence-led investigation</h2><small>${report ? `${report.mode === "demo" ? "Demo investigator" : "Groq investigator"} · ${(report.duration_ms / 1000).toFixed(1)}s · ${report.tool_trace.length} tool calls` : "From signals to an explained assessment"}</small></div></div><button class="primary-button" data-action="investigate" ${state.busy || noKey ? "disabled" : ""}>${icon(busyHere ? "clock" : "search")}${busyHere ? "Investigating…" : report ? "Run again" : "Investigate case"}</button></div>
    ${busyHere ? `<div class="busy-report"><span class="spinner"></span><h3>Following the evidence</h3><p>Retrieving MCP evidence and preparing an assessment. The completed trace will appear when the request finishes.</p><span class="busy-elapsed" id="elapsed">${Math.floor((Date.now() - state.startedAt) / 1000)}s elapsed</span></div>` : report ? `<div class="tabs" role="tablist" aria-label="Investigation result"><button id="tab-assessment" class="tab ${state.tab === "assessment" ? "active" : ""}" data-tab="assessment" role="tab" aria-controls="report-panel" aria-selected="${state.tab === "assessment"}" tabindex="${state.tab === "assessment" ? 0 : -1}">Assessment</button><button id="tab-trace" class="tab ${state.tab === "trace" ? "active" : ""}" data-tab="trace" role="tab" aria-controls="report-panel" aria-selected="${state.tab === "trace"}" tabindex="${state.tab === "trace" ? 0 : -1}">MCP trace <span class="tab-count">${report.tool_trace.length}</span></button><button id="tab-json" class="tab ${state.tab === "json" ? "active" : ""}" data-tab="json" role="tab" aria-controls="report-panel" aria-selected="${state.tab === "json"}" tabindex="${state.tab === "json" ? 0 : -1}">JSON</button></div>${state.tab === "trace" ? tracePanel(report) : state.tab === "json" ? jsonPanel(report) : assessment(report)}<div class="report-footer"><span>Saved report · <code>${escape(report.investigation_id)}</code></span><span>${escape(date(report.generated_at))}</span></div>` : `<div class="empty-report"><div class="empty-icon">${icon("search")}</div><h3>The signals are just the beginning.</h3><p>Investigate this case to retrieve the account history, examine the rules, and build an explained risk assessment.</p><div class="steps-mini"><span>Transaction</span>${icon("arrow")}<span>Account history</span>${icon("arrow")}<span>Assessment</span></div></div>`}
    <div class="mode-note">${icon("info")}<span>${noKey ? "Live mode needs a Groq key. Set GROQ_API_KEY in the server’s .env file and restart, or set INVESTIGATION_MODE=demo." : escape(report && !busyHere ? (report.mode === "demo" ? "This saved report is a deterministic demo assessment. No LLM was called." : `This saved report was generated by ${report.model} via Groq.`) : modeDescription())}</span></div>
  </section>`;
}
function workspace() {
  return `${heading("INVESTIGATION WORKSPACE", "Follow the evidence.", "Review the signals. Understand the context. Explain the risk.")}${stats()}<div class="workspace-grid">${queue()}<div class="detail-column">${transactionPanel(selectedCase())}${investigationPanel()}</div></div>`;
}
function rulesView() {
  const r = state.rules;
  const rules = [
    [
      "Large amount",
      "flag",
      r.high_amount_points,
      money(r.high_amount_cents),
      "amount threshold",
      "Flags payments strictly above the fixed amount threshold, regardless of account type.",
    ],
    [
      "Unusual spending",
      "chart",
      r.unusual_amount_points,
      `${r.unusual_amount_multiplier}×`,
      "prior average",
      `Compares the payment with its account’s earlier average. Requires at least ${r.minimum_baseline_transactions} prior payments; the selected payment is excluded.`,
    ],
    [
      "Rapid activity",
      "clock",
      r.velocity_points,
      `${r.velocity_count} payments`,
      `within ${r.velocity_window_minutes} minutes`,
      "Counts payments in the inclusive window ending at the selected transaction, including the selected payment once.",
    ],
    [
      "New foreign country",
      "globe",
      r.new_country_points,
      "New location",
      "outside home country",
      "Flags a country that differs from the account’s home country and is absent from its earlier payment history.",
    ],
  ];
  return `${heading("EXPLAINABLE SCREENING", "Simple rules. Visible signals.", `Four deterministic checks · Rule version ${escape(r.version)} · EUR payments`)}<div class="rule-grid">${rules.map(([title, symbol, points, threshold, unit, explanation]) => `<section class="panel rule-card"><div class="rule-card-top"><span class="rule-icon">${icon(symbol)}</span><span class="rule-points">+${points} points</span></div><h2>${title}</h2><p>${explanation}</p><div class="rule-threshold">${threshold} <small>${unit}</small></div></section>`).join("")}</div><section class="panel score-guide"><h2>How the screening score works</h2><p>Matched rule weights are added and capped at 100. Medium and high scores are flagged for review. This is a heuristic screening score, not a calibrated fraud probability.</p><div class="risk-bands"><div class="risk-band">Low risk<strong>0–${r.medium_risk_threshold - 1}</strong></div><div class="risk-band medium">Medium risk<strong>${r.medium_risk_threshold}–${r.high_risk_threshold - 1}</strong></div><div class="risk-band high">High risk<strong>${r.high_risk_threshold}–100</strong></div></div><p>All time windows are anchored to the selected payment. Future activity never influences its historical screening score.</p></section>`;
}
function workflowView() {
  const steps = [
    [
      "01 / SCREEN",
      "Spot the signals",
      "The rule engine checks amount, prior spending, transaction frequency, and country. Each matching rule adds a visible weight.",
    ],
    [
      "02 / RETRIEVE",
      "Gather real evidence",
      "The investigator calls three MCP tools for transaction details, account history, and the configured rules. Every completed call is recorded.",
    ],
    [
      "03 / ASSESS",
      "Put risk in context",
      "In live mode, Groq selects the tools and writes a structured assessment. Demo mode follows the same MCP path with deterministic explanations.",
    ],
    [
      "04 / REVIEW",
      "Make it explainable",
      "Review the assessment, cited payment IDs, recommendations, and tool trace. Completed reports are saved in SQLite and can be exported as JSON.",
    ],
  ];
  return `${heading("UNDER THE HOOD", "A traceable path to an assessment.", "A small, inspectable system built for a clear demonstration.")}<div class="panel workflow-intro">A suspicious payment is a signal to investigate, not proof of fraud. Trace keeps the deterministic screening score separate from the investigator’s contextual assessment, so you can see exactly what triggered attention and what the account history adds.</div><div class="workflow-steps">${steps.map(([step, title, description]) => `<section class="panel workflow-step"><div class="step-number">${step}</div><h2>${title}</h2><p>${description}</p></section>`).join("")}</div><section class="panel workflow-note">${icon("info")}<div><h2>Know which mode you’re demonstrating</h2><p>${escape(modeDescription())} To change mode, update INVESTIGATION_MODE in the server’s .env file and restart the service. API keys stay on the server.</p><p>All records are fictional. The service suggests next steps; it never blocks a payment or modifies an account.</p></div></section>`;
}
function render() {
  if (!state.health) return;
  const focused = document.activeElement;
  const focusKey = focused?.dataset
    ? ["case", "filter", "tab", "view", "action"].find(
        (key) => focused.dataset[key],
      )
    : null;
  const focusValue = focusKey ? focused.dataset[focusKey] : null;
  app.innerHTML =
    state.view === "rules"
      ? rulesView()
      : state.view === "workflow"
        ? workflowView()
        : workspace();
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.view);
    if (button.dataset.view === state.view)
      button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  document.getElementById("breadcrumb-page").textContent = {
    workspace: "Investigations",
    rules: "Detection rules",
    workflow: "How it works",
  }[state.view];
  if (focusKey && !document.contains(focused))
    document
      .querySelector(`[data-${focusKey}="${CSS.escape(focusValue)}"]`)
      ?.focus({ preventScroll: true });
}
function updateURL() {
  const url = new URL(location.href);
  url.searchParams.set("transaction", state.selected);
  const report = reportFor();
  if (report) url.searchParams.set("investigation", report.investigation_id);
  else url.searchParams.delete("investigation");
  window.history.replaceState(null, "", url);
}
async function loadHistory() {
  const accountId = selectedCase().transaction.account_id;
  if (state.histories.has(accountId) || state.historyLoading.has(accountId))
    return;
  state.historyLoading.add(accountId);
  state.historyErrors.delete(accountId);
  try {
    state.histories.set(
      accountId,
      await api(`/accounts/${encodeURIComponent(accountId)}/history`),
    );
  } catch {
    state.historyErrors.set(accountId, "Account history could not be loaded.");
  } finally {
    state.historyLoading.delete(accountId);
    if (selectedCase().transaction.account_id === accountId) render();
  }
}
function selectCase(id) {
  if (!state.cases.some((row) => row.transaction.transaction_id === id)) return;
  state.selected = id;
  state.view = "workspace";
  state.tab = "assessment";
  if (state.filter === "flagged" && !selectedCase().detection.flagged)
    state.filter = "all";
  updateURL();
  render();
  loadHistory();
}
async function runInvestigation() {
  if (state.busy) return;
  const id = state.selected;
  state.busy = id;
  state.startedAt = Date.now();
  notice();
  announce(`Investigating ${id}.`);
  render();
  const timer = window.setInterval(() => {
    const el = document.getElementById("elapsed");
    if (el)
      el.textContent = `${Math.floor((Date.now() - state.startedAt) / 1000)}s elapsed`;
  }, 1000);
  try {
    const report = await api(`/investigate/${encodeURIComponent(id)}`, {
      method: "POST",
    });
    state.reports.set(id, report);
    if (state.selected === id) {
      state.tab = "assessment";
      updateURL();
    } else
      notice(
        `Investigation complete for ${id}. Select that case to view the report.`,
      );
    announce(
      `Investigation complete. ${report.assessment.risk_level} contextual risk.`,
    );
  } catch (error) {
    const hint =
      error.status === 429
        ? " Groq’s free-plan quota may need time to reset. Try one case at a time."
        : error.status === 503
          ? " Configure the key on the server, or restart in demo mode."
          : " You can retry the investigation.";
    notice(`${error.message}${hint}`, true);
    announce("Investigation failed. See the notification for details.");
  } finally {
    window.clearInterval(timer);
    state.busy = null;
    render();
  }
}
function downloadReport() {
  const report = reportFor();
  if (!report) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `${report.transaction_id}-${report.investigation_id}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function initialize() {
  notice();
  app.innerHTML =
    '<div class="initial-loading"><span class="spinner"></span><h1>Opening your workspace</h1><p>Loading demo cases and detection rules…</p></div>';
  try {
    const [health, cases, rules] = await Promise.all([
      api("/health"),
      api("/demo/cases"),
      api("/fraud-rules"),
    ]);
    if (!cases.length)
      throw new Error(
        "No demo cases were returned. Check that the database was seeded.",
      );
    state.health = health;
    state.cases = cases;
    state.rules = rules;
    document.getElementById("connection-dot").className =
      "status-dot connected";
    document.getElementById("connection-label").textContent =
      "Service connected";
    document.getElementById("mode-pill").textContent =
      health.mode === "demo" ? "DEMO MODE · NO LLM" : "LIVE LLM · GROQ";
    document.getElementById("nav-count").textContent = cases.length;
    const params = new URLSearchParams(location.search);
    const requested = params.get("transaction") || "txn_spike";
    state.selected = cases.some(
      (row) => row.transaction.transaction_id === requested,
    )
      ? requested
      : cases[0].transaction.transaction_id;
    const savedId = params.get("investigation");
    if (savedId) {
      try {
        const report = await api(
          `/investigations/${encodeURIComponent(savedId)}`,
        );
        if (
          !cases.some(
            (row) => row.transaction.transaction_id === report.transaction_id,
          )
        )
          throw new Error("This report is outside the demo case queue.");
        state.reports.set(report.transaction_id, report);
        state.selected = report.transaction_id;
      } catch (error) {
        notice(`Could not restore the saved report. ${error.message}`, true);
      }
    }
    updateURL();
    render();
    loadHistory();
  } catch (error) {
    state.health = null;
    document.getElementById("connection-dot").className = "status-dot offline";
    document.getElementById("connection-label").textContent =
      "Service unavailable";
    document.getElementById("mode-pill").textContent = "OFFLINE";
    app.innerHTML = `<div class="error-state"><h1>We couldn’t open the workspace.</h1><p>${escape(error.message)}</p><button class="primary-button" data-action="retry">Try again</button></div>`;
  }
}
document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  if (button.dataset.action === "retry") return initialize();
  if (button.dataset.action === "dismiss") return notice();
  if (!state.health) return;
  if (button.dataset.view) {
    state.view = button.dataset.view;
    render();
  }
  if (button.dataset.case) selectCase(button.dataset.case);
  if (button.dataset.filter) {
    state.filter = button.dataset.filter;
    if (state.filter === "flagged" && !selectedCase().detection.flagged) {
      const first = state.cases.find((row) => row.detection.flagged);
      if (first) return selectCase(first.transaction.transaction_id);
    }
    render();
  }
  if (button.dataset.tab) {
    state.tab = button.dataset.tab;
    render();
  }
  if (button.dataset.action === "investigate") runInvestigation();
  if (button.dataset.action === "download") downloadReport();
  if (button.dataset.action === "retry-history") loadHistory();
});
document.addEventListener("keydown", (event) => {
  const tab = event.target.closest('[role="tab"]');
  if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
    return;
  event.preventDefault();
  const tabs = ["assessment", "trace", "json"],
    index = tabs.indexOf(state.tab);
  state.tab =
    event.key === "Home"
      ? tabs[0]
      : event.key === "End"
        ? tabs[2]
        : tabs[(index + (event.key === "ArrowRight" ? 1 : 2)) % 3];
  render();
  document.getElementById(`tab-${state.tab}`).focus();
});
initialize();
