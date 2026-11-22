"use strict";

const token = document.querySelector('meta[name="news-agent-token"]').content;
const main = document.querySelector("#main");
const state = { settings: null, runs: [], current: null, mode: "live", days: 7, budget: 3,
  filter: "all", search: "", pitch: null, questions: new Map(), documents: new Map(), dirty: new Set(),
  documentName: null, editorMode: "preview", busy: false, poll: null, route: "" };
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const date = value => new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short", year: "numeric" }).format(new Date(value));
const documentLabel = name => ({ "article.md": "Article", "reporting-notes.md": "Reporting notes", "reporting-brief.md": "Reporting brief" }[name] || name);
const safeURL = value => { try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : "#"; } catch { return "#"; } };
const domain = value => { try { return new URL(value).hostname.replace(/^www\./, ""); } catch { return "Source"; } };
const docKey = name => `${state.current?.id}/${name}`;
const questionKey = pitch => `${state.current?.id}/${pitch.id}`;

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options, headers: { "Content-Type": "application/json", "X-News-Agent-Token": token, ...options.headers } });
  let payload;
  try { payload = await response.json(); } catch { throw new Error("The workspace returned an unreadable response. Refresh and try again."); }
  if (!response.ok) throw new Error(payload.error || "This request could not be completed.");
  return payload;
}

let noticeTimer;
function notify(message, error = false) {
  const notice = document.querySelector("#notice");
  notice.textContent = message;
  notice.setAttribute("role", error ? "alert" : "status");
  notice.classList.toggle("is-error", error);
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice.hidden = true; }, error ? 10000 : 4500);
}

function label(run) {
  if (run.active) return ["Reporting in progress", "ready"];
  if (run.status === "awaiting_editor") return ["Needs an angle", "attention"];
  if (run.status === "error") return ["Reporting paused", "error"];
  if (run.outcome === "reporting_brief" || run.verification?.outcome === "reporting_brief") return ["Reporting brief", "attention"];
  if (run.status === "complete") return ["Ready to edit", "ready"];
  if (run.status === "dismissed") return ["Set aside", ""];
  if (run.status === "no_pitches") return ["No new pitches", ""];
  return ["Interrupted", "attention"];
}
function badge(run) { const [text, style] = label(run); return `<span class="status ${style}">${escapeHTML(text)}</span>`; }
function runRows(runs) {
  if (!runs.length) return '<div class="empty-inline">No briefings here yet. Start a new briefing to find your first story.</div>';
  return runs.map(run => `<button class="run-row" data-action="open-run" data-id="${escapeHTML(run.id)}"><span class="run-file-icon">${icon(run.outcome === "article" ? "edit" : "files")}</span><span><span class="run-title">${escapeHTML(run.title)}</span><span class="run-meta"><span>${date(run.created_at)}</span><span>·</span><span>${run.mode === "offline" ? "Fictional sample" : "Live news"}</span></span></span>${badge(run)}</button>`).join("");
}
function updateNavigation() {
  const page = location.hash.startsWith("#run/") ? "runs" : location.hash.slice(1) || "desk";
  document.querySelectorAll("[data-nav]").forEach(link => {
    const selected = link.dataset.nav === page;
    link.classList.toggle("active", selected);
    if (selected) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  document.querySelector("#section-title").textContent = ({ desk: "Editorial desk", runs: "Saved runs", sources: "Sources & connections" }[page] || "Editorial desk");
  document.querySelector("#run-count").textContent = state.runs.length;
  document.querySelector("#recent-nav").innerHTML = state.runs.length ? state.runs.slice(0, 4).map(run => `<button class="recent-nav-item" data-action="open-run" data-id="${escapeHTML(run.id)}"><span>${escapeHTML(run.title)}</span><small>${date(run.created_at)} · ${escapeHTML(label(run)[0])}</small></button>`).join("") : '<p class="sidebar-hint">Your briefings will be saved here.</p>';
}

function connections() {
  return [["groq", "Groq primary"], ["qwen", "Qwen fallback"], ["search", "Tavily research"]].map(([key, name]) => `<div class="connection-state ${state.settings[key] ? "" : "missing"}">${state.settings[key] ? icon("check") : '<span class="step-dot"></span>'}${name}${state.settings[key] ? "" : " · not set"}</div>`).join("");
}

function renderDesk() {
  const ready = state.settings.search && (state.settings.groq || state.settings.qwen);
  main.innerHTML = `<div class="page-header"><div><div class="eyebrow">The editorial desk</div><h1>Find your next story.</h1><p class="page-description">A fresh development. A useful question. A draft you can stand behind.</p></div><a class="button quiet" href="#runs">${icon("files")} Saved runs</a></div>
    <div class="desk-grid"><form id="discovery-form" class="discovery-form"><div class="section-topline"><h2>Start a new briefing</h2><span class="tiny-label">KENYA & BEYOND</span></div>
    <div class="mode-switch" aria-label="News source mode"><button type="button" data-action="mode" data-mode="live" aria-pressed="${state.mode === "live"}">Live news</button><button type="button" data-action="mode" data-mode="offline" aria-pressed="${state.mode === "offline"}">Fictional sample</button></div>
    <p class="mode-description">${state.mode === "live" ? "Discover recent developments from Kenyan and international sources, grouped into up to three story pitches." : "Try the complete workflow with a fictional AI storefront launch. No API calls or credentials needed."}</p>
    ${!ready && state.mode === "live" ? '<div class="message">Load your model and Tavily keys in the terminal before starting live news. <a href="#sources">Check connections</a>, or try the fictional sample.</div>' : ""}
    <div class="field-grid"><div class="field"><label for="recent-days">Look back</label><select id="recent-days" name="recent_days">${[3,7,14,30].map(n => `<option value="${n}" ${state.days === n ? "selected" : ""}>Last ${n} days</option>`).join("")}</select><p class="field-help">Look for fresh developments.</p></div><div class="field"><label for="search-budget">Research budget</label><select id="search-budget" name="search_budget">${[0,1,3,5,10].map(n => `<option value="${n}" ${state.budget === n ? "selected" : ""}>${n === 0 ? "Source pages only" : `Up to ${n} ${n === 1 ? "search" : "searches"}`}</option>`).join("")}</select><p class="field-help">Used after you approve an angle.</p></div></div>
    <button class="button primary discovery-submit" type="submit" ${state.busy || (state.mode === "live" && !ready) ? "disabled" : ""}>${icon("search")}${state.busy ? "Starting your briefing…" : "Find stories"}</button><p class="form-note">${state.mode === "live" ? "Live research uses your provider accounts. Your shortlist is saved automatically." : "Sample material is clearly labelled and is not for publication."}</p></form>
    <aside class="studio-brief"><div class="eyebrow">The editor’s brief</div><h2>Useful to someone.<br>Grounded in something.</h2><p>Stories for Kenyan SME owners, brand builders, vibe coders and tech practitioners. Start with what changed. Keep the reader in view.</p><ul class="workflow-notes"><li>${icon("source")}<span><strong>Discover the development</strong><span>Fresh reporting, grouped by event.</span></span></li><li>${icon("edit")}<span><strong>Make the question yours</strong><span>You choose the reader and angle.</span></span></li><li>${icon("check")}<span><strong>Review before publishing</strong><span>Trace the claims. Keep the final word.</span></span></li></ul></aside></div>
    <div class="connection-strip"><span>YOUR CONNECTIONS</span>${connections()}</div><div class="section-heading"><h2>Pick up where you left off</h2><button class="text-button" data-action="all-runs">View all runs</button></div><div class="run-list">${runRows(state.runs.slice(0,4))}</div>`;
}

function filteredRuns() {
  return state.runs.filter(run => (state.filter === "all" || (state.filter === "angle" ? run.status === "awaiting_editor" : run.status === "complete")) && `${run.title} ${run.id}`.toLowerCase().includes(state.search.toLowerCase()));
}
function renderRuns() {
  main.innerHTML = `<div class="page-header"><div><div class="eyebrow">Your working archive</div><h1>Saved runs.</h1><p class="page-description">Every shortlist, approved question and reporting outcome. Ready when you return.</p></div><button class="button primary" data-action="new">${icon("plus")} New briefing</button></div>
    <div class="filter-bar"><div class="filter-buttons" aria-label="Filter saved runs">${[["all","All runs"],["angle","Needs an angle"],["review","Ready to review"]].map(([key,text]) => `<button data-action="filter" data-filter="${key}" class="${state.filter === key ? "active" : ""}" aria-pressed="${state.filter === key}">${text}</button>`).join("")}</div><div class="search-field">${icon("search")}<input id="run-search" aria-label="Search saved runs" placeholder="Find a briefing…" value="${escapeHTML(state.search)}"></div></div><div id="history-list" class="run-list">${runRows(filteredRuns())}</div>`;
}

function renderSources() {
  const settings = state.settings;
  main.innerHTML = `<div class="page-header"><div><div class="eyebrow">The reporting foundation</div><h1>Sources & connections.</h1><p class="page-description">Discovery begins with these feeds. Your approved question directs follow-up research.</p></div></div><h2>Provider connections</h2><div class="connection-grid">${[["groq","Groq","The first model provider attempted for each task."],["qwen","Qwen","Optional fallback when Groq cannot complete a request."],["search","Tavily","Follow-up searches for original sources and evidence."]].map(([key,title,description]) => `<div class="connection-row"><div><strong>${title}</strong><p>${description}</p></div><span class="status ${settings[key] ? "ready" : "attention"}">${settings[key] ? "Key loaded" : "Not configured"}</span></div>`).join("")}</div>
    <p class="quiet-copy">Keys stay in the server environment. “Key loaded” confirms configuration, not a successful provider request. If you update your .env file, reload it in your terminal and restart this workspace.</p><pre class="setup-command">set -a\nsource .env\nset +a\npython -m deluxe --home .deluxe/live-test serve</pre>
    <div class="section-heading"><h2>Discovery sources</h2><span class="tiny-label">${settings.sources.length} FEEDS</span></div>${settings.sources.map(source => `<div class="feed-row"><div><strong>${escapeHTML(source.publisher)}</strong><a href="${escapeHTML(safeURL(source.url))}" target="_blank" rel="noopener noreferrer">${escapeHTML(domain(source.url))}</a></div><span class="region">${escapeHTML(source.region || "International")}</span></div>`).join("")}<p class="quiet-copy">Feed and page access can vary. Any unavailable sources appear in the run’s reporting warnings. Live runs never substitute fictional sample material.</p>`;
}

function stepper(run) {
  let current = run.documents.length ? 3 : run.approved_question ? 2 : run.pitches.length ? 1 : 0;
  return `<div class="stepper" aria-label="Editorial workflow">${["Discover","Choose an angle","Research & draft","Review"].map((text,index) => `<div class="step ${index === current ? "current" : index < current ? "done" : ""}" ${index === current ? 'aria-current="step"' : ""}>${index < current ? icon("check") : '<span class="step-dot"></span>'}${text}</div>`).join("")}</div>`;
}
function warningsPanel(run) {
  const messages = [...new Set([...(run.warnings || []), ...(run.events || [])])];
  if (!messages.length) return "";
  return `<details class="details-panel"><summary>Reporting warnings & provider activity (${messages.length})</summary><ul class="warning-list">${messages.map(text => `<li>${escapeHTML(text)}</li>`).join("")}</ul></details>`;
}
function pitchContent(run) {
  if (!run.pitches.some(pitch => pitch.id === state.pitch)) state.pitch = run.pitches[0]?.id;
  const pitch = run.pitches.find(item => item.id === state.pitch);
  if (!pitch) return "";
  const question = state.questions.has(questionKey(pitch)) ? state.questions.get(questionKey(pitch)) : pitch.question;
  return `<div class="pitch-layout"><section><div class="section-heading"><h2>The shortlist</h2><span class="tiny-label">${run.pitches.length} ${run.pitches.length === 1 ? "PITCH" : "PITCHES"}</span></div><div class="pitch-options">${run.pitches.map(item => `<button class="pitch-option ${item.id === pitch.id ? "selected" : ""}" data-action="pitch" data-pitch="${escapeHTML(item.id)}" aria-pressed="${item.id === pitch.id}"><span class="pitch-option-top"><span>${escapeHTML(domain(item.strongest_source))}</span><span class="radio-mark" aria-hidden="true"></span></span><h3>${escapeHTML(item.headline)}</h3><span class="pitch-reader">For ${escapeHTML(item.primary_reader)}</span>${item.id === pitch.id ? `<dl class="pitch-detail"><dt>What changed</dt><dd>${escapeHTML(item.what_changed)}</dd><dt>Why it matters in Kenya</dt><dd>${escapeHTML(item.why_kenya)}</dd><dt>Why now</dt><dd>${escapeHTML(item.timely_reason)}</dd><dt>Why this pitch ranks here</dt><dd>${escapeHTML(item.ranking_reason)}</dd></dl><div class="gap-note"><strong>The reporting gap</strong>${escapeHTML(item.reporting_gap)}</div>` : ""}</button>`).join("")}</div></section>
    <form class="angle-panel" id="angle-form"><div class="eyebrow">Your editorial decision</div><h2>What should this story answer?</h2><p>Keep the question tied to this development and one reader. Edit the proposed angle before reporting begins.</p><label class="field-label" for="approved-question">Reader’s question</label><textarea id="approved-question" name="question" maxlength="1000" required>${escapeHTML(question)}</textarea><p class="field-help">The approved question directs research, drafting and verification.</p><p class="quiet-copy">Strongest source: <a href="${escapeHTML(safeURL(pitch.strongest_source))}" target="_blank" rel="noopener noreferrer">${escapeHTML(domain(pitch.strongest_source))}</a></p><button class="button primary" type="submit" ${state.busy ? "disabled" : ""}>${icon("edit")}${state.busy ? "Starting reporting…" : "Approve & start reporting"}</button><button type="button" class="text-button dismiss-button" data-action="dismiss" ${state.busy ? "disabled" : ""}>Set this run aside</button></form></div>`;
}
function reportingContent(run) {
  const error = run.error || (run.status === "error" ? "Reporting stopped before finishing. Your approved question and sources remain saved." : "");
  return `${run.approved_question ? `<section class="approved-question"><div class="eyebrow">Approved reader question</div><h2>${escapeHTML(run.approved_question)}</h2></section>` : ""}
    ${error ? `<div class="message error-message" role="alert"><p>${escapeHTML(error)}</p>${run.can_resume ? `<button class="button" data-action="retry" ${state.busy ? "disabled" : ""}>${icon("refresh")} Retry saved work</button>` : ""}</div>` : ""}
    <section class="progress-panel"><div class="progress-heading">${run.active ? '<span class="working-indicator" aria-hidden="true"></span>' : icon("clock")}<h2>${escapeHTML(run.active ? run.stage || "Working on your story" : "Your work is saved")}</h2></div><p>${run.active ? "You can leave this page and return. Keep the server terminal running while reporting continues." : "Continue the saved reporting step without choosing the pitch again."}</p>
    ${run.can_resume && !error ? '<button class="button primary" data-action="retry">Continue reporting</button>' : ""}<div class="reporting-counts"><span><strong>${run.candidate_count}</strong>reports discovered</span><span><strong>${run.source_count}</strong>source pages opened</span><span><strong>${run.searches_used} / ${run.search_budget}</strong>follow-up searches</span></div></section>`;
}

function inlineMarkdown(text) {
  const fragment = document.createDocumentFragment();
  const pattern = /\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    fragment.append(document.createTextNode(text.slice(cursor, match.index)));
    if (match[1]) {
      const href = safeURL(match[2]);
      if (href !== "#") {
        const link = document.createElement("a"); link.href = href; link.textContent = match[1]; link.target = "_blank"; link.rel = "noopener noreferrer"; fragment.append(link);
      } else fragment.append(document.createTextNode(match[0]));
    } else { const node = document.createElement(match[3] ? "strong" : "code"); node.textContent = match[3] || match[4]; fragment.append(node); }
    cursor = match.index + match[0].length;
  }
  fragment.append(document.createTextNode(text.slice(cursor)));
  return fragment;
}
function renderMarkdown(target, markdown) {
  target.replaceChildren();
  let paragraph = [], list = null;
  const flush = () => { if (paragraph.length) { const p = document.createElement("p"); p.append(inlineMarkdown(paragraph.join(" "))); target.append(p); paragraph = []; } };
  for (const line of markdown.split(/\r?\n/)) {
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    const bullet = /^\s*[-*]\s+(.+)$/.exec(line);
    if (!line.trim()) { flush(); list = null; }
    else if (heading) { flush(); list = null; const node = document.createElement(`h${heading[1].length}`); node.append(inlineMarkdown(heading[2])); target.append(node); }
    else if (line.startsWith("> ")) { flush(); list = null; const node = document.createElement("blockquote"); node.append(inlineMarkdown(line.slice(2))); target.append(node); }
    else if (bullet) { flush(); if (!list) { list = document.createElement("ul"); target.append(list); } const item = document.createElement("li"); item.append(inlineMarkdown(bullet[1])); list.append(item); }
    else { list = null; paragraph.push(line); }
  }
  flush();
}
function reviewContent(run) {
  if (!run.documents.some(doc => doc.name === state.documentName)) state.documentName = run.documents[0]?.name;
  const doc = run.documents.find(item => item.name === state.documentName);
  const content = state.documents.get(docKey(doc.name)) ?? doc.content;
  const dirty = state.dirty.has(docKey(doc.name));
  return `<div class="review-layout"><section class="document-panel"><div class="document-tabs" aria-label="Reporting documents">${run.documents.map(item => `<button class="${doc.name === item.name ? "active" : ""}" data-action="document" data-name="${escapeHTML(item.name)}" aria-pressed="${doc.name === item.name}">${documentLabel(item.name)}</button>`).join("")}</div><div class="document-toolbar"><div class="editor-switch" aria-label="Document view"><button data-action="editor-mode" data-mode="preview" class="${state.editorMode === "preview" ? "active" : ""}" aria-pressed="${state.editorMode === "preview"}">Preview</button><button data-action="editor-mode" data-mode="markdown" class="${state.editorMode === "markdown" ? "active" : ""}" aria-pressed="${state.editorMode === "markdown"}">Edit Markdown</button></div><div class="document-tools"><a class="button small" data-action="download-document" href="/api/runs/${run.id}/files/${doc.name}" download>${icon("download")} Download</a><button id="save-document" class="button primary small" data-action="save-document" ${!dirty || state.busy ? "disabled" : ""}>${state.busy ? "Saving…" : "Save edits"}</button></div></div>
    ${state.editorMode === "markdown" ? `<textarea id="markdown-editor" class="markdown-editor" aria-label="Edit ${documentLabel(doc.name)}" spellcheck="true">${escapeHTML(content)}</textarea>` : '<article id="document-preview" class="document-preview"></article>'}<div class="editor-footer"><span id="document-save-state">${dirty ? "Unsaved edits" : doc.edited ? "Your edited copy is saved" : "Verified workflow output"} · <span id="word-count">${content.trim() ? content.trim().split(/\s+/).length : 0}</span> words</span><span>Edits are saved separately. Check any new claims.</span></div></section>
    <aside class="source-map"><div class="eyebrow">Behind the reporting</div><h2>Source map</h2><p>${run.evidence.length} material ${run.evidence.length === 1 ? "claim" : "claims"}. Open a claim to inspect its supporting passage.</p>${run.evidence.map(claim => `<details class="claim"><summary><span class="claim-id">${escapeHTML(claim.id)}</span><span>${escapeHTML(claim.publisher)}</span></summary><p>${escapeHTML(claim.text)}</p><span class="claim-kind">${run.verification.supported_claim_ids?.includes(claim.id) ? "Supported passage" : "Excluded from article"} · ${escapeHTML(claim.kind.replaceAll("_"," "))} · ${escapeHTML(claim.geographic_scope)}</span><blockquote>${escapeHTML(claim.passage)}</blockquote><a href="${escapeHTML(safeURL(claim.url))}" target="_blank" rel="noopener noreferrer">Read source at ${escapeHTML(domain(claim.url))}</a></details>`).join("") || '<p class="quiet-copy">No material claims could be verified from the available sources.</p>'}${run.reporting_tasks.length ? `<div class="source-map-tasks"><h3>For the editor</h3><ul>${run.reporting_tasks.map(task => `<li>${escapeHTML(task)}</li>`).join("")}</ul></div>` : ""}</aside></div>`;
}

function renderRun() {
  const run = state.current;
  const brief = run.verification.outcome === "reporting_brief";
  const title = run.documents.length ? brief ? "A question worth reporting further." : "Ready for your edit." : run.pending ? "Choose the story worth telling." : run.status === "no_pitches" ? "Nothing strong enough to pitch." : run.status === "dismissed" ? "This shortlist is set aside." : "Your story is taking shape.";
  main.innerHTML = `<div class="page-header"><div><div class="eyebrow">${run.mode === "offline" ? "Fictional sample" : "Live briefing"} · ${date(run.created_at)}</div><h1>${title}</h1><p class="page-description">${run.documents.length ? brief ? "The evidence does not yet support this angle. Use the brief to guide your next reporting." : "A sourced first draft, ready for your judgement and voice." : run.pending ? "Start with the strongest pitch, then make the reader’s question your own." : "Your question, sources and progress are saved in this workspace."}</p></div><div class="run-top-actions">${badge(run)}<button class="icon-button" data-action="refresh" aria-label="Refresh this run">${icon("refresh")}</button></div></div>${stepper(run)}${run.mode === "offline" ? '<div class="sample-banner">SAMPLE MATERIAL · This is a fictional demonstration, not real news or material for publication.</div>' : ""}
    ${run.documents.length ? reviewContent(run) : run.pending && !run.active ? pitchContent(run) : ["no_pitches","dismissed"].includes(run.status) ? `<section class="empty-state">${icon("source")}<h2>${run.status === "dismissed" ? "Space for a better story." : "A shortlist should earn its place."}</h2><p>${run.status === "dismissed" ? "The pitches remain in your history. Start a new briefing when you are ready to explore another development." : "The available reports were already covered or did not establish enough fresh evidence. You can try a wider date window or return when something new develops."}</p><button class="button primary" data-action="new">${icon("plus")} Start a new briefing</button></section>` : reportingContent(run)}${warningsPanel(run)}`;
  if (run.documents.length && state.editorMode === "preview") {
    const doc = run.documents.find(item => item.name === state.documentName);
    renderMarkdown(document.querySelector("#document-preview"), state.documents.get(docKey(doc.name)) ?? doc.content);
  }
}

function render() {
  updateNavigation();
  if (location.hash.startsWith("#run/")) { if (state.current) renderRun(); }
  else if (location.hash === "#runs") renderRuns();
  else if (location.hash === "#sources") renderSources();
  else renderDesk();
}
async function refreshRuns() { state.runs = (await api("/api/runs")).runs; updateNavigation(); }
const fingerprint = run => JSON.stringify([run.id, run.status, run.active, run.pending, run.stage, run.error, run.pitches.length, run.candidate_count, run.source_count, run.searches_used, run.events.length, run.documents.length]);
async function loadRun(id, initial = false) {
  const run = await api(`/api/runs/${id}`);
  if (location.hash !== `#run/${id}`) return;
  const changed = !state.current || fingerprint(run) !== fingerprint(state.current);
  state.current = run;
  if (initial || changed) { renderRun(); await refreshRuns(); }
  clearTimeout(state.poll);
  state.poll = setTimeout(() => loadRun(id).catch(error => { notify(error.message, true); }), run.active ? 1400 : 5000);
}
async function route() {
  clearTimeout(state.poll);
  document.querySelector("#sidebar").classList.remove("is-open");
  document.querySelector(".mobile-menu").setAttribute("aria-expanded", "false");
  updateNavigation();
  const match = /^#run\/([a-f0-9]{32})$/.exec(location.hash);
  if (match) {
    if (state.current?.id !== match[1]) { state.current = null; state.pitch = null; state.documentName = null; state.editorMode = "preview"; }
    main.innerHTML = '<div class="loading-page" aria-label="Loading briefing"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-panel"></div></div>';
    await loadRun(match[1], true);
  } else { await refreshRuns(); render(); }
  state.route = location.hash;
}
function go(hash) { if (location.hash === hash) route().catch(showError); else location.hash = hash; }
function showError(error) {
  notify(error.message, true);
  if (!state.settings || (location.hash.startsWith("#run/") && !state.current)) {
    main.innerHTML = `<section class="empty-state"><h1>The workspace could not load.</h1><p>${escapeHTML(error.message)}</p><button class="button" data-action="reload">Try again</button></section>`;
  }
}

document.addEventListener("click", async event => {
  const button = event.target.closest("[data-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.action;
  if (action === "download-document" && state.dirty.has(docKey(state.documentName))) {
    event.preventDefault(); notify("Save your edits before downloading the edited copy."); document.querySelector("#save-document")?.focus?.(); return;
  }
  if (state.busy && ["save-document", "retry", "dismiss"].includes(action)) return;
  let ownsBusy = false;
  try {
    if (action === "new") go("#desk");
    else if (action === "all-runs") go("#runs");
    else if (action === "open-run") go(`#run/${button.dataset.id}`);
    else if (action === "mode") { state.mode = button.dataset.mode; renderDesk(); document.querySelector('.mode-switch [aria-pressed="true"]')?.focus?.(); }
    else if (action === "filter") { state.filter = button.dataset.filter; renderRuns(); }
    else if (action === "pitch") { state.pitch = button.dataset.pitch; renderRun(); document.querySelector('.pitch-option.selected')?.focus?.({ preventScroll: true }); }
    else if (action === "refresh") { await loadRun(state.current.id, true); notify("Run refreshed."); }
    else if (action === "document") { state.documentName = button.dataset.name; renderRun(); }
    else if (action === "editor-mode") { state.editorMode = button.dataset.mode; renderRun(); document.querySelector(state.editorMode === "markdown" ? '#markdown-editor' : '.editor-switch .active')?.focus?.({ preventScroll: true }); }
    else if (action === "reload") location.reload();
    else if (action === "menu") { const open = document.querySelector("#sidebar").classList.toggle("is-open"); button.setAttribute("aria-expanded", String(open)); }
    else if (action === "save-document") {
      const run = state.current;
      const name = state.documentName;
      const key = `${run.id}/${name}`;
      const content = state.documents.get(key);
      ownsBusy = true;
      state.busy = true; renderRun();
      await api(`/api/runs/${run.id}/documents/${name}`, { method: "PUT", body: JSON.stringify({ content }) });
      state.dirty.delete(key);
      const doc = run.documents.find(item => item.name === name); doc.content = content; doc.edited = true;
      notify("Your edited copy is saved.");
    } else if (action === "retry" || action === "dismiss") {
      if (action === "dismiss" && !confirm("Set this run aside? The shortlist will remain in your saved history.")) return;
      const id = state.current.id;
      ownsBusy = true;
      state.busy = true;
      await api(`/api/runs/${id}/resume`, { method: "POST", body: JSON.stringify({ action: action === "retry" ? "resume" : "dismiss" }) });
      await loadRun(id, true);
    }
  } catch (error) { showError(error); }
  finally { if (ownsBusy) { state.busy = false; render(); } }
});

document.addEventListener("input", event => {
  if (event.target.id === "approved-question") state.questions.set(`${state.current.id}/${state.pitch}`, event.target.value);
  if (event.target.id === "run-search") { state.search = event.target.value; document.querySelector("#history-list").innerHTML = runRows(filteredRuns()); }
  if (event.target.id === "markdown-editor") {
    const key = docKey(state.documentName); state.documents.set(key, event.target.value); state.dirty.add(key);
    document.querySelector("#save-document").disabled = false;
    document.querySelector("#document-save-state").textContent = `Unsaved edits · ${event.target.value.trim() ? event.target.value.trim().split(/\s+/).length : 0} words`;
  }
});
document.addEventListener("change", event => {
  if (event.target.id === "recent-days") state.days = Number(event.target.value);
  if (event.target.id === "search-budget") state.budget = Number(event.target.value);
});
document.addEventListener("submit", async event => {
  if (!["discovery-form","angle-form"].includes(event.target.id)) return;
  event.preventDefault();
  if (state.busy) return;
  try {
    state.busy = true;
    if (event.target.id === "discovery-form") {
      state.days = Number(document.querySelector("#recent-days").value); state.budget = Number(document.querySelector("#search-budget").value);
      renderDesk();
      const result = await api("/api/runs", { method: "POST", body: JSON.stringify({ mode: state.mode, recent_days: state.days, search_budget: state.budget }) });
      go(`#run/${result.id}`);
    } else {
      const question = document.querySelector("#approved-question").value.trim();
      if (!question) throw new Error("Add a reader question before starting reporting.");
      const id = state.current.id;
      renderRun();
      await api(`/api/runs/${id}/resume`, { method: "POST", body: JSON.stringify({ action: "select", pitch_id: state.pitch, question }) });
      await loadRun(id, true);
    }
  } catch (error) { showError(error); }
  finally { state.busy = false; if (state.settings) render(); }
});
window.addEventListener("beforeunload", event => { if (state.dirty.size) { event.preventDefault(); event.returnValue = ""; } });
window.addEventListener("hashchange", () => route().catch(showError));
document.querySelector("#today").textContent = new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short" }).format(new Date());
Promise.all([api("/api/settings"), api("/api/runs")]).then(([settings, runs]) => { state.settings = settings; state.runs = runs.runs; return route(); }).catch(showError);
