"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const CATEGORY = { billing: "Billing", access: "Access & login", bug: "Bug", how_to: "How-to", feature_request: "Feature request",
  integration: "Integration", data_import: "Import / export", cancellation: "Cancellation", spam: "Spam" };
const THEME = { onboarding: "Onboarding", billing_pricing: "Billing & pricing", support_speed: "Support", bugs_reliability: "Bugs & reliability",
  missing_feature: "Missing feature", integrations: "Integrations", ease_of_use: "Ease of use", performance: "Performance",
  mobile: "Mobile app", praise_staff: "Praise for staff" };
const RISK = { refund: "Refund", cancellation: "Cancellation", legal: "Legal", security: "Security", outage_or_data_loss: "Outage / data loss", money_missing: "Money missing" };
const LANES = [
  { key: "auto", title: "Auto-resolved", cls: "auto" },
  { key: "Tier 1", title: "Tier 1", cls: "q" },
  { key: "Technical", title: "Technical", cls: "q" },
  { key: "Billing", title: "Billing", cls: "q" },
  { key: "Account Management", title: "Account Mgmt", cls: "q" },
  { key: "spam", title: "Spam review", cls: "spam" },
];
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const segColor = (score) => (score >= 9 ? css("--promoter") : score >= 7 ? css("--passive") : css("--detractor"));

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

/* ---------------- status, tabs, segmented controls */
const status = $("#model-status");
let modelReady = false, busyCount = 0;
function setStatus() {
  if (!modelReady) return;
  status.className = "status " + (busyCount ? "busy" : "ready");
  status.textContent = busyCount ? "Working…" : "Model ready · runs on this PC";
}
async function pollStatus() {
  try {
    const s = await api("/api/status");
    if (s.model_error) { status.className = "status failed"; status.textContent = "Model failed to start"; status.title = s.model_error; return; }
    if (s.model_ready) { modelReady = true; setStatus(); return; }
  } catch { /* server still starting */ }
  setTimeout(pollStatus, 1000);
}
async function busy(fn) {
  busyCount++; setStatus();
  try { return await fn(); } finally { busyCount--; setStatus(); }
}

$$(".tabs [role=tab]").forEach((tab) => tab.addEventListener("click", () => {
  $$(".tabs [role=tab]").forEach((t) => {
    const on = t === tab;
    t.setAttribute("aria-selected", on);
    $("#" + t.getAttribute("aria-controls")).hidden = !on;
  });
}));

function segmented(el, onChange) {
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$("button", el).forEach((x) => x.setAttribute("aria-checked", x === b));
    onChange?.(b.dataset.v);
  });
  return () => $("[aria-checked=true]", el).dataset.v;
}
const getPlan = segmented($("#plan"));
const getGroup = segmented($("#group"));
const setPlan = (v) => $$("#plan button").forEach((b) => b.setAttribute("aria-checked", b.dataset.v === v));

/* ---------------- triage */
const form = $("#ticket-form"), subject = $("#subject"), body = $("#body"), result = $("#result");
let loaded = null;           // test ticket currently in the form (with its correct answer)
const history = [];          // everything triaged this session
let selected = null;

function goldCheck(r, gold) {
  if (!gold) return null;
  const catOk = [gold.category, ...(gold.alt_category || [])].includes(r.category);
  return { catOk, decOk: r.resolution === gold.resolution };
}

function renderResult(item) {
  const { ticket, r, gold } = item;
  const head = {
    auto: ["✓", "Answered automatically", `Drafted from “${r.article?.title}”`],
    escalate: ["→", `Sent to ${r.queue}`, r.why],
    spam: ["✕", "Filed as spam", r.why.replace(/^spam: /, "")],
  }[r.resolution];
  const check = goldCheck(r, gold);
  result.className = "card result";
  result.innerHTML = `
    <div class="decision ${r.resolution}">
      <div class="icon" aria-hidden="true">${head[0]}</div>
      <div><h3>${esc(head[1])}</h3><p>${esc(head[2])}</p></div>
    </div>
    <div class="facts">
      <div class="fact"><span>Category</span><b>${esc(CATEGORY[r.category])}</b></div>
      <div class="fact"><span>Urgency</span><b class="${r.urgency === "urgent" ? "urgent" : ""}">${esc(r.urgency)}</b></div>
      <div class="fact"><span>Queue</span><b>${esc(r.resolution === "auto" ? "None needed" : r.queue)}</b></div>
    </div>
    ${r.risk_flags.length ? `<div class="chips">${r.risk_flags.map((f) => `<span class="chip risk">⚑ ${esc(RISK[f] || f)}</span>`).join("")}</div>` : ""}
    ${r.reply ? `<div class="reply-head"><span>Drafted reply</span><button type="button" class="ghost small" id="copy">Copy</button></div>
      <div class="reply">${esc(r.reply)}</div>` : ""}
    ${r.article ? `<details><summary>${r.article.custom ? "Your article" : "Help article"} it used: [${esc(r.article.id)}] ${esc(r.article.title)}</summary><div class="article">${esc(r.article.body)}</div>
      <button type="button" class="ghost small" style="margin-top:8px" data-open-article="${esc(r.article.id)}">Open in Help center</button></details>` : ""}
    ${check ? `<div class="gold"><b>Test set answer</b> (${esc(ticket.id)}): ${esc(CATEGORY[gold.category])}, ${esc(gold.urgency)},
      ${gold.resolution === "auto" ? "answer automatically" : gold.resolution === "spam" ? "spam" : "send to " + esc(gold.queue)}.<br>
      Category <span class="${check.catOk ? "ok" : "no"}">${check.catOk ? "matches" : "differs"}</span>,
      decision <span class="${check.decOk ? "ok" : "no"}">${check.decOk ? "matches" : "differs"}</span>.
      ${gold.note ? `<div class="dim" style="margin-top:6px">${esc(gold.note)}</div>` : ""}</div>` : ""}
    <div class="meta">${esc(ticket.plan)} plan · ${r.seconds}s on the local model</div>`;
  $("#copy")?.addEventListener("click", (e) => { navigator.clipboard.writeText(r.reply); e.target.textContent = "Copied"; });
}

async function runTriage(ticket, gold) {
  const r = await api("/api/triage", ticket);
  const item = { ticket, r, gold, n: history.length + 1 };
  history.push(item);
  selected = item;
  renderResult(item);
  renderBoard(item);
  return item;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!body.value.trim()) { body.focus(); return; }
  const ticket = { id: "typed", plan: getPlan(), subject: subject.value.trim(), body: body.value.trim() };
  const gold = loaded && loaded.body === ticket.body && loaded.subject === ticket.subject ? loaded.gold : null;
  if (gold) ticket.id = loaded.id;
  $("#triage-btn").disabled = true; result.classList.add("loading");
  try { await busy(() => runTriage(ticket, gold)); }
  catch (err) { result.className = "card result"; result.innerHTML = `<p class="error">${esc(err.message)}</p>`; }
  finally { $("#triage-btn").disabled = false; result.classList.remove("loading"); }
});
body.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.ctrlKey) form.requestSubmit(); });

async function loadSample(kind = "any") {
  loaded = await api("/api/sample?kind=" + kind);
  subject.value = loaded.subject; body.value = loaded.body; setPlan(loaded.plan);
  return loaded;
}
$("#sample-btn").addEventListener("click", () => loadSample().catch((e) => alertInline(e)));
// Batches mix the kinds of ticket so the board shows every lane (roughly the test set's proportions).
const BATCH_MIX = ["auto", "escalate", "auto", "spam", "escalate", "auto", "escalate", "auto"];
function alertInline(e) { result.className = "card result"; result.innerHTML = `<p class="error">${esc(e.message)}</p>`; }

let stopBatch = false;
$$("[data-batch]").forEach((b) => b.addEventListener("click", async () => {
  const n = +b.dataset.batch, prog = $("#batch-progress");
  $$("[data-batch], #triage-btn, #sample-btn").forEach((x) => (x.disabled = true));
  $("#batch-stop").hidden = false; stopBatch = false;
  try {
    for (let i = 1; i <= n && !stopBatch; i++) {
      prog.textContent = `${i} of ${n}…`;
      const t = await loadSample(BATCH_MIX[(i - 1) % BATCH_MIX.length]);
      await busy(() => runTriage({ id: t.id, plan: t.plan, subject: t.subject, body: t.body }, t.gold));
    }
    prog.textContent = stopBatch ? "Stopped." : "Done.";
  } catch (e) { alertInline(e); }
  finally { $$("[data-batch], #triage-btn, #sample-btn").forEach((x) => (x.disabled = false)); $("#batch-stop").hidden = true; }
}));
$("#batch-stop").addEventListener("click", () => (stopBatch = true));

function laneOf(r) { return r.resolution === "auto" ? "auto" : r.resolution === "spam" ? "spam" : r.queue; }
function renderBoard(fresh) {
  const board = $("#board");
  board.innerHTML = LANES.map((l) => {
    const items = history.filter((h) => laneOf(h.r) === l.key).reverse();
    return `<div class="lane ${l.cls}"><h3>${esc(l.title)} <span class="n">${items.length}</span></h3>${items.map((h) => {
      const c = goldCheck(h.r, h.gold), miss = c && !(c.catOk && c.decOk);
      return `<button type="button" class="tcard${h === fresh ? " new" : ""}${h === selected ? " selected" : ""}" data-n="${h.n}">
        <b>${esc(h.ticket.subject || h.ticket.body)}</b>
        <span class="sub"><span>${esc(h.ticket.plan)}</span><span class="${h.r.urgency === "urgent" ? "urgent" : ""}">${esc(h.r.urgency)}</span>
        ${c ? `<span class="${miss ? "miss" : ""}">${miss ? "≠ test answer" : "✓ test answer"}</span>` : ""}</span></button>`;
    }).join("") || `<p class="dim small" style="margin:4px">Empty</p>`}</div>`;
  }).join("");
  const checked = history.filter((h) => h.gold), right = checked.filter((h) => { const c = goldCheck(h.r, h.gold); return c.decOk; });
  $("#board-count").textContent = history.length ? `· ${history.length} triaged${checked.length ? `, ${right.length} of ${checked.length} test tickets decided correctly` : ""}` : "";
}
$("#board").addEventListener("click", (e) => {
  const c = e.target.closest(".tcard"); if (!c) return;
  selected = history.find((h) => h.n === +c.dataset.n);
  renderResult(selected); renderBoard();
  result.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
$("#board-clear").addEventListener("click", () => { history.length = 0; selected = null; renderBoard(); });
renderBoard();

/* ---------------- one comment */
let score = null;
$("#score").innerHTML = Array.from({ length: 11 }, (_, i) =>
  `<button type="button" role="radio" aria-checked="false" class="${i >= 9 ? "pr" : i >= 7 ? "p" : "d"}" data-v="${i}">${i}</button>`).join("");
$("#score").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  score = +b.dataset.v;
  $$("#score button").forEach((x) => x.setAttribute("aria-checked", x === b));
  $("#score-label").textContent = score >= 9 ? "promoter" : score >= 7 ? "passive" : "detractor";
});
$("#comment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const out = $("#comment-result"), comment = $("#comment").value.trim();
  if (score === null) { out.innerHTML = `<p class="error">Pick a score first.</p>`; return; }
  if (!comment) { $("#comment").focus(); return; }
  $("#comment-btn").disabled = true; out.innerHTML = `<p class="dim">Analyzing…</p>`;
  try {
    const t = await busy(() => api("/api/comment", { score, plan: getPlan(), comment }));
    out.innerHTML = `<div class="tagline">
        <span class="flag ${t.follow_up ? "yes" : "no"}">${t.follow_up ? "⚑ Follow up with this customer" : "No follow-up needed"}</span>
        <span class="chip">${esc(t.segment)}</span><span class="chip">${esc(t.sentiment)}</span>
        ${t.themes.map((x) => `<span class="chip">${esc(THEME[x] || x)}</span>`).join("") || `<span class="dim small">no specific themes</span>`}
      </div><p class="dim small" style="margin:8px 0 0">${esc(t.reason)} · ${t.seconds}s</p>`;
  } catch (err) { out.innerHTML = `<p class="error">${esc(err.message)}</p>`; }
  finally { $("#comment-btn").disabled = false; }
});

/* ---------------- survey report */
const prog = $("#survey-progress");
$("#survey-btn").addEventListener("click", async () => {
  $("#survey-btn").disabled = true; prog.hidden = false; busyCount++; setStatus();
  try {
    let s = await api("/api/survey", { group: getGroup() });
    while (s.state === "running") {
      const pct = s.total ? (100 * s.done) / s.total : 0;
      $(".progress-fill", prog).style.width = `${s.step === "Writing the summary" ? 100 : pct}%`;
      $("span", prog).textContent = s.step === "Writing the summary" ? "Writing the summary…" : `Tagging comments: ${s.done} of ${s.total || "…"}`;
      await new Promise((r) => setTimeout(r, 600));
      s = await api("/api/survey");
    }
    if (s.state === "error") throw new Error(s.error);
    renderReport(s.result);
    prog.hidden = true;
  } catch (e) { $("span", prog).innerHTML = `<span class="error">${esc(e.message)}</span>`; }
  finally { $("#survey-btn").disabled = false; busyCount--; setStatus(); }
});

let lastReport = null;
addEventListener("resize", () => { if (lastReport) renderReport(lastReport, false); });

function renderReport(rep, scroll = true) {
  lastReport = rep;
  const { stats, summary, unsupported, group } = rep;
  $("#report").hidden = false;
  const n = stats.responses, pct = (x) => Math.round((100 * x) / n);
  $("#kpis").innerHTML = `
    <div class="kpi"><span>NPS</span><b>${stats.nps > 0 ? "+" : ""}${stats.nps}</b><div class="sub">−100 to +100</div></div>
    <div class="kpi"><span>Responses</span><b>${n}</b><div class="sub">${group === "core" ? "May–Oct 2026" : "November 2026"}</div></div>
    <div class="kpi"><span>Promoters, passives, detractors</span>
      <div class="split" role="img" aria-label="${stats.promoters} promoters, ${stats.passives} passives, ${stats.detractors} detractors">
        <div style="flex:${stats.detractors};background:var(--detractor)" data-tip="Detractors (0–6): ${stats.detractors} · ${pct(stats.detractors)}%"></div>
        <div style="flex:${stats.passives};background:var(--passive)" data-tip="Passives (7–8): ${stats.passives} · ${pct(stats.passives)}%"></div>
        <div style="flex:${stats.promoters};background:var(--promoter)" data-tip="Promoters (9–10): ${stats.promoters} · ${pct(stats.promoters)}%"></div>
      </div>
      <div class="legend"><span><i style="background:var(--detractor)"></i>Detractors <b>${stats.detractors}</b> (${pct(stats.detractors)}%)</span>
        <span><i style="background:var(--passive)"></i>Passives <b>${stats.passives}</b> (${pct(stats.passives)}%)</span>
        <span><i style="background:var(--promoter)"></i>Promoters <b>${stats.promoters}</b> (${pct(stats.promoters)}%)</span></div></div>
    <div class="kpi"><span>Follow-ups</span><b>${stats.follow_up_count}</b><div class="sub">customers to contact</div></div>`;

  const months = Object.entries(stats.nps_by_month).map(([m, v]) => ({
    label: new Date(m + "-15").toLocaleString("en-US", { month: "short" }), value: v.nps, tip: `${m}: NPS ${v.nps} from ${v.responses} responses` }));
  // Draw at each panel's real width so text stays at its intended size.
  const width = (sel) => Math.max(240, Math.round($(sel).clientWidth));
  $("#chart-month").innerHTML = columnChart(months, width("#chart-month"));
  const plans = Object.entries(stats.nps_by_plan).map(([p, v]) => ({ label: p, value: v.nps, tip: `${p}: NPS ${v.nps} from ${v.responses} responses` }));
  $("#chart-plan").innerHTML = columnChart(plans, width("#chart-plan"));
  const themes = stats.detractor_themes.slice(0, 8).map(([t, c]) => ({ label: THEME[t] || t, value: c, tip: `${THEME[t] || t}: ${c} detractor mentions` }));
  $("#chart-themes").innerHTML = themes.length ? barList(themes, width("#chart-themes")) : `<p class="dim">No detractor themes.</p>`;

  $("#summary-text").innerHTML = markdown(summary);
  const badge = $("#numcheck");
  badge.className = "badge " + (unsupported.length ? "bad" : "ok");
  badge.textContent = unsupported.length ? `⚠ ${unsupported.length} number(s) not found in the data: ${unsupported.join(", ")}` : "✓ Every number checked against the data";

  $("#fu-count").textContent = `· ${stats.follow_up_count}, lowest score first`;
  $("#followups tbody").innerHTML = stats.follow_up.map((f) => `<tr>
      <td class="score"><span class="pill" style="background:${segColor(f.score)}">${f.score}</span></td><td>${esc(f.plan)}</td>
      <td>${esc(f.comment)}</td><td class="why">${esc(f.why)}</td></tr>`).join("");
  if (scroll) $("#report").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* Column chart with a zero baseline (NPS can be negative). Color encodes sign, labels carry the value. */
function columnChart(items, W = 360) {
  const hasNeg = items.some((d) => d.value < 0), hasPos = items.some((d) => d.value > 0);
  // Room for value labels above positive bars and below negative ones, plus the category row.
  const H = 200, top = hasPos ? 24 : 10, bottom = hasNeg ? 44 : 28, left = 8, right = 8;
  const max = Math.max(10, ...items.map((d) => Math.abs(d.value)));
  const lo = hasNeg ? -max : 0, hi = hasPos || !hasNeg ? max : 0;
  const y = (v) => top + ((hi - v) / (hi - lo)) * (H - top - bottom);
  const bw = (W - left - right) / items.length, barW = Math.min(46, bw * 0.62);
  const zero = y(0);
  const bars = items.map((d, i) => {
    const x = left + i * bw + (bw - barW) / 2, y0 = Math.min(y(d.value), zero), h = Math.max(2, Math.abs(y(d.value) - zero));
    const color = d.value >= 0 ? "var(--promoter)" : "var(--detractor)";
    const r = Math.min(4, h / 2), path = d.value >= 0
      ? `M${x},${y0 + h}V${y0 + r}q0,-${r} ${r},-${r}h${barW - 2 * r}q${r},0 ${r},${r}V${y0 + h}Z`
      : `M${x},${y0}V${y0 + h - r}q0,${r} ${r},${r}h${barW - 2 * r}q${r},0 ${r},-${r}V${y0}Z`;
    const ly = d.value >= 0 ? y0 - 6 : y0 + h + 13;
    return `<g data-tip="${esc(d.tip)}"><rect class="hit" x="${left + i * bw}" y="${top - 16}" width="${bw}" height="${H - top - bottom + 32}"></rect>
      <path class="bar" d="${path}" fill="${color}"></path>
      <text class="val" x="${x + barW / 2}" y="${ly}" text-anchor="middle">${d.value > 0 ? "+" : ""}${d.value}</text>
      <text x="${x + barW / 2}" y="${H - 8}" text-anchor="middle">${esc(d.label)}</text></g>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(items.map((d) => `${d.label} ${d.value}`).join(", "))}">
    <line class="zero" x1="${left}" x2="${W - right}" y1="${zero}" y2="${zero}"></line>${bars}</svg>`;
}

/* Horizontal bars for counts: one hue (the detractor color, since these are detractor mentions). */
function barList(items, W = 360) {
  const rowH = 24, labelW = 118, H = items.length * rowH + 4;
  const max = Math.max(...items.map((d) => d.value));
  const rows = items.map((d, i) => {
    const w = Math.max(3, ((W - labelW - 34) * d.value) / max), yy = i * rowH + 4;
    return `<g data-tip="${esc(d.tip)}"><rect class="hit" x="0" y="${yy - 2}" width="${W}" height="${rowH}"></rect>
      <text x="${labelW - 8}" y="${yy + 13}" text-anchor="end">${esc(d.label)}</text>
      <path class="bar" d="M${labelW},${yy + 3}h${w - 4}q4,0 4,4v6q0,4 -4,4h-${w - 4}Z" fill="var(--detractor)"></path>
      <text class="val" x="${labelW + w + 6}" y="${yy + 13}">${d.value}</text></g>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(items.map((d) => `${d.label} ${d.value}`).join(", "))}">${rows}</svg>`;
}

/* Tiny Markdown renderer for the summary: **bold**, bullets, paragraphs, bold-only lines as headings. */
function markdown(md) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  let html = "", list = false;
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trim();
    const bullet = line.match(/^[*-]\s+(.*)/);
    if (bullet) { if (!list) { html += "<ul>"; list = true; } html += `<li>${inline(bullet[1])}</li>`; continue; }
    if (list) { html += "</ul>"; list = false; }
    if (!line) continue;
    const heading = line.match(/^(?:#+\s*)?\*\*(.+?)\*\*:?$/) || line.match(/^#+\s*(.+)$/);
    html += heading ? `<h4>${esc(heading[1])}</h4>` : `<p>${inline(line)}</p>`;
  }
  return html + (list ? "</ul>" : "");
}

/* ---------------- help center */
const kb = { list: [], selected: null, filter: "all", maxBody: 2000, maxCustom: 25, file: "" };
const getKbFilter = segmented($("#kb-filter"), (v) => { kb.filter = v; renderKbList(); });
const kbSearch = $("#kb-search");

function showTab(id) { $("#" + id).click(); }
function toast(msg) {
  const t = Object.assign(document.createElement("div"), { className: "toast", textContent: msg });
  document.body.append(t); setTimeout(() => t.remove(), 2600);
}
const highlight = (text, q) => {
  const safe = esc(text);
  if (!q) return safe;
  const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/&/g, "&amp;")})`, "gi");
  return safe.replace(re, "<mark>$1</mark>");
};

async function loadArticles(selectId) {
  const r = await api("/api/articles");
  Object.assign(kb, { list: r.articles, maxBody: r.max_body, maxCustom: r.max_custom, file: r.custom_file });
  if (selectId !== undefined) kb.selected = selectId;
  if (!kb.list.some((a) => a.id === kb.selected)) kb.selected = kb.list[0]?.id ?? null;
  renderKbList();
  if (kb.selected) renderArticle(kb.selected);
}

function kbMatches() {
  const q = kbSearch.value.trim().toLowerCase();
  return kb.list.filter((a) => (kb.filter === "all" || (kb.filter === "custom") === a.custom)
    && (!q || (a.title + " " + a.body + " " + a.id).toLowerCase().includes(q)));
}

function renderKbList() {
  const items = kbMatches(), q = kbSearch.value.trim(), mine = kb.list.filter((a) => a.custom).length;
  $("#kb-count").textContent = `${items.length} of ${kb.list.length} articles · ${mine} of yours (up to ${kb.maxCustom})`;
  $("#kb-items").innerHTML = items.map((a) => `
    <button type="button" class="kb-item" role="option" aria-selected="${a.id === kb.selected}" data-id="${esc(a.id)}">
      <b>${highlight(a.title, q)}</b>
      <span class="sub"><code>${esc(a.id)}</code>${a.custom ? `<span class="tag mine">Yours</span>` : `<span>answers ${a.tickets.length} test ticket${a.tickets.length === 1 ? "" : "s"}</span>`}</span>
    </button>`).join("") || `<p class="dim small" style="padding:8px">No articles match.${kb.filter !== "builtin" && !mine ? " Add your own with + New article." : ""}</p>`;
}

function renderArticle(id) {
  const a = kb.list.find((x) => x.id === id), d = $("#kb-detail"), q = kbSearch.value.trim();
  if (!a) { d.innerHTML = ""; return; }
  kb.selected = id;
  d.innerHTML = `
    <div class="crumb"><code>${esc(a.id)}</code><span class="tag ${a.custom ? "mine" : ""}">${a.custom ? "Your article" : "Built-in · read-only"}</span></div>
    <h2>${highlight(a.title, q)}</h2>
    <div class="kb-body">${highlight(a.body, q)}</div>
    ${a.custom ? `<div class="actions"><button type="button" class="ghost" id="kb-edit">Edit</button><button type="button" class="danger" id="kb-delete">Delete</button></div>
      <div class="tipbox">The app's triage can now answer tickets from this article. Try it: write a ticket it answers on the <b>Ticket triage</b> tab.</div>`
    : `<div class="kb-section"><h3>Test tickets this article answers (${a.tickets.length})</h3>
      ${a.tickets.length ? `<ul class="kb-tickets">${a.tickets.map((t) => `<li><code>${esc(t.id)}</code><span>${esc(t.subject)}</span>
        <button type="button" class="ghost small" data-try-ticket="${esc(t.id)}">Try it</button></li>`).join("")}</ul>`
      : `<p class="dim small">None of the test tickets need this article; it's there so the tool has a realistic help center.</p>`}</div>`}`;
  $$(".kb-item").forEach((b) => b.setAttribute("aria-selected", b.dataset.id === id));
  $("#kb-edit")?.addEventListener("click", () => renderEditor(a));
  $("#kb-delete")?.addEventListener("click", () => confirmDelete(a));
}

function renderEditor(a = null) {
  const d = $("#kb-detail");
  d.innerHTML = `<form class="editor" id="kb-form" autocomplete="off">
      <div class="crumb">${a ? `<code>${esc(a.id)}</code>Editing your article` : "New article"}</div>
      <label for="kb-title">Title</label>
      <input id="kb-title" maxlength="120" value="${esc(a?.title ?? "")}" placeholder="e.g. Office hours for phone support" required>
      <label for="kb-body">Article text</label>
      <textarea id="kb-body" maxlength="${kb.maxBody}" placeholder="Write it the way a help article reads: what the customer should do, with the exact menu paths, numbers, and limits.">${esc(a?.body ?? "")}</textarea>
      <div class="counter" id="kb-counter"></div>
      <div class="actions"><button type="submit" class="primary">${a ? "Save changes" : "Add article"}</button>
        <button type="button" class="ghost" id="kb-cancel">Cancel</button><span id="kb-err" class="error small"></span></div>
      <div class="tipbox"><b>Tips for articles the tool can use well:</b> one topic per article; put the specific facts in the text
        (Settings &gt; ... paths, time limits, prices, which plan has the feature). The tool only answers when one article fully
        covers the question, and it quotes facts from it. Saved to <code>${esc(kb.file)}</code>, outside the project, so it's never published.</div>
    </form>`;
  const body = $("#kb-body"), counter = $("#kb-counter");
  const count = () => { counter.textContent = `${body.value.length} / ${kb.maxBody} characters`; counter.classList.toggle("over", body.value.length >= kb.maxBody); };
  body.addEventListener("input", count); count();
  $("#kb-title").focus();
  $("#kb-cancel").addEventListener("click", () => (kb.selected ? renderArticle(kb.selected) : (d.innerHTML = "")));
  $("#kb-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const saved = await api("/api/articles", { id: a?.id, title: $("#kb-title").value, body: body.value });
      kb.filter = "all"; $$("#kb-filter button").forEach((x) => x.setAttribute("aria-checked", x.dataset.v === "all"));
      kbSearch.value = "";
      await loadArticles(saved.id);
      toast(a ? "Article saved" : "Article added. Triage can use it now.");
    } catch (err) { $("#kb-err").textContent = err.message; }
  });
}

function confirmDelete(a) {
  const d = $("#kb-detail");
  d.insertAdjacentHTML("beforeend", `<div class="tipbox" id="kb-confirm">Delete <b>${esc(a.title)}</b>? This can't be undone.
    <div class="actions"><button type="button" class="danger" id="kb-yes">Delete it</button><button type="button" class="ghost" id="kb-no">Keep it</button></div></div>`);
  $("#kb-delete").disabled = true;
  $("#kb-no").addEventListener("click", () => renderArticle(a.id));
  $("#kb-yes").addEventListener("click", async () => {
    try { await fetch(`/api/articles/${encodeURIComponent(a.id)}`, { method: "DELETE" }); await loadArticles(null); toast("Article deleted"); }
    catch (err) { toast(err.message); }
  });
}

$("#kb-items").addEventListener("click", (e) => { const b = e.target.closest(".kb-item"); if (b) renderArticle(b.dataset.id); });
kbSearch.addEventListener("input", () => { renderKbList(); if (kb.selected) renderArticle(kb.selected); });
$("#kb-new").addEventListener("click", () => {
  if (kb.list.filter((a) => a.custom).length >= kb.maxCustom) return toast(`You can add up to ${kb.maxCustom} articles.`);
  $$(".kb-item").forEach((b) => b.setAttribute("aria-selected", false));
  renderEditor();
});
$("#tab-kb").addEventListener("click", () => { if (!kb.list.length) loadArticles().catch((e) => ($("#kb-detail").innerHTML = `<p class="error">${esc(e.message)}</p>`)); });

// Cross-links: "Open in Help center" from a triage result, and "Try it" from an article's test tickets.
document.addEventListener("click", async (e) => {
  const open = e.target.closest("[data-open-article]");
  if (open) {
    showTab("tab-kb"); kbSearch.value = "";
    await loadArticles(open.dataset.openArticle);
    return;
  }
  const tryIt = e.target.closest("[data-try-ticket]");
  if (tryIt) {
    const t = await api("/api/sample?id=" + encodeURIComponent(tryIt.dataset.tryTicket));
    loaded = t; subject.value = t.subject; body.value = t.body; setPlan(t.plan);
    showTab("tab-triage"); form.requestSubmit();
  }
});

/* ---------------- shared hover tooltip for any [data-tip] */
const tip = $("#tooltip");
document.addEventListener("mousemove", (e) => {
  const t = e.target.closest("[data-tip]");
  if (!t) { tip.hidden = true; return; }
  tip.textContent = t.dataset.tip; tip.hidden = false;
  const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px"; tip.style.top = e.clientY + 16 + "px";
});

pollStatus();
