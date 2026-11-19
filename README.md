# Deluxe Studios editorial assistant

A small Python/LangGraph CLI for discovering emerging-technology stories, approving a reader question, researching it and exporting a sourced first draft. It serves Kenyan SME owners, brand builders, vibe coders and tech practitioners, using Kenyan and international reporting. Publication stays with the editor.

## Setup

Requires Python 3.11+ and network access to install LangGraph:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -v
```

The `deluxe` entry point and `python -m deluxe` are equivalent. Commands below assume the virtual environment is active and the repository is your current directory.

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

The real model adapter uses the OpenAI Chat Completions JSON API; follow-up searches use Tavily. Pages are fetched separately: search snippets never become claim evidence. Feed/page retrieval does not require credentials.

```bash
cp .env.example .env
# Edit .env to supply your keys, then export it:
set -a
source .env
set +a

python -m deluxe discover --search-budget 3 --recent-days 7
python -m deluxe list-runs
python -m deluxe resume RUN_ID --select 1 --question 'Your specific reader question?'
```

Required: `OPENAI_API_KEY`, `TAVILY_API_KEY`. Optional: `OPENAI_MODEL` (default `gpt-4.1-mini`), `OPENAI_BASE_URL` (default `https://api.openai.com/v1`), `DELUXE_HOME` (default `.deluxe`). `.env` is **not automatically loaded**. Keys are not saved in checkpoints. Both credentials are checked before live discovery, including when the search budget is zero. Inspecting or dismissing an already saved live shortlist does not need credentials. Actual live model calls incur provider charges.

The search budget is **0–10 search requests**, not tokens or money. The planner chooses each next query from the question, fetched sources and earlier searches. Each request returns at most four results; at most 16 source pages are retained. Failed requests consume budget and are reported. Model calls for grouping, planning, extraction, drafting and verification are additional. A zero search budget still fetches the original discovery sources.

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
```

The standard-library test suite covers both fixture outcomes, RSS/Atom/date handling, grouped syndication, duplicate ledgers, budget enforcement, unavailable sources/search, missing credentials, fabricated supporting passages, verification rejection and invalid editorial choices. Real LangGraph tests launch separate CLI processes to prove shortlist persistence, revised-question persistence, approval recovery after a research failure, dismissal and duplicate detection after restart. These integration tests are explicitly skipped if LangGraph is absent; install dependencies to run the complete suite.

Live API compatibility, provider permissions, model quality on actual news and full feed/page availability require live credentials and network access. Offline tests do not claim to verify those.
