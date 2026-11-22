# News Agent

A local editorial workspace and Python/LangGraph CLI for Deluxe Studios: discover emerging-technology stories, approve a reader question, research it and edit a sourced first draft. It serves Kenyan SME owners, brand builders, vibe coders and tech practitioners, using Kenyan and international reporting. Publication stays with the editor.

## Setup

Requires Python 3.11+ and network access to install LangGraph:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -v
```

The `news-agent`, `deluxe` and `python -m deluxe` entry points are equivalent. The Python package name remains `deluxe` for compatibility with existing runs. Commands below assume the virtual environment is active and the repository is your current directory.

## Web workspace

Start the dark News Agent workspace with the same storage directory you used for the CLI:

```bash
cd ~/news_agent
source .venv/bin/activate
python -m pip install -e .
set -a
source .env
set +a
python -m deluxe --home .deluxe/live-test serve --port 8765
```

Open **http://127.0.0.1:8765** in your browser and keep the terminal running. No Node installation, frontend build or extra Python web dependency is needed to use the UI. If that port is busy, choose another with `--port 8766`. After reinstalling the package, `news-agent --home .deluxe/live-test serve` is also available.

The workspace includes:

- **Editorial desk:** start a live briefing or explicitly choose fictional sample material; configure the look-back window and follow-up search budget.
- **Saved runs:** open existing CLI runs, return to an interrupted shortlist, or retry failed reporting without repeating editorial approval.
- **Choose an angle:** inspect the pitch, Kenyan relevance, strongest source and reporting gap; edit the question before approving it.
- **Reporting progress:** work runs in the background, so navigation and page reloads do not cancel it. One UI reporting job runs at a time to limit concurrent provider traffic. Queued jobs and concurrent duplicate actions are handled explicitly. Keep one active process per run; do not also resume the same run from the CLI while the UI is reporting it.
- **Review:** read the article or reporting brief, inspect claim passages and attribution, switch to Markdown editing, save and download.
- **Sources & connections:** inspect the bundled source list and whether provider keys are loaded. Credentials stay on the server; “key loaded” is not a claim that an API call succeeded. The UI does not edit keys or source configuration.

Edits are saved beside the original as `article-edited.md`, `reporting-notes-edited.md` or `reporting-brief-edited.md`. The workflow's verified original and audit snapshot remain unchanged. Download returns the saved edited copy when one exists. Save edits before downloading; edits do not automatically rerun verification, and new claims need editorial checking. Unsaved text is kept while navigating this browser tab, but closing/reloading the tab can lose it.

Closing the browser does not stop reporting. Stopping the server ends the UI; existing graph checkpoints and saved documents remain available after restarting. A clean Ctrl+C shutdown waits for active work to finish. After an unexpected shutdown, reopen a saved run and use **Continue reporting** to resume a saved step. A run interrupted before its very first checkpoint must be started again.

The server binds only to `127.0.0.1`. Request-origin, host and session-token checks protect local actions, and source Markdown is rendered without executing HTML. This is a single-user local app; there is no public hosting, login or multi-user access control. Do not expose this server to the internet.

To try the UI without credentials, start with a separate sample workspace:

```bash
python -m deluxe --home .deluxe/ui-demo serve
```

Choose **Fictional sample**, then **Find stories**. Approving the default question produces an article; choosing the Kenyan-payout question produces a reporting brief. Duplicate protection also applies to sample stories: use a different `--home` if you want a fresh run of the same fictional event with another angle.

## Offline demonstration

No credentials or network calls are used. All output is labelled **SAMPLE MATERIAL — FICTIONAL**. The fictional LoomCart announcement establishes storefront generation and editable product descriptions; it supplies no evidence of Kenyan merchant payouts. Offline adapters implement the same discovery, model, search and page interfaces and traverse the same graph and verification/export stages as live mode. They are deliberately deterministic and support the default generation question plus two simple equivalent questions; arbitrary unsupported questions return a brief.

```bash
python -m deluxe --home .deluxe/demo-article discover --offline
python -m deluxe --home .deluxe/demo-article list-runs
```

Copy the exact continuation command printed by discovery, replacing `RUN_ID` below with its saved ID:

```bash
# Safe to close the terminal and run these commands in a new session.
python -m deluxe --home .deluxe/demo-article resume RUN_ID
python -m deluxe --home .deluxe/demo-article resume RUN_ID --select 1
```

That approves the default question about what the builder generates. It exports `article.md` and `reporting-notes.md`, including attributed vendor claims with clickable references.

Use a separate home for the second demonstration so the duplicate ledger does not suppress the same fictional launch:

```bash
python -m deluxe --home .deluxe/demo-payout discover --offline
python -m deluxe --home .deluxe/demo-payout resume RUN_ID --select 1 \
  --question 'Can a Kenyan clothing brand receive payment through this storefront?'
```

This exports **only `reporting-brief.md`**, with missing merchant-country documentation, questions for the vendor and a suggested checkout/settlement test. It does not claim Kenyan availability or M-Pesa support.

To dismiss a paused run:

```bash
python -m deluxe --home .deluxe/demo-payout resume RUN_ID --dismiss
```

Discovery in the same home suppresses events already shortlisted, even if dismissed. Offline and live duplicate ledgers are separate. Inspect or resume existing runs instead of rediscovering the same story. A completed run is immutable through the CLI; use a new home if you deliberately want to experiment with another angle on the same event.

## Live mode

The real model adapter calls **Groq first**, then **Qwen through Alibaba Cloud Model Studio/DashScope** if Groq fails. Groq is the hosted AI API at groq.com, not the ngrok tunnelling service. No OpenAI API key or OpenAI Python package is required. Both adapters request JSON through compatible chat-completions interfaces; the Qwen adapter also disables thinking. Follow-up searches use Tavily. Pages are fetched separately: search snippets never become claim evidence. Feed/page retrieval does not require credentials.

```bash
# Only create .env if it does not already exist:
test -f .env || cp .env.example .env
# Edit .env: set GROQ_API_KEY and TAVILY_API_KEY.
# Leave QWEN_API_KEY blank until you have a fallback key, then export:
set -a
source .env
set +a

python -m deluxe discover --search-budget 3 --recent-days 7
python -m deluxe list-runs
python -m deluxe resume RUN_ID --select 1 --question 'Your specific reader question?'
```

For the primary route, set `GROQ_API_KEY` and `TAVILY_API_KEY`. Obtain a Groq key from [GroqCloud API Keys](https://console.groq.com/keys). `GROQ_MODEL` defaults to `openai/gpt-oss-20b`; `GROQ_BASE_URL` defaults to `https://api.groq.com/openai/v1`. The model name identifies the open-weight model served by Groq; it uses your Groq key, not an OpenAI key. See [Groq's supported models](https://console.groq.com/docs/models) and [JSON output documentation](https://console.groq.com/docs/structured-outputs). Free-tier availability and limits depend on your account and current provider terms; the application does not guarantee free inference.

The **optional fallback** uses `QWEN_API_KEY` (or `DASHSCOPE_API_KEY`); `QWEN_API_KEY` takes precedence if both are set. `QWEN_MODEL` defaults to `qwen-plus`; `QWEN_BASE_URL` defaults to `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`. Obtain the key through [Alibaba Cloud Model Studio's API Key page](https://www.alibabacloud.com/help/en/model-studio/get-api-key): select the intended region, create an API key, and copy the key and API host into your local `.env`. Use a Qwen model supporting JSON output in non-thinking mode. Qwen fallback calls may incur charges. Neither adapter reads `OPENAI_API_KEY`. `DELUXE_HOME` still defaults to `.deluxe`.

Set `QWEN_BASE_URL` to the compatible-mode base URL for your key's region and workspace, as shown in your Alibaba Model Studio console. For example, Beijing uses `https://dashscope.aliyuncs.com/compatible-mode/v1`; some Singapore workspaces use `https://YOUR_WORKSPACE_ID.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`. Do not include `/chat/completions`; the adapter appends it. See Alibaba's [Qwen JSON output documentation](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output) for supported models and regional examples. Account/region access must still be verified with your real key.

Every model call tries Groq first. A missing Groq key, invalid provider configuration, request failure (including authentication, rate limits, timeouts and server errors), or malformed/non-object JSON response triggers one Qwen attempt with the same task, approved question and source data. Fallback use emits a terminal warning, including a safe diagnostic such as HTTP 429 (rate/quota limit), HTTP 401 (authentication) or invalid JSON. When both fail, both diagnostics are reported without raw provider response bodies. Each subsequent call tries Groq first again. There is no retry loop or circuit breaker. A syntactically valid JSON object that fails editorial checks is handled by the normal reporting/verification stages; it does not automatically trigger a second provider call.

A missing Qwen key **does not block working Groq**. If Groq fails without a usable Qwen configuration, the command reports an error and retains the checkpoint. If both providers fail, it reports that both failed; restore access and `resume RUN_ID` to retry. If Groq is not configured but Qwen is, the Qwen-only route remains usable with a fallback warning. Fallback never selects fixture data. The terminal warnings identify providers but do not expose provider error bodies or keys.

`.env` is **not automatically loaded**. Keys are not saved in checkpoints. At least one model key and the Tavily search key must be present before live discovery, even when the search budget is zero. Provider settings are validated when that provider is attempted. Inspecting or dismissing an already saved live shortlist needs no credentials. Actual live calls incur provider charges; fallback can add an extra model request per failed primary call. Tavily CLI login is separate from this Python application's `TAVILY_API_KEY` environment setting.

The search budget is **0–10 search requests**, not tokens or money. The planner chooses each next query from the question, fetched sources and earlier searches. Each request returns at most four results; at most 16 source pages are retained. Failed requests consume budget and are reported. Model calls for grouping, planning, extraction, drafting and verification are additional. A zero search budget still fetches the original discovery sources.

Planning, extraction and verification use bounded source excerpts instead of sending every full page in a single request. `DELUXE_SOURCE_CONTEXT_CHARS` defaults to **12000 total source-text characters per request** (range 2000–48000). This is a character budget, not a token or monetary limit; prompts, metadata, evidence and draft text add to the request. Excerpts retain opening context, question-matching blocks and closing qualifiers, while full pages remain unchanged in checkpoints and `audit.json`. When pages are excerpted, reporting notes explicitly flag omitted sections for editor review. An omitted passage is not evidence that a capability is absent. Excerpt selection can miss important context; narrow the question and review source pages before publication.

### Sources

The bundled [source list](deluxe/sources.json) contains Techweez (Kenya), TechCabal (Africa), TechCrunch and The Verge (international). Use your own list with:

```bash
python -m deluxe discover --feeds my-feeds.json
```

```json
[
  {"publisher": "Techweez", "url": "https://techweez.com/feed/", "region": "Kenya"},
  {"publisher": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "region": "International"}
]
```

Feed verification during implementation was constrained: the web reader identified RSS/XML responses for TechCrunch and The Verge, but could not parse their bodies; it could not retrieve the Kenyan/African feed bodies. Shell networking was blocked. These are starter endpoints, **not a claim that all feeds were successfully parsed live**. Every discovery run validates each feed as RSS/Atom and reports inaccessible, malformed or empty feeds. Partial outages allow remaining feeds to proceed; no usable evidence returns no pitches. No fixture data is ever substituted into live runs.

## Persistence and outputs

Under `--home` (or `DELUXE_HOME`):

```text
editorial.sqlite           run index and cross-run event/URL ledger
checkpoints.sqlite         LangGraph state, parent checkpoints and pending writes
outputs/<run-id>/
  article.md               supported story only
  reporting-notes.md       supported story's source map, uncertainties and tasks
  reporting-brief.md       insufficient evidence only
  audit.json               source texts, evidence, question and verification snapshot
```

Run IDs are generated UUIDs and become LangGraph `thread_id`s. The graph pauses using `interrupt()` and resumes with `Command(resume=...)`. Approved questions and editor choices are checkpointed before research. A synchronous SQLite saver implements LangGraph's checkpoint API, stores full channel snapshots with its typed serializer, and commits pending writes separately. It supports this CLI's ordinary state channels; async graphs and delta channels are outside version one's scope. Use one active process per run. Do not edit checkpoint databases or open databases from untrusted sources.

After a transient error, restore credentials/connectivity and run `resume RUN_ID` to retry from the saved graph step. If approval itself was not checkpointed, the saved shortlist remains paused and displays the selection command again. A crash before the very first checkpoint requires a new discovery run. Page/search failures are recorded as gaps rather than treated as positive evidence. Model/API failures stop the run with an explicit error.

After a failure **following selection**, retry with no selection flags:

```bash
python -m deluxe --home .deluxe/live-test resume RUN_ID
```

Do not repeat `--select` or `--question`: the original choice and question are already saved. The CLI prints the exact continuation command when work fails. A generic question such as "How can SMEs maximise profits with technology?" is much broader than a news-event angle and may correctly result in a reporting brief. Prefer a specific reader, development and cost/revenue question when approving a new pitch.

## Editorial and verification rules

- Discovery captures headline, publisher, canonical URL, publication date and event date. Unknown dates stay `null`. Tracking parameters are removed; fetched pages honour canonical links. An Atom `updated` date is not silently substituted for publication date. Undated reports are retained for inspection but cannot establish recency.
- Grouping uses model-assisted event identification and a persistent URL/event-key ledger, including previous story context. Recent publication alone does not establish a fresh event: a verbatim freshness passage and an explicit fresh-development judgement are required. Old known event dates are excluded. Up to three pitches are returned, with one reader/question, a concrete Kenyan decision, timeliness, strongest source, gap and ranking rationale. Semantic event matching can miss paraphrases; an editor should still check overlap.
- Research follows the approved question and seeks original sources and appropriate independent evidence. Material claims store source ID, URL, publisher, exact supporting passage, attribution, evidence type and geographic scope. Vendor assertions remain attributed. Interview and test needs become specific reporting tasks.
- Retrieved text is passed as untrusted data under a fixed system instruction. It has no direct tool access. HTTP fetches reject private/reserved addresses and non-HTTP URLs and impose time/size limits. Prompt injection remains a model risk; the editor must review outputs.
- Passage matching rejects fabricated citations before drafting. A separate model verification step checks semantic support, attribution, every paragraph, the title and geographic scope. Unsupported paragraphs are removed. Missing central evidence, a missing verdict or no supported draft produces a brief. The verifier is model-assisted rather than a proof of truth; no article is published automatically.
- Version one fetches static HTML only. Paywalls, login pages, JavaScript-only pages and inaccessible documentation may require manual reporting. It performs no interviews, product tests or transactions.

## Tests

```bash
python -m unittest discover -v
# Optional frontend controller tests; requires Node.js 20+ but no npm install:
node tests/ui.test.cjs
```

The standard-library test suite covers both fixture outcomes, RSS/Atom/date handling, grouped syndication, duplicate ledgers, budget enforcement, unavailable sources/search, missing credentials, fabricated supporting passages, verification rejection and invalid editorial choices. Model-routing tests cover Groq success without Qwen credentials, provider request formats and separate keys, HTTP/JSON failure fallback, missing keys, both providers failing, unchanged task data and returning to Groq on the next call. Real LangGraph tests launch separate CLI processes to prove shortlist persistence, revised-question persistence, approval recovery after a research failure, dismissal and duplicate detection after restart. These integration tests are explicitly skipped if LangGraph is absent; install dependencies to run the complete suite.

Live API compatibility, provider permissions, model quality on actual news and full feed/page availability require live credentials and network access. Offline tests do not claim to verify those.

Web tests exercise the HTTP application dispatcher and real background LangGraph jobs without binding a socket. They cover both sample outcomes, authentication/configuration separation, origin/host/token checks, traversal prevention, saved-run restart, retries, duplicate actions, document editing and downloads. Dependency-free JavaScript tests cover view logic, question submission, retry payloads, source HTML escaping and Markdown editing. A browser visual pass still needs an environment that permits the local server and browser processes.

## Remaining work and current limitations

- **Not live-validated:** a full Groq/Qwen + Tavily + RSS run with real credentials; full successful parsing of the starter feeds. Adapter tests use mocked HTTP and the offline acceptance scenarios use deterministic sample responses.
- **Partial event/date handling:** feeds preserve supplied publication dates; live event dates are proposed during pitch grouping. There is no dedicated page-metadata event-date extractor or field-level provenance for event dates. Unknown dates remain empty.
- **Partial duplicate handling:** canonical URLs and model-proposed event keys are stored, but no content-fingerprint/syndication detector is implemented. Model-assisted matching can miss paraphrases, and the URL ledger can suppress a fresh development posted at an already-seen URL.
- **Verification removes rather than rewrites:** the verifier checks semantic support and scope; unsupported paragraphs are dropped or a brief is produced. There is no automated revision-and-reverification loop. Independent-source discovery is guided by prompts rather than a mandatory corroboration policy.
- **No automatic API retries/backoff or token-cost accounting:** failed graph steps can be resumed manually. The budget limits search calls only.
- **No browser-rendered source retrieval, interview execution or hands-on product testing:** inaccessible pages and required human reporting become explicit gaps/tasks. Scheduling, public hosting, multi-user access and publication integrations remain outside this local version.
