"""Run the model's SELECT on SQL Server: guard first, then as chat_reader, with timeout and row cap."""

import datetime as dt
import decimal
import re

import pyodbc

from app.auth.access import Access
from app.config import settings
from app.databases.connection import connect_read_only
from app.databases.registry import DatabaseConfig, load_databases
from app.databases.schema import render, schema_cache
from app.sql_guard import GuardError, check_select

SCHEMAS = frozenset({"dbo"})


class DatabaseError(ValueError):
    """The query failed. The message is meant for the model, so it can correct its SQL."""


def visible_databases(access: Access | None) -> dict[str, DatabaseConfig]:
    """The databases a user may use (access=None: all, for internal use and tests)."""
    return {n: db for n, db in load_databases().items() if access is None or access.can_use_database(n)}


def get_database(name: str, access: Access | None = None) -> DatabaseConfig:
    """A database the user may use. One they may not use reads as unknown: it doesn't reveal it exists."""
    databases = visible_databases(access)
    db = databases.get((name or "").strip().lower())
    if db is None:
        raise DatabaseError(f"Unknown database {name!r}. Available: {', '.join(databases) or '(none)'}")
    return db


def _json_value(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ") if value.time() != dt.time() else value.date().isoformat()
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray):
        return f"<{len(value)} bytes>"
    if isinstance(value, str):
        return value.rstrip()  # nchar(5) columns come back padded: 'ALFKI' not 'ALFKI   '
    return value


def _error_message(exc: pyodbc.Error) -> str:
    """'[Microsoft][ODBC Driver 18 ...][SQL Server]Invalid column name 'x'. (207) (SQLExecDirectW)' -> the useful part."""
    text = str(exc.args[-1]) if exc.args else str(exc)
    text = text.rsplit("]", 1)[-1]
    return re.sub(r"\s*\(\d+\)\s*\(SQL\w+\)\s*$", "", text).strip()


def run_select(db: DatabaseConfig, sql: str) -> dict:
    tables = schema_cache.tables(db)
    known = {t.name.lower() for t in tables}
    check_select(sql, "tsql", known, SCHEMAS)

    try:
        with connect_read_only(db) as conn:
            cursor = conn.execute(sql)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(settings.max_result_rows + 1)
    except pyodbc.Error as exc:
        message = _error_message(exc)
        if "timeout" in message.lower() or getattr(exc, "args", [""])[0] == "HYT00":
            raise DatabaseError(
                f"The query took longer than {settings.query_timeout_s:g} s and was stopped."
            ) from exc
        if "Invalid column name" in message or "Invalid object name" in message:
            # Self-healing: show the whole schema, not only the tables used - the fix is often a table the
            # query didn't use yet (e.g. pub_id is in titles, not titleauthor). Measured: fewer retries.
            message += "\n\nCall get_schema first next time. The database schema:\n" + render(db, tables)
        raise DatabaseError(message) from exc

    truncated = len(rows) > settings.max_result_rows
    rows = [[_json_value(v) for v in row] for row in rows[: settings.max_result_rows]]
    return {"columns": columns, "rows": rows, "truncated": truncated}


__all__ = ["DatabaseError", "GuardError", "get_database", "run_select", "visible_databases"]
