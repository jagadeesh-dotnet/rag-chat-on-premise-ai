"""SQLite database for accounts: data/app.db."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from app.config import settings

ADMIN_ROLE = "admin"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY,
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name         TEXT NOT NULL,
    password_hash        TEXT NOT NULL,          -- bcrypt, never the password itself
    is_active            INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 1,
    created              TEXT NOT NULL,
    last_login           TEXT
);
CREATE TABLE IF NOT EXISTS roles (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    builtin     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS user_roles (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_name TEXT NOT NULL REFERENCES roles(name) ON DELETE CASCADE ON UPDATE CASCADE,
    PRIMARY KEY (user_id, role_name)
);
CREATE TABLE IF NOT EXISTS role_grants (
    role_name TEXT NOT NULL REFERENCES roles(name) ON DELETE CASCADE ON UPDATE CASCADE,
    kind      TEXT NOT NULL CHECK (kind IN ('folder', 'spreadsheet', 'database')),
    value     TEXT NOT NULL,                     -- 'hr', '/' (top-level files), a table or database name, or '*'
    PRIMARY KEY (role_name, kind, value)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,                 -- SHA-256 of the cookie value: a stolen app.db has no usable sessions
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created    TEXT NOT NULL,
    expires    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id       INTEGER PRIMARY KEY,
    at       TEXT NOT NULL,
    user_id  INTEGER,                            -- who did it (NULL for failed logins of unknown users)
    username TEXT NOT NULL,
    action   TEXT NOT NULL,                      -- login_ok, login_failed, login_locked, user_created, ...
    detail   TEXT NOT NULL DEFAULT ''            -- never passwords
);
CREATE INDEX IF NOT EXISTS audit_by_user ON audit (username, action, at);
INSERT OR IGNORE INTO roles (name, description, builtin) VALUES ('admin', 'Full access and user management', 1);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection with foreign keys on; commits on success, rolls back on error."""
    settings.app_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.app_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
