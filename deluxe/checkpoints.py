"""Synchronous SQLite LangGraph saver for this CLI's ordinary state channels.

Uses LangGraph's typed serializer (including Interrupt objects), never pickle.
Each checkpoint stores a full channel snapshot; writes are durable independently
so an interrupt/resume survives exit before the next superstep checkpoint.
"""
import sqlite3
import threading

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP


class SQLiteSaver(BaseCheckpointSaver):
    def __init__(self, path):
        super().__init__()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread TEXT, ns TEXT, id TEXT, parent TEXT,
                type TEXT, data BLOB, meta_type TEXT, meta BLOB,
                PRIMARY KEY(thread, ns, id)
            );
            CREATE TABLE IF NOT EXISTS writes (
                thread TEXT, ns TEXT, checkpoint TEXT, task TEXT, idx INTEGER,
                channel TEXT, type TEXT, data BLOB,
                PRIMARY KEY(thread, ns, checkpoint, task, idx)
            );
        """)
        self.db.commit()

    @staticmethod
    def config(thread, ns, checkpoint):
        return {"configurable": {"thread_id": thread, "checkpoint_ns": ns, "checkpoint_id": checkpoint}}

    def close(self):
        self.db.close()

    def get_tuple(self, config):
        c = config["configurable"]
        args = [c["thread_id"], c.get("checkpoint_ns", "")]
        query = "SELECT * FROM checkpoints WHERE thread=? AND ns=?"
        if c.get("checkpoint_id"):
            query += " AND id=?"
            args.append(c["checkpoint_id"])
        with self.lock:
            row = self.db.execute(query + " ORDER BY id DESC LIMIT 1", args).fetchone()
            if row is None:
                return None
            writes = self.db.execute("SELECT * FROM writes WHERE thread=? AND ns=? AND checkpoint=? ORDER BY task, idx",
                                     (row["thread"], row["ns"], row["id"])).fetchall()
        return CheckpointTuple(
            self.config(row["thread"], row["ns"], row["id"]),
            self.serde.loads_typed((row["type"], row["data"])),
            self.serde.loads_typed((row["meta_type"], row["meta"])),
            self.config(row["thread"], row["ns"], row["parent"]) if row["parent"] else None,
            [(w["task"], w["channel"], self.serde.loads_typed((w["type"], w["data"]))) for w in writes])

    def put(self, config, checkpoint, metadata, new_versions):
        c = config["configurable"]
        typ, data = self.serde.dumps_typed(checkpoint)
        meta_type, meta = self.serde.dumps_typed(metadata)
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (c["thread_id"], c.get("checkpoint_ns", ""), checkpoint["id"],
                             c.get("checkpoint_id"), typ, data, meta_type, meta))
        return self.config(c["thread_id"], c.get("checkpoint_ns", ""), checkpoint["id"])

    def put_writes(self, config, writes, task_id, task_path=""):
        c = config["configurable"]
        with self.lock, self.db:
            for index, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, index)
                typ, data = self.serde.dumps_typed(value)
                # Special writes (interrupt/resume/error) must replace older values.
                operation = "REPLACE" if idx < 0 else "IGNORE"
                self.db.execute(f"INSERT OR {operation} INTO writes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (c["thread_id"], c.get("checkpoint_ns", ""), c["checkpoint_id"],
                                 task_id, idx, channel, typ, data))

    def list(self, config, *, filter=None, before=None, limit=None):
        clauses, args = [], []
        if config:
            c = config["configurable"]
            clauses.append("thread=?")
            args.append(c["thread_id"])
            if "checkpoint_ns" in c:
                clauses.append("ns=?")
                args.append(c["checkpoint_ns"])
        if before:
            clauses.append("id < ?")
            args.append(before["configurable"]["checkpoint_id"])
        query = "SELECT thread, ns, id FROM checkpoints" + (" WHERE " + " AND ".join(clauses) if clauses else "")
        with self.lock:
            rows = self.db.execute(query + " ORDER BY id DESC", args).fetchall()
        count = 0
        for row in rows:
            item = self.get_tuple(self.config(row["thread"], row["ns"], row["id"]))
            if filter and any(item.metadata.get(k) != v for k, v in filter.items()):
                continue
            if limit is not None and count >= limit:
                break
            yield item
            count += 1
