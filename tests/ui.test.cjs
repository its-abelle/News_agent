// Dependency-free controller tests. HTTP/graph integration lives in test_web.py.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class Element {
  constructor(tag = "div") { this.tagName = tag.toUpperCase(); this.children = []; this.innerHTML = ""; this.textContent = ""; this.content = "test-session"; this.value = ""; this.disabled = false; this.attributes = {}; this.dataset = {}; this.classList = { toggle() {}, add() {}, remove() {} }; }
  append(...nodes) { for (const node of nodes) this.children.push(...(node.tagName === "FRAGMENT" ? node.children : [node])); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
}
function setup() {
  const elements = new Map();
  const listeners = new Map();
  const calls = [];
  const query = selector => { if (!elements.has(selector)) elements.set(selector, new Element()); return elements.get(selector); };
  const context = vm.createContext({
    document: { querySelector: query, querySelectorAll: () => [], createElement: name => new Element(name),
      createTextNode: text => ({ tagName: "TEXT", textContent: text, children: [] }), createDocumentFragment: () => new Element("fragment"),
      addEventListener: (event, callback) => listeners.set(event, callback) },
    window: { addEventListener() {} }, location: { hash: "#desk" }, confirm: () => true,
    setTimeout: () => 0, clearTimeout() {}, URL, Intl, Date, console,
    fetch: () => new Promise(() => {}),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../deluxe/ui/app.js"), "utf8"), context);
  vm.runInContext('state.settings = {groq: true, qwen: false, search: true, sources: []};', context);
  const run = { id: "a".repeat(32), mode: "offline", created_at: "2026-11-21T12:00:00Z", status: "awaiting_editor",
    active: false, pending: true, can_resume: false, stage: "", error: "", events: [], warnings: [],
    pitches: [{ id: "1", headline: "An AI storefront launch", primary_reader: "Kenyan clothing brand owner", what_changed: "A new builder",
      why_kenya: "Product page workflow", timely_reason: "New release", ranking_reason: "Specific evidence", reporting_gap: "Payouts undocumented",
      question: "What does this builder generate?", strongest_source: "https://example.com/launch" }],
    selected_pitch: null, approved_question: "", source_count: 0, candidate_count: 2, searches_used: 0, search_budget: 3,
    evidence: [], reporting_tasks: [], verification: {}, documents: [], };
  function installRun(value = run) { context.testRun = value; context.location.hash = `#run/${value.id}`; vm.runInContext("state.current = testRun; state.pitch = '1';", context); }
  function mockAPI(callback) {
    context.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => callback(url, options) }; };
  }
  return { context, run, query, calls, listeners, installRun, mockAPI, evaluate: code => vm.runInContext(code, context) };
}
function descendants(element) { return [element, ...element.children.flatMap(descendants)]; }

test("live discovery requires loaded keys while fictional mode stays available", () => {
  const ui = setup();
  ui.evaluate("state.settings.groq = false; state.settings.search = false; renderDesk();");
  assert.match(ui.query("#main").innerHTML, /Load your model and Tavily keys/);
  assert.match(ui.query("#main").innerHTML, /discovery-submit[^>]*disabled/);
  ui.evaluate("state.mode = 'offline'; renderDesk();");
  assert.match(ui.query("#main").innerHTML, /No API calls or credentials needed/);
  assert.doesNotMatch(ui.query("#main").innerHTML, /discovery-submit[^>]*disabled/);
});

test("retrieved pitch text is escaped rather than interpreted as HTML", () => {
  const ui = setup();
  ui.run.pitches[0].headline = '<img src=x onerror="alert(1)">';
  ui.run.pitches[0].question = "</textarea><script>evil()</script>";
  ui.installRun(); ui.evaluate("renderRun()");
  const markup = ui.query("#main").innerHTML;
  assert.doesNotMatch(markup, /<img src=x|<script>evil/);
  assert.match(markup, /&lt;img/);
  assert.match(markup, /&lt;\/textarea&gt;/);
});

test("approval sends the selected pitch and revised question", async () => {
  const ui = setup(); ui.installRun();
  const question = "Can this Kenyan brand receive payouts?";
  ui.query("#approved-question").value = question;
  ui.mockAPI(url => url.endsWith("/resume") ? { id: ui.run.id } : url === "/api/runs" ? { runs: [] } : { ...ui.run, active: true, pending: false, approved_question: question });
  await ui.listeners.get("submit")({ target: { id: "angle-form" }, preventDefault() {} });
  const post = ui.calls.find(call => call.options.method === "POST");
  assert.deepEqual(JSON.parse(post.options.body), { action: "select", pitch_id: "1", question });
  assert.equal(post.options.headers["X-News-Agent-Token"], "test-session");
});

test("retry continues saved work without resending a selection", async () => {
  const ui = setup(); ui.installRun({ ...ui.run, pending: false, status: "error", can_resume: true });
  ui.mockAPI(url => url.endsWith("/resume") ? { id: ui.run.id } : url === "/api/runs" ? { runs: [] } : { ...ui.run, active: true });
  await ui.listeners.get("click")({ target: { closest: () => ({ dataset: { action: "retry" }, disabled: false }) } });
  const post = ui.calls.find(call => call.options.method === "POST");
  assert.deepEqual(JSON.parse(post.options.body), { action: "resume" });
});

test("Markdown preview keeps raw HTML inert and rejects script links", () => {
  const ui = setup(); const target = new Element();
  ui.context.target = target;
  ui.evaluate('renderMarkdown(target, "# Draft\\n\\n<script>evil()</script> [bad](javascript:evil) [source](https://example.com/report)")');
  const nodes = descendants(target);
  assert.equal(nodes.filter(node => node.tagName === "SCRIPT").length, 0);
  const links = nodes.filter(node => node.tagName === "A");
  assert.equal(links.length, 1);
  assert.equal(links[0].href, "https://example.com/report");
  assert.match(nodes.map(node => node.textContent).join(" "), /<script>evil/);
});

test("editing and saving sends the current Markdown and clears unsaved state", async () => {
  const ui = setup();
  ui.installRun({ ...ui.run, status: "complete", pending: false, documents: [{ name: "article.md", content: "# Original", edited: false }] });
  ui.evaluate("state.documentName = 'article.md'; state.editorMode = 'markdown';");
  const content = "# My edit\n\nA sourced paragraph.";
  ui.listeners.get("input")({ target: { id: "markdown-editor", value: content } });
  assert.equal(ui.evaluate("state.dirty.size"), 1);
  assert.equal(ui.query("#save-document").disabled, false);
  ui.mockAPI(() => ({ saved: true }));
  await ui.listeners.get("click")({ target: { closest: () => ({ dataset: { action: "save-document" }, disabled: false }) } });
  assert.deepEqual(JSON.parse(ui.calls[0].options.body), { content });
  assert.equal(ui.evaluate("state.dirty.size"), 0);
  assert.equal(ui.evaluate("state.current.documents[0].content"), content);
});
