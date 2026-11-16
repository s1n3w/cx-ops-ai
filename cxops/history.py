"""Local history of everything the app processes, for reports and Excel exports.

SQLite in %LOCALAPPDATA%\\cx-ops-ai\\history.db. Nothing leaves the PC. Only the desktop app writes here;
the scored tests never do.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "cx-ops-ai" / "history.db"
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY, created TEXT, source TEXT, test_id TEXT, plan TEXT, subject TEXT, body TEXT,
  type TEXT, urgency TEXT, queue TEXT, decision TEXT, risk_flags TEXT, kb_id TEXT, reply TEXT, why TEXT,
  seconds REAL, topic_id TEXT, topic_by TEXT);
CREATE TABLE IF NOT EXISTS responses (
  id INTEGER PRIMARY KEY, created TEXT, source TEXT, response_id TEXT UNIQUE, month TEXT, plan TEXT,
  score INTEGER, segment TEXT, comment TEXT, sentiment TEXT, themes TEXT, follow_up INTEGER, reason TEXT,
  topic_id TEXT, topic_by TEXT);
"""


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def add_ticket(t: dict) -> int:
    cols = ["created", "source", "test_id", "plan", "subject", "body", "type", "urgency", "queue", "decision",
            "risk_flags", "kb_id", "reply", "why", "seconds", "topic_id", "topic_by"]
    row = {**t, "created": t.get("created") or now(), "risk_flags": json.dumps(t.get("risk_flags", []))}
    with _lock, _conn() as c:
        cur = c.execute(f"INSERT INTO tickets ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [row.get(k) for k in cols])
        return cur.lastrowid


def add_response(r: dict) -> int:
    """Insert a survey response. Test-set responses (with a response_id) are updated, not duplicated, on re-runs."""
    cols = ["created", "source", "response_id", "month", "plan", "score", "segment", "comment", "sentiment",
            "themes", "follow_up", "reason", "topic_id", "topic_by"]
    row = {**r, "created": r.get("created") or now(), "themes": json.dumps(r.get("themes", [])),
           "follow_up": int(bool(r.get("follow_up")))}
    with _lock, _conn() as c:
        if row.get("response_id"):
            prior = c.execute("SELECT id, topic_by, topic_id FROM responses WHERE response_id = ?", [row["response_id"]]).fetchone()
            if prior and prior["topic_by"] == "you":  # keep a person's correction over a new AI suggestion
                row["topic_id"], row["topic_by"] = prior["topic_id"], "you"
            c.execute(f"INSERT INTO responses ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                      f"ON CONFLICT(response_id) DO UPDATE SET {','.join(f'{k}=excluded.{k}' for k in cols)}",
                      [row.get(k) for k in cols])
            return c.execute("SELECT id FROM responses WHERE response_id = ?", [row["response_id"]]).fetchone()[0]
        cur = c.execute(f"INSERT INTO responses ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [row.get(k) for k in cols])
        return cur.lastrowid


def set_topic(kind: str, item_id: int, topic_id: str) -> None:
    table = {"ticket": "tickets", "response": "responses"}[kind]
    with _lock, _conn() as c:
        c.execute(f"UPDATE {table} SET topic_id = ?, topic_by = 'you' WHERE id = ?", [topic_id, item_id])


def rows(kind: str) -> list[dict]:
    table = {"ticket": "tickets", "response": "responses"}[kind]
    with _conn() as c:
        out = [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY created, id")]
    for r in out:
        for key in ("risk_flags", "themes"):
            if key in r:
                r[key] = json.loads(r[key] or "[]")
        if "follow_up" in r:
            r["follow_up"] = bool(r["follow_up"])
    return out


def counts() -> dict:
    with _conn() as c:
        return {"tickets": c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
                "responses": c.execute("SELECT COUNT(*) FROM responses").fetchone()[0]}


def clear(kind: str | None = None) -> None:
    with _lock, _conn() as c:
        for table in ([{"ticket": "tickets", "response": "responses"}[kind]] if kind else ["tickets", "responses"]):
            c.execute(f"DELETE FROM {table}")
