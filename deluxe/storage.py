"""Run index and story ledger. LangGraph owns the separate checkpoint database."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, home: Path):
        self.home = home
        home.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(home / "editorial.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, mode TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, config TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stories (
                run_id TEXT NOT NULL, mode TEXT NOT NULL, event_key TEXT NOT NULL,
                headline TEXT NOT NULL, urls TEXT NOT NULL,
                PRIMARY KEY (run_id, event_key)
            );
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def create(self, run_id, mode, config):
        with self.db:
            self.db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                            (run_id, mode, datetime.now(timezone.utc).isoformat(),
                             "starting", json.dumps(config)))

    def get(self, run_id):
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown run ID: {run_id}")
        return dict(row)

    def list_runs(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM runs ORDER BY created_at DESC")]

    def status(self, run_id, status):
        with self.db:
            self.db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))

    def previous(self, mode, exclude_run):
        return [dict(r) | {"urls": json.loads(r["urls"])} for r in self.db.execute(
            "SELECT * FROM stories WHERE mode=? AND run_id != ?", (mode, exclude_run))]

    def record(self, state):
        candidates = {c["id"]: c for c in state["candidates"]}
        with self.db:
            for p in state["pitches"]:
                urls = [candidates[c]["url"] for c in p["candidate_ids"]]
                self.db.execute("INSERT OR REPLACE INTO stories VALUES (?, ?, ?, ?, ?)",
                                (state["run_id"], state["mode"], p["event_key"],
                                 p["headline"], json.dumps(urls)))
