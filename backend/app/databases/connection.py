"""Read-only connections: connect with Windows authentication, then become chat_reader for good."""

import re
from collections.abc import Iterator
from contextlib import contextmanager

import pyodbc

from app.config import settings
from app.databases.registry import DatabaseConfig

# Must be off before the first connect: a pooled connection would be handed out again while still
# impersonating chat_reader, and NO REVERT means it can never switch back.
pyodbc.pooling = False

_IDENTIFIER = re.compile(r"^\w+$")


def connection_string(database: str) -> str:
    """Windows authentication to a database on the configured SQL Server (also used for RagChatApp)."""
    return (
        f"Driver={{{settings.odbc_driver}}};Server={settings.sql_server};Database={database};"
        "Trusted_Connection=yes;TrustServerCertificate=yes;"  # Driver 18 encrypts; local cert is self-signed
    )


_connection_string = connection_string


@contextmanager
def connect_read_only(db: DatabaseConfig) -> Iterator[pyodbc.Connection]:
    """A connection that runs everything as the read-only database user, with a query timeout."""
    user = settings.db_reader_user
    if not _IDENTIFIER.match(user):  # it's put into SQL text below, so only plain names are allowed
        raise ValueError(f"Invalid db_reader_user: {user!r}")
    conn = pyodbc.connect(_connection_string(db.database), timeout=settings.db_login_timeout_s, autocommit=True)
    try:
        # From here on this connection has only chat_reader's rights (db_datareader), and can't switch back.
        conn.execute(f"EXECUTE AS USER = '{user}' WITH NO REVERT")
        conn.timeout = int(settings.query_timeout_s)  # seconds per statement; 0 would mean no limit
        yield conn
    finally:
        conn.close()


def is_reachable(db: DatabaseConfig) -> bool:
    try:
        with connect_read_only(db) as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except pyodbc.Error:
        return False
