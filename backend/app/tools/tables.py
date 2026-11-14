"""The query_tables tool: the model writes DuckDB SQL over the spreadsheet tables."""

from app.auth.access import Access
from app.sql_guard import GuardError
from app.tables.catalog import QueryError, get_catalog

NAME = "query_tables"

TOOL = {
    "type": "function",
    "function": {
        "name": NAME,
        "description": (
            "Run one read-only DuckDB SQL SELECT on the spreadsheet tables listed in the system prompt. "
            "Use it for numbers, totals, counts, averages, rankings and trends in spreadsheet data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A single DuckDB SELECT using only the listed tables and columns.",
                }
            },
            "required": ["sql"],
        },
    },
}


def _cell(value) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    return "" if value is None else str(value).replace("|", "/")


def to_markdown(columns: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def allowed_tables(access: Access) -> set[str] | None:
    """Spreadsheet tables this user may query (None = all)."""
    catalog = get_catalog()
    return None if access.is_admin else {t for t in catalog.tables if access.can_use_spreadsheet(t)}


def run_query(sql: str, access: Access) -> tuple[str, dict | None]:
    """Blocking: call with asyncio.to_thread. Returns (text for the model, table event or None)."""
    catalog = get_catalog()
    catalog.refresh()
    allowed = allowed_tables(access)
    if not catalog.visible(allowed):
        return "Error: you have no access to any spreadsheets. Tell the user you can't access that data.", None
    try:
        result = catalog.query(sql, allowed)
    except (GuardError, QueryError) as exc:
        # Send the schema back with the error, so the model can fix the SQL in its next round.
        return (f"Error: {exc}\n\nAvailable tables:\n{catalog.schema_text(allowed)}", None)

    names = ", ".join(sorted(catalog.visible(allowed)))
    source = f"Source: the spreadsheets ({names}). Name this source in your answer."
    if not result["rows"]:
        return f"{source}\nThe query returned no rows.", None
    text = source + "\n" + to_markdown(result["columns"], result["rows"])
    if result["truncated"]:
        text += f"\n(Only the first {len(result['rows'])} rows are shown.)"
    event = {"type": "table", "sql": sql, **result}
    return text, event
