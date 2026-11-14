"""All spreadsheets as tables in one sandboxed, in-memory DuckDB database."""

import datetime as dt
import decimal
import logging
import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import duckdb

from app.config import settings
from app.ingest.loaders import SPREADSHEETS
from app.sql_guard import check_select
from app.tables.loader import read_spreadsheet

log = logging.getLogger(__name__)


class QueryError(ValueError):
    """The query failed. The message is meant for the model, so it can correct its SQL."""


@dataclass
class TableInfo:
    name: str
    source: str  # file it came from, relative to docs_dir
    rows: int
    columns: list[tuple[str, str]]  # (name, DuckDB type)
    samples: dict[str, list[str]]


def _json_value(value):
    """DuckDB returns dates and decimals; JSON (and the UI) needs strings and floats."""
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ") if value.time() != dt.time() else value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


class TableCatalog:
    def __init__(self, docs_dir: Path, timeout_s: float, max_rows: int) -> None:
        self._docs_dir = docs_dir
        self._timeout_s = timeout_s
        self._max_rows = max_rows
        self._lock = threading.Lock()  # one DuckDB connection: one query at a time
        self._con: duckdb.DuckDBPyConnection | None = None
        self._signature: dict[str, float] = {}
        self.tables: dict[str, TableInfo] = {}

    def _files(self) -> list[Path]:
        return sorted(
            p
            for p in self._docs_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in SPREADSHEETS and not p.name.startswith(("~$", "."))
        )

    def refresh(self) -> None:
        """Reload when a spreadsheet was added, changed or removed (checked by modification time)."""
        files = self._files()
        signature = {p.as_posix(): p.stat().st_mtime for p in files}
        with self._lock:
            if self._con is not None and signature == self._signature:
                return
            frames, tables = {}, {}
            for path in files:
                try:
                    for name, df in read_spreadsheet(path).items():
                        frames[name] = df
                        tables[name] = path.relative_to(self._docs_dir).as_posix()
                except Exception as exc:  # noqa: BLE001 - one bad spreadsheet must not hide the others
                    log.warning("Skipping spreadsheet %s: %s", path.name, exc)
            self._build(frames, tables)
            self._signature = signature

    def _build(self, frames: dict, sources: dict[str, str]) -> None:
        con = duckdb.connect(
            ":memory:",
            config={
                "enable_external_access": False,  # SQL can't read files or URLs
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
            },
        )
        infos = {}
        for name, df in frames.items():
            con.register("incoming", df)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM incoming')
            con.unregister("incoming")
            columns = [(r[0], r[1]) for r in con.execute(f'DESCRIBE "{name}"').fetchall()]
            samples = {}
            for column, _ in columns:
                values = con.execute(
                    f'SELECT DISTINCT "{column}" FROM "{name}" WHERE "{column}" IS NOT NULL LIMIT 3'
                ).fetchall()
                samples[column] = [str(_json_value(v[0]))[:40] for v in values]
            rows = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            infos[name] = TableInfo(name, sources[name], rows, columns, samples)
        # Lock down AFTER the tables exist: no Python variables from SQL, and settings can't be changed back.
        con.execute("SET python_enable_replacements = false")
        con.execute("SET lock_configuration = true")
        if self._con is not None:
            self._con.close()
        self._con, self.tables = con, infos
        log.info("Spreadsheet tables: %s", {n: i.rows for n, i in infos.items()})

    def schema_text(self) -> str:
        """Tables, columns, types and sample values, for the model's prompt."""
        if not self.tables:
            return "(no spreadsheets)"
        parts = []
        for info in self.tables.values():
            lines = [f"Table {info.name} ({info.rows} rows, from {info.source}):"]
            for column, kind in info.columns:
                examples = ", ".join(info.samples.get(column, []))
                lines.append(f"  - {column} {kind}  e.g. {examples}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    def query(self, sql: str) -> dict:
        """Run a guarded SELECT. Returns columns, rows (max max_rows) and whether it was cut off."""
        with self._lock:
            if self._con is None:
                raise QueryError("No spreadsheet tables are loaded.")
            check_select(sql, "duckdb", set(self.tables))
            timer = threading.Timer(self._timeout_s, self._con.interrupt)
            timer.start()
            try:
                cursor = self._con.execute(sql)
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchmany(self._max_rows + 1)
            except duckdb.InterruptException as exc:
                raise QueryError(f"The query took longer than {self._timeout_s:g} s and was stopped.") from exc
            except duckdb.Error as exc:
                raise QueryError(str(exc).splitlines()[0]) from exc
            finally:
                timer.cancel()
        truncated = len(rows) > self._max_rows
        rows = [[_json_value(v) for v in row] for row in rows[: self._max_rows]]
        return {"columns": columns, "rows": rows, "truncated": truncated}


@lru_cache
def get_catalog() -> TableCatalog:
    return TableCatalog(settings.docs_dir, settings.query_timeout_s, settings.max_result_rows)
