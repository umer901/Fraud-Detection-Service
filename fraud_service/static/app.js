"use strict";

const $ = (id) => document.getElementById(id);
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[char],
  );
const money = (cents) =>
  new Intl.NumberFormat("en-IE", {
    style: "currency",
    currency: "EUR",
  }).format(cents / 100);
const date = (value) =>
  new Date(value).toISOString().replace("T", " ").replace(".000Z", " UTC");
const json = (value) => escape(JSON.stringify(value, null, 2));
const state = {
  health: null,
  cases: [],
  selected: null,
  reports: new Map(),
  busy: false,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { Accept: "application/json" },
  });
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`,
    );
  return body;
}

function showError(message = "") {
  $("error").textContent = message;
  $("error").hidden = !message;
}

function reportURL(report) {
  const url = new URL(location.href);
  url.search = "";
  url.searchParams.set(
    "transaction",
    state.selected.transaction.transaction_id,
  );
  if (report) url.searchParams.set("investigation", report.investigation_id);
  return url;
}

function setControls() {
  const missingKey =
    state.health.mode === "groq" && !state.health.live_configured;
  $("investigate").disabled = state.busy || missingKey;
  $("investigate").textContent = state.busy ? "Investigating…" : "Investigate";
  document.querySelectorAll('[name="transaction"]').forEach((input) => {
    input.disabled = state.busy;
  });
}

function renderResult() {
  const report = state.reports.get(state.selected.transaction.transaction_id);
  $("result-section").hidden = !report;
  history.replaceState(null, "", reportURL(report));
  if (!report) return;

  const assessment = report.assessment;
  $("result").innerHTML = `
    <dl>
      <dt>Rule score</dt><dd>${report.detection.risk_score}/100 (${escape(report.detection.risk_level)})</dd>
      <dt>Assessment</dt><dd><strong>${escape(assessment.risk_level)} risk</strong></dd>
      <dt>Mode</dt><dd>${report.mode === "demo" ? "Groq" : `Groq — ${escape(report.model)}`}</dd>
      <dt>Duration</dt><dd>${(report.duration_ms / 1000).toFixed(1)} seconds</dd>
      <dt>Report ID</dt><dd><code>${escape(report.investigation_id)}</code></dd>
    </dl>
    <p>${escape(assessment.summary)}</p>
    <h3>Evidence</h3>
    <ul>${assessment.evidence.map((item) => `<li>${escape(item.observation)}<br><code>${item.transaction_ids.map(escape).join(", ")}</code></li>`).join("")}</ul>
    <h3>Recommended actions</h3>
    <ul>${assessment.recommended_actions.map((action) => `<li>${escape(action)}</li>`).join("")}</ul>
    <details><summary>Limitations</summary><ul>${assessment.limitations.map((line) => `<li>${escape(line)}</li>`).join("")}</ul><p>No payments or accounts were modified.</p></details>`;
  $("trace").innerHTML = report.tool_trace
    .map(
      (call) => `
    <details><summary>${call.sequence}. <code>${escape(call.tool)}</code> (${call.duration_ms.toFixed(0)} ms)</summary>
      <p>Arguments</p><pre>${json(call.arguments)}</pre>
      <p>Result</p><pre>${json(call.result)}</pre>
    </details>`,
    )
    .join("");
  $("json").textContent = JSON.stringify(report, null, 2);
  $("saved-report").href = reportURL(report);
}

function selectTransaction(id) {
  state.selected =
    state.cases.find((row) => row.transaction.transaction_id === id) ||
    state.cases[0];
  const { transaction: tx, detection } = state.selected;
  document.querySelectorAll('[name="transaction"]').forEach((input) => {
    input.checked = input.value === tx.transaction_id;
  });
  $("transaction").innerHTML = `
    <dl>
      <dt>ID</dt><dd><code>${escape(tx.transaction_id)}</code></dd>
      <dt>Account</dt><dd><code>${escape(tx.account_id)}</code></dd>
      <dt>Merchant</dt><dd>${escape(tx.merchant)}</dd>
      <dt>Amount</dt><dd>${money(tx.amount_cents)}</dd>
      <dt>Country / channel</dt><dd>${escape(tx.country)} / ${escape(tx.channel)}</dd>
      <dt>Time</dt><dd>${escape(date(tx.timestamp))}</dd>
      <dt>Rule score</dt><dd>${detection.risk_score}/100 (${escape(detection.risk_level)}) — ${detection.flagged ? "flagged for review" : "not flagged"}</dd>
    </dl>
    ${detection.matched_rules.length ? `<ul>${detection.matched_rules.map((rule) => `<li><strong>${escape(rule.title)} (+${rule.points}):</strong> ${escape(rule.explanation)}</li>`).join("")}</ul>` : "<p>No rules triggered.</p>"}
    <p class="note">The rule score is a sum of weights, not a fraud probability.</p>
    <details><summary>Transaction JSON <code>get_transaction_details</code></summary><pre>${json(tx)}</pre></details>`;
  $("history-details").open = false;
  $("history").textContent = "";
  $("endpoint").textContent = `POST /investigate/${tx.transaction_id}`;
  $("status").textContent = "";
  setControls();
  renderResult();
}

async function loadHistory() {
  if (!$("history-details").open || !state.selected) return;
  const accountId = state.selected.transaction.account_id;
  $("history").textContent = "Loading…";
  try {
    const result = await api(
      `/accounts/${encodeURIComponent(accountId)}/history`,
    );
    if (state.selected.transaction.account_id !== accountId) return;
    $("history").innerHTML =
      `<p>${escape(result.account.name)} · ${escape(result.account.account_type)} · Home country: ${escape(result.account.home_country)}</p>
      <div class="table-scroll" tabindex="0" role="region" aria-label="Account transactions"><table><thead><tr><th>ID</th><th>Time (UTC)</th><th>Merchant</th><th>Amount</th></tr></thead><tbody>${result.transactions.map((tx) => `<tr><td><code>${escape(tx.transaction_id)}</code></td><td>${escape(date(tx.timestamp))}</td><td>${escape(tx.merchant)}</td><td class="amount">${money(tx.amount_cents)}</td></tr>`).join("")}</tbody></table></div>
      <details><summary>Account history JSON</summary><pre>${json(result)}</pre></details>`;
  } catch (error) {
    if (state.selected.transaction.account_id === accountId)
      $("history").textContent = `${error.message} Close and reopen to retry.`;
  }
}

async function investigate() {
  if (state.busy) return;
  const id = state.selected.transaction.transaction_id;
  state.busy = true;
  showError();
  setControls();
  $("result-section").hidden = true;
  const start = Date.now();
  const update = () => {
    $("status").textContent =
      `Waiting for the backend… ${Math.floor((Date.now() - start) / 1000)}s. Results and completed MCP calls will appear below.`;
  };
  update();
  const timer = setInterval(update, 1000);
  try {
    const report = await api(`/investigate/${encodeURIComponent(id)}`, {
      method: "POST",
    });
    state.reports.set(id, report);
    $("status").textContent = "Investigation complete.";
  } catch (error) {
    showError(error.message);
    $("status").textContent = state.reports.has(id)
      ? "Request failed. The previous report is shown below."
      : "Request failed. You can retry.";
  } finally {
    clearInterval(timer);
    state.busy = false;
    setControls();
    renderResult();
  }
}

async function initialize() {
  showError();
  $("retry").hidden = true;
  $("mode").textContent = "Loading service information…";
  try {
    const [health, cases, rules] = await Promise.all([
      api("/health"),
      api("/demo/cases"),
      api("/fraud-rules"),
    ]);
    if (!cases.length)
      throw new Error("The backend returned no demo transactions.");
    state.health = health;
    state.cases = cases;
    $("mode").textContent =
      health.mode === "demo"
        ? `Mode: openai/gpt-oss-20b with MCP calls`
        : `Mode: Groq (${health.model}). Investigations use your API quota.`;
    if (health.mode === "groq" && !health.live_configured)
      showError(
        "Set GROQ_API_KEY on the server and restart, or use INVESTIGATION_MODE=demo.",
      );
    $("transactions").innerHTML = cases
      .map(
        (row) => `<tr>
      <td><label><input type="radio" name="transaction" value="${escape(row.transaction.transaction_id)}"><code>${escape(row.transaction.transaction_id)}</code></label></td>
      <td>${escape(row.demo_label)}</td><td class="amount">${money(row.transaction.amount_cents)}</td><td>${row.detection.risk_score}/100 (${escape(row.detection.risk_level)})</td>
    </tr>`,
      )
      .join("");
    $("rules").innerHTML =
      `<ul>${rules.rules.map((rule) => `<li><code>${escape(rule.id)}</code>: ${escape(rule.description)}</li>`).join("")}</ul><pre>${json(rules)}</pre>`;
    const params = new URLSearchParams(location.search);
    let transactionId = params.get("transaction") || "txn_spike";
    if (params.get("investigation")) {
      try {
        const report = await api(
          `/investigations/${encodeURIComponent(params.get("investigation"))}`,
        );
        if (
          !cases.some(
            (row) => row.transaction.transaction_id === report.transaction_id,
          )
        )
          throw new Error(
            "This saved report is outside the demo transactions.",
          );
        state.reports.set(report.transaction_id, report);
        transactionId = report.transaction_id;
      } catch (error) {
        showError(`Could not load the saved report: ${error.message}`);
      }
    }
    selectTransaction(transactionId);
    $("demo").hidden = false;
  } catch (error) {
    $("mode").textContent = "Service unavailable.";
    showError(error.message);
    $("retry").hidden = false;
  }
}

$("transactions").addEventListener("change", (event) => {
  if (event.target.name === "transaction")
    selectTransaction(event.target.value);
});
$("history-details").addEventListener("toggle", loadHistory);
$("investigate").addEventListener("click", investigate);
$("retry").addEventListener("click", initialize);
$("download").addEventListener("click", () => {
  const report = state.reports.get(state.selected.transaction.transaction_id);
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
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
initialize();
