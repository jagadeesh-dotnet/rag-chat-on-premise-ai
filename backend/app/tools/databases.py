"""get_schema and run_sql: the model reads a database's tables, then writes T-SQL for it."""

import pyodbc

from app.databases.query import DatabaseError, GuardError, get_database, run_select
from app.databases.registry import load_databases
from app.databases.schema import render, schema_cache
from app.tools.tables import to_markdown

SCHEMA_NAME = "get_schema"
SQL_NAME = "run_sql"


def _database_parameter() -> dict:
    return {"type": "string", "description": "Database name from the list in the system prompt, e.g. northwind."}


SCHEMA_TOOL = {
    "type": "function",
    "function": {
        "name": SCHEMA_NAME,
        "description": "Get the tables, columns, keys and business notes of one SQL Server database. "
        "Call it before writing SQL for that database.",
        "parameters": {"type": "object", "properties": {"database": _database_parameter()}, "required": ["database"]},
    },
}

SQL_TOOL = {
    "type": "function",
    "function": {
        "name": SQL_NAME,
        "description": "Run one read-only T-SQL SELECT on one SQL Server database. Use TOP n (not LIMIT).",
        "parameters": {
            "type": "object",
            "properties": {
                "database": _database_parameter(),
                "sql": {"type": "string", "description": "A single T-SQL SELECT using that database's tables."},
            },
            "required": ["database", "sql"],
        },
    },
}


def database_list() -> str:
    """Names, descriptions and notes for the prompt (full schemas come from get_schema)."""
    lines = []
    for db in load_databases().values():
        lines.append(f"- {db.name}: {db.description}")
        lines += [f"    note: {n}" for n in db.notes]
    return "\n".join(lines)


def run_get_schema(database: str) -> tuple[str, int]:
    """Blocking. Returns (schema text for the model, number of tables)."""
    try:
        db = get_database(database)
        tables = schema_cache.tables(db)
    except DatabaseError as exc:
        return f"Error: {exc}", 0
    except pyodbc.Error:
        return f"Error: database {database!r} can't be reached right now.", 0
    return render(db, tables), len(tables)


def run_sql(database: str, sql: str) -> tuple[str, dict | None]:
    """Blocking. Returns (text for the model, table event or None)."""
    try:
        db = get_database(database)
        result = run_select(db, sql)
    except (GuardError, DatabaseError) as exc:
        return f"Error: {exc}", None
    except pyodbc.Error:
        return f"Error: database {database!r} can't be reached right now.", None

    source = f"Source: the {db.name} database. Name this source in your answer."
    if not result["rows"]:
        return f"{source}\nThe query returned no rows.", None
    text = source + "\n" + to_markdown(result["columns"], result["rows"])
    if result["truncated"]:
        text += f"\n(Only the first {len(result['rows'])} rows are shown.)"
    return text, {"type": "table", "database": db.name, "sql": sql, **result}
