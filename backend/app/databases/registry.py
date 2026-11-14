"""The SQL Server databases the chat may query, from databases.json."""

import json
from dataclasses import dataclass, field

from app.config import settings


@dataclass(frozen=True)
class DatabaseConfig:
    name: str  # short name the model uses: "northwind"
    database: str  # real database name on the server: "Northwind"
    description: str
    notes: list[str] = field(default_factory=list)  # business rules the schema can't express


def load_databases() -> dict[str, DatabaseConfig]:
    """Read databases.json (small file, read each time so edits apply without a restart)."""
    path = settings.databases_file
    if not path.exists():
        return {}
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {
        e["name"].lower(): DatabaseConfig(
            name=e["name"].lower(),
            database=e["database"],
            description=e.get("description", ""),
            notes=list(e.get("notes", [])),
        )
        for e in entries
    }
