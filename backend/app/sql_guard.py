"""Allow only a single, plain, read-only SELECT on known tables. Used for DuckDB and (later) SQL Server.

This is the first safety layer. The databases are also locked down themselves (DuckDB without file/network
access, SQL Server with a read-only user), so a gap here still doesn't give write or file access.
"""

import sqlglot
from sqlglot import exp


class GuardError(ValueError):
    """The SQL was rejected. The message is safe to show to the model so it can fix its query."""


def _classes(*names: str) -> tuple[type, ...]:
    # Some expression types only exist in newer sqlglot versions.
    return tuple(getattr(exp, n) for n in names if hasattr(exp, n))


# Statements or clauses that change data, schema, settings or reach outside the database.
_FORBIDDEN = _classes(
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "TruncateTable",
    "Command", "Copy", "Attach", "Detach", "Pragma", "Set", "Use", "Transaction", "Commit",
    "Rollback", "Grant", "Into", "Install", "Load", "LoadData", "Export", "Kill",
)  # fmt: skip

# Functions that read files, URLs, environment variables or run other SQL.
_FORBIDDEN_FUNCTIONS = {
    "glob", "query", "query_table", "getenv", "sniff_csv", "openrowset", "opendatasource",
    "openquery", "xp_cmdshell", "load_extension",
}  # fmt: skip
_FORBIDDEN_PREFIXES = ("read_", "parquet_", "iceberg_", "delta_", "sqlite_", "postgres_", "mysql_")


def check_select(
    sql: str, dialect: str, allowed_tables: set[str], allowed_schemas: frozenset[str] = frozenset()
) -> exp.Expression:
    """Return the parsed query if it is safe, otherwise raise GuardError with the reason.

    allowed_schemas: schema prefixes that may be written before a table (SQL Server: {"dbo"}).
    Three-part names (database.schema.table) are always rejected: no reaching into other databases.
    """
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise GuardError(f"The SQL could not be parsed: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise GuardError("Send exactly one SQL statement.")
    tree = statements[0]

    if not isinstance(tree, exp.Query):  # SELECT, UNION/INTERSECT/EXCEPT, WITH ... SELECT
        raise GuardError("Only SELECT queries are allowed.")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN):
            raise GuardError(f"{node.key.upper()} is not allowed: only plain SELECT queries can run.")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name in _FORBIDDEN_FUNCTIONS or name.startswith(_FORBIDDEN_PREFIXES):
                raise GuardError(f"The function {name}() is not allowed.")

    allowed = {t.lower() for t in allowed_tables}
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):  # FROM read_csv(...), FROM range(...)
            raise GuardError("Table functions are not allowed: select from the listed tables only.")
        if table.args.get("catalog"):
            raise GuardError(f"Other databases can't be used: {table.sql(dialect)}")
        schema = table.text("db").lower()
        if schema and schema not in allowed_schemas:
            hint = f" Allowed: {', '.join(sorted(allowed_schemas))}." if allowed_schemas else ""
            raise GuardError(f"Schema {table.text('db')!r} can't be used: {table.sql(dialect)}.{hint}")
        name = table.name.lower()
        if name not in allowed and name not in cte_names:
            known = ", ".join(sorted(allowed_tables)) or "(none)"
            raise GuardError(f"Unknown table {table.name!r}. Available tables: {known}")
    return tree
