import argparse
import json
import os
import shlex
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .adapters import AdapterError, LiveDiscovery, LivePages, LiveSearch, live_model
from .fixture import FixtureDiscovery, FixtureModel, FixturePages, FixtureSearch
from .graph import graph_config, is_interrupted, open_graph
from .storage import Store
from .workflow import EditorialWorkflow


def resume_command(home, run_id):
    return f"python -m deluxe --home {shlex.quote(str(home.resolve()))} resume {shlex.quote(run_id)}"


def runtime(store, mode, config):
    if mode == "offline":
        return EditorialWorkflow(store, FixtureDiscovery(), FixtureSearch(), FixturePages(), FixtureModel())
    # A working primary needs no fallback key. No implicit offline fixture fallback.
    model, search = live_model(), LiveSearch()
    return EditorialWorkflow(store, LiveDiscovery(config["feeds"]), search, LivePages(), model)


def parser():
    p = argparse.ArgumentParser(prog="deluxe", description="Deluxe Studios editorial assistant")
    p.add_argument("--home", type=Path, default=Path(os.environ.get("DELUXE_HOME", ".deluxe")),
                   help="SQLite databases and outputs directory (default: .deluxe)")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover", help="Find and save up to three pitches, then pause")
    d.add_argument("--offline", action="store_true", help="Explicit fictional sample workflow; no network or credentials")
    d.add_argument("--feeds", type=Path, help="JSON source list; defaults to bundled starter feeds")
    d.add_argument("--search-budget", type=int, choices=range(0, 11), default=3, metavar="0..10")
    d.add_argument("--recent-days", type=int, choices=range(1, 31), default=7, metavar="1..30")
    sub.add_parser("list-runs", help="Show persisted run IDs, modes and status")
    r = sub.add_parser("resume", help="Inspect or continue an existing run")
    r.add_argument("run_id")
    action = r.add_mutually_exclusive_group()
    action.add_argument("--select", metavar="PITCH_ID")
    action.add_argument("--dismiss", action="store_true")
    r.add_argument("--question", help="Revised reader question, used with --select")
    return p


def show(state, home, interrupted=False):
    print(f"Run: {state['run_id']} [{state['mode']}] — {state['status']}")
    if state["mode"] == "offline":
        print("SAMPLE MATERIAL — FICTIONAL. Not for publication.")
    for error in state.get("errors", []):
        print(f"Warning: {error}", file=sys.stderr)
    for pitch in state.get("pitches", []):
        print(f"\n{pitch['id']}. {pitch['headline']}")
        for key in ("primary_reader", "what_changed", "why_kenya", "question", "timely_reason",
                    "strongest_source", "reporting_gap", "ranking_reason"):
            print(f"   {key.replace('_', ' ').capitalize()}: {pitch[key]}")
    if state.get("approved_question"):
        print(f"\nApproved question: {state['approved_question']}")
    if interrupted:
        prefix = resume_command(home, state["run_id"])
        print(f"\nPaused for the editor. Continue with:\n{prefix} --select 1")
        print(f"Revise the angle:\n{prefix} --select 1 --question 'Your reader question here?'")
        print(f"Dismiss:\n{prefix} --dismiss")
    elif state.get("status") == "no_pitches":
        print("No sufficiently fresh, new, evidenced pitches. See warnings above and previous runs.")
    for output in state.get("outputs", []):
        print(f"Saved: {output}")


def run(args, store):
    if args.command == "list-runs":
        for row in store.list_runs():
            print(f"{row['id']}  {row['mode']:7}  {row['status']:16}  {row['created_at']}")
        return
    if args.command == "discover":
        feed_file = args.feeds or Path(__file__).with_name("sources.json")
        feeds = json.loads(feed_file.read_text(encoding="utf-8"))
        if not isinstance(feeds, list) or any(not isinstance(f, dict) or not f.get("url") or not f.get("publisher") for f in feeds):
            raise ValueError("Feeds JSON must be a list of objects containing publisher and url")
        config = {"feeds": feeds, "recent_days": args.recent_days, "search_budget": args.search_budget}
        mode = "offline" if args.offline else "live"
        workflow = runtime(store, mode, config)
        run_id = uuid4().hex
        initial = {"run_id": run_id, "mode": mode, "config": config,
                   "now": datetime.now(timezone.utc).isoformat(), "research_budget": args.search_budget,
                   "candidates": [], "pitches": [], "editor_decision": {}, "approved_question": "",
                   "evidence": [], "sources": [], "searches_used": 0, "search_log": [],
                   "draft": {}, "verification": {}, "reporting_tasks": [], "errors": [], "outputs": [],
                   "status": "starting"}
        with open_graph(workflow, store.home) as graph:
            store.create(run_id, mode, config)
            print(f"Created run: {run_id}", flush=True)
            try:
                graph.invoke(initial, graph_config(run_id))
            except Exception:
                store.status(run_id, "error")
                print(f"Run saved. Retry: {resume_command(store.home, run_id)}", file=sys.stderr)
                raise
            snapshot = graph.get_state(graph_config(run_id))
            store.status(run_id, snapshot.values["status"])
            show(snapshot.values, store.home, is_interrupted(snapshot))
        return

    if args.question is not None and not args.select:
        raise ValueError("--question requires --select PITCH_ID")
    row = store.get(args.run_id)
    config = json.loads(row["config"])
    # Inspecting a saved live shortlist does not require live credentials.
    workflow = (EditorialWorkflow(store, None, None, None, None))
    with open_graph(workflow, store.home) as graph:
        snapshot = graph.get_state(graph_config(args.run_id))
        if not snapshot.values:
            raise ValueError("Run has no checkpoint; start a new discovery run")
        pending = is_interrupted(snapshot)
        if not args.select and not args.dismiss and (pending or not snapshot.next):
            store.status(args.run_id, snapshot.values["status"])
            show(snapshot.values, store.home, pending)
            return
        if (args.select or args.dismiss) and not pending:
            verb = "Retry the saved work" if snapshot.next else "Inspect the saved outcome"
            raise ValueError("This run is not awaiting an editorial decision; its saved decision cannot be replaced. "
                             f"{verb} without --select or --question:\n{resume_command(store.home, args.run_id)}")
        decision = {"action": "dismiss"} if args.dismiss else {"action": "select", "pitch_id": args.select}
        if args.question is not None:
            decision["question"] = args.question
        if pending:
            workflow.select(snapshot.values, decision)  # Validate before consuming the interrupt.
        mode = row["mode"]
    # Re-open with configured adapters only when work is requested.
    workflow = runtime(store, mode, config) if not args.dismiss else workflow
    with open_graph(workflow, store.home) as graph:
        from langgraph.types import Command
        try:
            graph.invoke(Command(resume=decision) if pending else None, graph_config(args.run_id))
        except Exception:
            store.status(args.run_id, "error")
            print("Work checkpointed. Retry without --select or --question:\n"
                  f"{resume_command(store.home, args.run_id)}\nNo fixture fallback was used.", file=sys.stderr)
            raise
        snapshot = graph.get_state(graph_config(args.run_id))
        store.status(args.run_id, snapshot.values["status"])
        show(snapshot.values, store.home, is_interrupted(snapshot))


def main():
    args = parser().parse_args()
    store = None
    try:
        store = Store(args.home.resolve())
        run(args, store)
    except ModuleNotFoundError as e:
        print(f"Missing dependency {e.name}. Install with: python -m pip install -e .", file=sys.stderr)
        sys.exit(2)
    except (AdapterError, ValueError, OSError, sqlite3.Error, KeyError, TypeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    finally:
        if store:
            store.close()
