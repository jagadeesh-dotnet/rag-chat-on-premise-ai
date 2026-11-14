"""Saved conversations in SQLite (data/chat.db): the browser saves the whole thread after each answer."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id       TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    created  TEXT NOT NULL,
    updated  TEXT NOT NULL,
    messages TEXT NOT NULL            -- JSON list: text, steps, sources and tables of each message
)"""


def _connect() -> sqlite3.Connection:
    settings.chat_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.chat_db_path)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["title"]
    conn.execute(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def title_from(messages: list[dict]) -> str:
    first = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    text = " ".join(str(first).split())
    return (text[:57] + "...") if len(text) > 60 else (text or "New chat")


def list_conversations() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT id, title, updated FROM conversations ORDER BY updated DESC").fetchall()
    return [dict(r) for r in rows]


def get_conversation(conversation_id: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if row is None:
        return None
    return {**dict(row), "messages": json.loads(row["messages"])}


def save_conversation(conversation_id: str, messages: list[dict]) -> dict:
    """Create or replace the thread. A new conversation gets its title from the first question."""
    now = _now()
    data = json.dumps(messages, ensure_ascii=False)
    with closing(_connect()) as conn, conn:  # second `conn`: commit on success, roll back on error
        conn.execute(
            """INSERT INTO conversations (id, title, created, updated, messages) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET messages = excluded.messages, updated = excluded.updated""",
            (conversation_id, title_from(messages), now, now, data),
        )
    return {"id": conversation_id, "updated": now}


def rename_conversation(conversation_id: str, title: str) -> bool:
    with closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "UPDATE conversations SET title = ?, updated = ? WHERE id = ?", (title, _now(), conversation_id)
        )
    return cursor.rowcount == 1


def delete_conversation(conversation_id: str) -> bool:
    with closing(_connect()) as conn, conn:
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return cursor.rowcount == 1
