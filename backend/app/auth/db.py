"""The app's own SQL Server database (RagChatApp): accounts, roles, permissions, row rules, sessions, audit.

Tables are created by db-scripts/create_app_database.sql (run once by an administrator). At runtime the app
only reads and writes rows, as the database user chat_app.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pyodbc

from app.config import settings

# Importing this module also switches pyodbc connection pooling off (required with EXECUTE AS ... NO REVERT).
from app.databases.connection import connection_string

ADMIN_ROLE = "admin"
_IDENTIFIER = re.compile(r"^\w+$")


def now() -> datetime:
    """UTC, without tzinfo (SQL Server DATETIME2 has no time zone; every stored time is UTC)."""
    return datetime.now(UTC).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    """A stored UTC time as ISO 8601 with offset, for the API."""
    return f"{value.isoformat(timespec='seconds')}+00:00" if value else None


class Db:
    """A thin wrapper so queries read like SQL and rows come back as dicts."""

    def __init__(self, conn: pyodbc.Connection) -> None:
        self.conn = conn

    def execute(self, sql: str, *params) -> pyodbc.Cursor:
        return self.conn.execute(sql, *params)

    def all(self, sql: str, *params) -> list[dict]:
        cursor = self.conn.execute(sql, *params)
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def one(self, sql: str, *params) -> dict | None:
        rows = self.all(sql, *params)
        return rows[0] if rows else None

    def scalar(self, sql: str, *params):
        row = self.conn.execute(sql, *params).fetchone()
        return row[0] if row else None


def _open(database: str, as_user: str | None) -> pyodbc.Connection:
    conn = pyodbc.connect(connection_string(database), timeout=settings.db_login_timeout_s, autocommit=True)
    if as_user:
        if not _IDENTIFIER.match(as_user):  # put into SQL text below, so only plain names
            raise ValueError(f"Invalid database user: {as_user!r}")
        conn.execute(f"EXECUTE AS USER = '{as_user}' WITH NO REVERT")
    conn.autocommit = False  # one transaction per `with connect()` block
    return conn


@contextmanager
def connect() -> Iterator[Db]:
    """A transaction as chat_app: commits when the block ends, rolls back if it raises."""
    conn = _open(settings.app_database, settings.app_db_user)
    try:
        yield Db(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def connect_as_administrator() -> Iterator[Db]:
    """Your own Windows identity, without EXECUTE AS: only for the migration command and tests."""
    conn = _open(settings.app_database, None)
    try:
        yield Db(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
