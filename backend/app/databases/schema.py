"""Read a database's tables, columns and keys, render them for the model, and cache them."""

import json
import threading
import time
from dataclasses import asdict, dataclass

import pyodbc

from app.config import settings
from app.databases.connection import connect_read_only
from app.databases.registry import DatabaseConfig

_COLUMNS = """
SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH,
       c.NUMERIC_PRECISION, c.NUMERIC_SCALE, c.IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS c
JOIN INFORMATION_SCHEMA.TABLES t ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
WHERE t.TABLE_TYPE = 'BASE TABLE'
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION"""

_PRIMARY_KEYS = """
SELECT k.TABLE_SCHEMA, k.TABLE_NAME, k.COLUMN_NAME
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k ON k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'"""

_FOREIGN_KEYS = """
SELECT SCHEMA_NAME(pt.schema_id), pt.name, pc.name, rt.name, rc.name
FROM sys.foreign_key_columns fk
JOIN sys.tables pt ON pt.object_id = fk.parent_object_id
JOIN sys.columns pc ON pc.object_id = fk.parent_object_id AND pc.column_id = fk.parent_column_id
JOIN sys.tables rt ON rt.object_id = fk.referenced_object_id
JOIN sys.columns rc ON rc.object_id = fk.referenced_object_id AND rc.column_id = fk.referenced_column_id"""

_ROW_COUNTS = """
SELECT SCHEMA_NAME(t.schema_id), t.name, SUM(p.rows)
FROM sys.tables t JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
GROUP BY t.schema_id, t.name"""

# Changes whenever a table or column is created, altered or dropped.
_FINGERPRINT = "SELECT COUNT(*), CONVERT(varchar(30), MAX(modify_date), 126) FROM sys.objects WHERE is_ms_shipped = 0"


@dataclass
class Table:
    schema: str
    name: str
    rows: int
    columns: list[str]  # already rendered: "OrderID int PK", "CustomerID nchar(5) -> Customers.CustomerID"


def _type(data_type: str, length, precision, scale) -> str:
    if data_type in ("char", "nchar", "varchar", "nvarchar", "binary", "varbinary"):
        return f"{data_type}({'max' if length == -1 else length})"
    if data_type in ("decimal", "numeric"):
        return f"{data_type}({precision},{scale})"
    return data_type


def read_schema(conn: pyodbc.Connection) -> list[Table]:
    primary = {tuple(r) for r in conn.execute(_PRIMARY_KEYS).fetchall()}
    foreign = {(r[0], r[1], r[2]): f"{r[3]}.{r[4]}" for r in conn.execute(_FOREIGN_KEYS).fetchall()}
    counts = {(r[0], r[1]): int(r[2] or 0) for r in conn.execute(_ROW_COUNTS).fetchall()}

    tables: dict[tuple[str, str], Table] = {}
    for schema, table, column, data_type, length, precision, scale, nullable in conn.execute(_COLUMNS):
        key = (schema, table)
        if key not in tables:
            tables[key] = Table(schema, table, counts.get(key, 0), [])
        text = f"{column} {_type(data_type, length, precision, scale)}"
        if (schema, table, column) in primary:
            text += " PK"
        if (schema, table, column) in foreign:
            text += f" -> {foreign[(schema, table, column)]}"
        if nullable == "YES":
            text += " null"
        tables[key].columns.append(text)
    return list(tables.values())


def quoted(table: Table) -> str:
    name = f"[{table.name}]" if not table.name.isidentifier() else table.name
    return f"{table.schema}.{name}"


def render(db: DatabaseConfig, tables: list[Table], only: set[str] | None = None) -> str:
    """Compact schema text. `only`: lowercase table names to include (for focused error hints)."""
    lines = [f"Database {db.name} (SQL Server, T-SQL). {db.description}"]
    for note in db.notes:
        lines.append(f"Note: {note}")
    for t in tables:
        if only is None or t.name.lower() in only:
            lines.append(f"{quoted(t)} ({t.rows} rows): {', '.join(t.columns)}")
    return "\n".join(lines)


class SchemaCache:
    """Schema per database: in memory, on disk (data/cache/schemas), re-read only when the database changed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._memory: dict[str, tuple[float, str, list[Table]]] = {}  # name -> (checked_at, fingerprint, tables)

    def tables(self, db: DatabaseConfig, force: bool = False) -> list[Table]:
        with self._lock:
            cached = self._memory.get(db.name) or self._from_disk(db)
            if cached and not force and time.monotonic() - cached[0] < settings.schema_recheck_s:
                return cached[2]
            with connect_read_only(db) as conn:
                count, modified = conn.execute(_FINGERPRINT).fetchone()
                fingerprint = f"{count}|{modified}"
                if cached and not force and cached[1] == fingerprint:
                    tables = cached[2]  # unchanged: no need to read the whole schema again
                else:
                    tables = read_schema(conn)
                    self._to_disk(db, fingerprint, tables)
            self._memory[db.name] = (time.monotonic(), fingerprint, tables)
            return tables

    def _path(self, db: DatabaseConfig):
        return settings.cache_dir / "schemas" / f"{db.name}.json"

    def _from_disk(self, db: DatabaseConfig):
        path = self._path(db)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return (float("-inf"), data["fingerprint"], [Table(**t) for t in data["tables"]])  # -inf: verify once

    def _to_disk(self, db: DatabaseConfig, fingerprint: str, tables: list[Table]) -> None:
        path = self._path(db)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"fingerprint": fingerprint, "tables": [asdict(t) for t in tables]}
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")


schema_cache = SchemaCache()
