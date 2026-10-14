"""SQLite storage. Every message, draft and decision is here so the owner can see why something was sent."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  channel TEXT NOT NULL,              -- whatsapp | email
  external_id TEXT NOT NULL,          -- wa message id or mail Message-ID
  conversation TEXT NOT NULL,         -- wa phone number or email address (lowercase)
  direction TEXT NOT NULL,            -- in | out
  subject TEXT,
  body TEXT NOT NULL,
  raw TEXT,                           -- original payload/headers as JSON, for debugging
  has_attachment INTEGER DEFAULT 0,
  received_at REAL NOT NULL,
  UNIQUE(channel, external_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation, received_at);

CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES messages(id),
  text TEXT NOT NULL,
  language TEXT,
  intents TEXT,                       -- JSON
  quote TEXT,                         -- JSON or NULL
  status TEXT NOT NULL,               -- pending | sent | held | approved_sent | approved_dry | rejected | expired | failed
  reasons TEXT,                       -- JSON list of hold reasons
  token TEXT UNIQUE,                  -- approval token when held
  token_used INTEGER DEFAULT 0,
  approver TEXT,
  created_at REAL NOT NULL,
  decided_at REAL,
  sent_at REAL,
  error TEXT
);

CREATE TABLE IF NOT EXISTS state (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  at REAL NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT
);
"""


def db_path() -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir / "projectbilal.db"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


def event(kind: str, detail: Any = None) -> None:
    with connect() as con:
        con.execute("INSERT INTO events(at, kind, detail) VALUES (?,?,?)",
                    (time.time(), kind, json.dumps(detail, default=str) if detail is not None else None))


def set_state(key: str, value: Any) -> None:
    with connect() as con:
        con.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value, default=str)))


def get_state(key: str, default: Any = None) -> Any:
    with connect() as con:
        row = con.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def insert_message(channel: str, external_id: str, conversation: str, direction: str, body: str,
                   subject: str | None = None, raw: Any = None, has_attachment: bool = False,
                   received_at: float | None = None) -> int | None:
    """Returns the new row id, or None if this external_id was already stored (duplicate delivery)."""
    with connect() as con:
        try:
            cur = con.execute(
                "INSERT INTO messages(channel, external_id, conversation, direction, subject, body, raw, has_attachment, received_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (channel, external_id, conversation.lower(), direction, subject, body,
                 json.dumps(raw, default=str) if raw is not None else None, int(has_attachment),
                 received_at or time.time()))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def get_message(message_id: int) -> sqlite3.Row | None:
    with connect() as con:
        return con.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()


def conversation_history(conversation: str, limit: int = 5) -> list[sqlite3.Row]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM messages WHERE conversation=? ORDER BY received_at DESC LIMIT ?",
            (conversation.lower(), limit)).fetchall()
    return list(reversed(rows))


def last_inbound_at(conversation: str, channel: str) -> float | None:
    with connect() as con:
        row = con.execute(
            "SELECT MAX(received_at) AS t FROM messages WHERE conversation=? AND channel=? AND direction='in'",
            (conversation.lower(), channel)).fetchone()
    return row["t"] if row and row["t"] else None


def insert_draft(message_id: int, text: str, language: str | None, intents: Any, quote: Any,
                 status: str, reasons: list[str], token: str | None) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO drafts(message_id, text, language, intents, quote, status, reasons, token, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (message_id, text, language, json.dumps(intents, default=str), json.dumps(quote, default=str) if quote else None,
             status, json.dumps(reasons), token, time.time()))
        return cur.lastrowid


def get_draft(draft_id: int) -> sqlite3.Row | None:
    with connect() as con:
        return con.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()


def get_draft_by_token(token: str) -> sqlite3.Row | None:
    with connect() as con:
        return con.execute("SELECT * FROM drafts WHERE token=?", (token,)).fetchone()


def update_draft(draft_id: int, **fields: Any) -> None:
    allowed = {"text", "status", "reasons", "token_used", "approver", "decided_at", "sent_at", "error"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {bad}")
    if "reasons" in fields and not isinstance(fields["reasons"], str):
        fields["reasons"] = json.dumps(fields["reasons"])
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect() as con:
        con.execute(f"UPDATE drafts SET {cols} WHERE id=?", (*fields.values(), draft_id))


def held_drafts_older_than(seconds: float) -> list[sqlite3.Row]:
    with connect() as con:
        return con.execute("SELECT * FROM drafts WHERE status='held' AND created_at < ?",
                           (time.time() - seconds,)).fetchall()


def _show(args: list[str]) -> None:
    table = "messages"
    last = 5
    if args and args[0] in ("messages", "drafts", "events"):
        table = args.pop(0)
    if len(args) >= 2 and args[0] == "--last":
        last = int(args[1])
    with connect() as con:
        rows = con.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (last,)).fetchall()
    for r in reversed(rows):
        d = dict(r)
        d.pop("raw", None)
        print(json.dumps(d, indent=1, default=str))


if __name__ == "__main__":
    init()
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        _show(sys.argv[2:])
    else:
        print(f"database at {db_path()}")
