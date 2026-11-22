"""Local UI application service. Every job uses the same graph as the CLI."""
import json
import os
import re
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from .adapters import AdapterError
from .cli import initial_state, runtime
from .graph import graph_config, is_interrupted, open_graph
from .storage import Store
from .workflow import EditorialWorkflow


DOCUMENTS = {"article.md", "reporting-notes.md", "reporting-brief.md"}
STEPS = {"discover": "Reading news sources", "pitch": "Preparing story pitches", "editor": "Waiting for your angle",
         "research_start": "Opening original sources", "research_search": "Researching your question",
         "extract": "Building the source map", "draft": "Writing the first draft",
         "verify": "Checking claims and attribution", "export": "Saving your documents"}


class ServiceError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class NewsAgent:
    def __init__(self, home, workflow_factory=runtime):
        self.home = Path(home).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.workflow_factory = workflow_factory
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-agent")
        self.lock = threading.RLock()
        self.jobs = {}

    def close(self):
        self.executor.shutdown(wait=True)

    def settings(self):
        configured = lambda *keys: any(os.environ.get(k, "").strip() for k in keys)
        return {"name": "News Agent", "groq": configured("GROQ_API_KEY"),
                "qwen": configured("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
                "search": configured("TAVILY_API_KEY"),
                "sources": json.loads(Path(__file__).with_name("sources.json").read_text())}

    def _id(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ServiceError("Run not found.", 404)

    def _row(self, store, run_id):
        self._id(run_id)
        try:
            return store.get(run_id)
        except ValueError as error:
            raise ServiceError("Run not found.", 404) from error

    def _snapshot(self, store, run_id):
        workflow = EditorialWorkflow(store, None, None, None, None)
        with open_graph(workflow, self.home) as graph:
            return graph.get_state(graph_config(run_id))

    def _job(self, run_id):
        with self.lock:
            return dict(self.jobs.get(run_id, {}))

    def _active(self, run_id):
        return self._job(run_id).get("state") in {"queued", "running"}

    def _file(self, run_id, name, edited=False):
        self._id(run_id)
        if name not in DOCUMENTS:
            raise ServiceError("Document not found.", 404)
        folder = self.home / "outputs" / run_id
        target = folder / (name.removesuffix(".md") + "-edited.md" if edited else name)
        if not target.resolve().is_relative_to((self.home / "outputs").resolve()):
            raise ServiceError("Document not found.", 404)
        return target

    def documents(self, run_id):
        result = []
        for name in ("article.md", "reporting-brief.md", "reporting-notes.md"):
            original = self._file(run_id, name)
            if original.is_file():
                edited = self._file(run_id, name, edited=True)
                chosen = edited if edited.is_file() else original
                result.append({"name": name, "content": chosen.read_text(encoding="utf-8"), "edited": edited.is_file()})
        return result

    def list_runs(self):
        store = Store(self.home)
        try:
            result = []
            for row in store.list_runs()[:100]:
                snapshot = self._snapshot(store, row["id"])
                state = snapshot.values
                pitch = state.get("selected_pitch") or next(iter(state.get("pitches", [])), {})
                job = self._job(row["id"])
                result.append({"id": row["id"], "mode": row["mode"], "created_at": row["created_at"],
                               "status": row["status"], "title": pitch.get("headline", "New editorial briefing"),
                               "active": job.get("state") in {"queued", "running"},
                               "outcome": state.get("verification", {}).get("outcome")})
            return result
        finally:
            store.close()

    def detail(self, run_id):
        store = Store(self.home)
        try:
            row = self._row(store, run_id)
            snapshot = self._snapshot(store, run_id)
            state = snapshot.values
            job = self._job(run_id)
            active = job.get("state") in {"queued", "running"}
            pending = is_interrupted(snapshot)
            error = job.get("error", "")
            if not state and not active:
                error = "This run stopped before its first checkpoint. Start a new briefing."
            return {"id": run_id, "mode": row["mode"], "created_at": row["created_at"],
                    "status": row["status"], "active": active, "pending": pending,
                    "can_resume": bool(snapshot.next) and not pending and not active,
                    "stage": (STEPS.get(snapshot.next[0], "") if snapshot.next and active else job.get("stage", "")),
                    "error": error, "events": job.get("events", []),
                    "pitches": state.get("pitches", []), "selected_pitch": state.get("selected_pitch"),
                    "approved_question": state.get("approved_question", ""),
                    "searches_used": state.get("searches_used", 0),
                    "search_budget": json.loads(row["config"])["search_budget"],
                    "source_count": len(state.get("sources", [])), "candidate_count": len(state.get("candidates", [])),
                    "evidence": state.get("evidence", []), "reporting_tasks": state.get("reporting_tasks", []),
                    "verification": state.get("verification", {}), "warnings": state.get("errors", []),
                    "documents": self.documents(run_id)}
        finally:
            store.close()

    def discover(self, payload):
        mode = payload.get("mode", "live")
        if mode not in {"live", "offline"}:
            raise ServiceError("Choose live news or the fictional sample.")
        days, budget = payload.get("recent_days", 7), payload.get("search_budget", 3)
        if type(days) is not int or not 1 <= days <= 30 or type(budget) is not int or not 0 <= budget <= 10:
            raise ServiceError("Use 1–30 days and a research budget of 0–10 searches.")
        config = {"feeds": self.settings()["sources"], "recent_days": days, "search_budget": budget}
        store = Store(self.home)
        try:
            self.workflow_factory(store, mode, config)  # Validate credentials before creating a run.
            run_id = uuid4().hex
            store.create(run_id, mode, config)
            self._submit(run_id, "discover", initial_state(run_id, mode, config))
            return {"id": run_id}
        finally:
            store.close()

    def resume(self, run_id, payload):
        with self.lock:
            if self._active(run_id):
                raise ServiceError("This run is already in progress.", 409)
            store = Store(self.home)
            try:
                row = self._row(store, run_id)
                snapshot = self._snapshot(store, run_id)
                pending = is_interrupted(snapshot)
                action = payload.get("action", "resume")
                if action not in {"select", "dismiss", "resume"}:
                    raise ServiceError("Choose an angle, dismiss the run or retry reporting.")
                if pending:
                    if action == "resume":
                        raise ServiceError("Select a pitch and approve its question first.", 409)
                    decision = {"action": action}
                    if action == "select":
                        decision["pitch_id"] = str(payload.get("pitch_id", ""))
                        if "question" in payload:
                            decision["question"] = payload["question"]
                    EditorialWorkflow.select(snapshot.values, decision)
                else:
                    if action != "resume" or not snapshot.next:
                        raise ServiceError("This run has already saved its editorial decision.", 409)
                    decision = None
                if action != "dismiss":
                    self.workflow_factory(store, row["mode"], json.loads(row["config"]))
                self._submit(run_id, action, decision)
                return {"id": run_id}
            finally:
                store.close()

    def _submit(self, run_id, action, value):
        with self.lock:
            self.jobs[run_id] = {"state": "queued", "stage": "Waiting to start", "events": [], "error": ""}
        self.executor.submit(self._work, run_id, action, value)

    def _work(self, run_id, action, value):
        store = Store(self.home)
        try:
            row = store.get(run_id)
            config = json.loads(row["config"])
            workflow = (EditorialWorkflow(store, None, None, None, None) if action == "dismiss"
                        else self.workflow_factory(store, row["mode"], config))
            with self.lock:
                self.jobs[run_id].update(state="running", stage="Reading news sources" if action == "discover" else "Continuing your run")
            with open_graph(workflow, self.home) as graph:
                from langgraph.types import Command
                command = value if action == "discover" else Command(resume=value) if value is not None else None
                with warnings.catch_warnings(record=True) as captured:
                    warnings.simplefilter("always", RuntimeWarning)
                    seen = 0
                    for update in graph.stream(command, graph_config(run_id), stream_mode="updates"):
                        with self.lock:
                            events = self.jobs[run_id]["events"]
                            events.extend(str(item.message) for item in captured[seen:])
                            seen = len(captured)
                            for step in update:
                                if step in STEPS:
                                    self.jobs[run_id]["stage"] = STEPS[step]
                            self.jobs[run_id]["events"] = events[-30:]
                snapshot = graph.get_state(graph_config(run_id))
                store.status(run_id, snapshot.values["status"])
            with self.lock:
                self.jobs[run_id].update(state="done", stage="Ready for your angle" if is_interrupted(snapshot) else "Run finished")
        except Exception as error:
            store.status(run_id, "error")
            message = str(error) if isinstance(error, (AdapterError, ValueError)) else "The run stopped unexpectedly. Retry the saved work."
            with self.lock:
                self.jobs[run_id].update(state="failed", error=message, stage="Reporting paused")
        finally:
            store.close()

    def save_document(self, run_id, name, content):
        if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000:
            raise ServiceError("Document must contain at most 1 MB of text.")
        with self.lock:
            if self._active(run_id):
                raise ServiceError("Wait for reporting to finish before editing.", 409)
            if not self._file(run_id, name).is_file():
                raise ServiceError("Document not found.", 404)
            target = self._file(run_id, name, edited=True)
            temp = target.with_suffix(".tmp")
            temp.write_text(content, encoding="utf-8")
            temp.replace(target)
        return {"saved": True, "name": name}
