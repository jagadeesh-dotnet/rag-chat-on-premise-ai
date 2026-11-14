"""Saved conversations in SQLite (data/chat.db), private per user.

The browser saves the whole thread after each answer. Every function takes the owner's user id: a user
can only list, open, save, rename or delete their own conversations.
"""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id       TEXT PRIMARY KEY,
    owner_id INTEGER,                 -- users.id in app.db; NULL only for chats saved before login existed
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
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(conversations)")}
    if "owner_id" not in columns:  # database from before login existed
        conn.execute("ALTER TABLE conversations ADD COLUMN owner_id INTEGER")
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def title_from(messages: list[dict]) -> str:
    first = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    text = " ".join(str(first).split())
    return (text[:57] + "...") if len(text) > 60 else (text or "New chat")


def list_conversations(owner_id: int) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, title, updated FROM conversations WHERE owner_id = ? ORDER BY updated DESC",
            (owner_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversation(owner_id: int, conversation_id: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, title, created, updated, messages FROM conversations WHERE id = ? AND owner_id = ?",
            (conversation_id, owner_id),
        ).fetchone()
    if row is None:
        return None  # someone else's conversation looks exactly like a missing one
    return {**dict(row), "messages": json.loads(row["messages"])}


def save_conversation(owner_id: int, conversation_id: str, messages: list[dict]) -> dict | None:
    """Create or replace the thread. Returns None if the id belongs to another user."""
    now = _now()
    data = json.dumps(messages, ensure_ascii=False)
    with closing(_connect()) as conn, conn:  # second `conn`: commit on success, roll back on error
        cursor = conn.execute(
            """INSERT INTO conversations (id, owner_id, title, created, updated, messages) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET messages = excluded.messages, updated = excluded.updated
               WHERE conversations.owner_id = excluded.owner_id""",
            (conversation_id, owner_id, title_from(messages), now, now, data),
        )
    return {"id": conversation_id, "updated": now} if cursor.rowcount == 1 else None


def rename_conversation(owner_id: int, conversation_id: str, title: str) -> bool:
    with closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "UPDATE conversations SET title = ?, updated = ? WHERE id = ? AND owner_id = ?",
            (title, _now(), conversation_id, owner_id),
        )
    return cursor.rowcount == 1


def delete_conversation(owner_id: int, conversation_id: str) -> bool:
    with closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND owner_id = ?", (conversation_id, owner_id)
        )
    return cursor.rowcount == 1


def adopt_orphans(owner_id: int) -> int:
    """Give conversations saved before login existed to this user (the first admin)."""
    with closing(_connect()) as conn, conn:
        return conn.execute(
            "UPDATE conversations SET owner_id = ? WHERE owner_id IS NULL", (owner_id,)
        ).rowcount
