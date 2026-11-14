"""Turn a user's row rules into filter conditions for the row filter (app/row_filter.py).

Missing attribute = no rows: a rule the user has no value for becomes 1 = 0 (fail closed), never "all rows".
"""

from collections.abc import Iterable

from sqlglot import exp

from app.auth.access import Access, RowRule
from app.databases.schema import Table

MAX_DEPTH = 4  # how many foreign-key hops a restriction is inherited (cycle-safe: each table at most once)
NOTHING = exp.EQ(this=exp.Literal.number(1), expression=exp.Literal.number(0))


def _condition(rule: RowRule, access: Access) -> exp.Expression:
    values = access.values(rule.attribute)
    if not values:
        return NOTHING.copy()
    return exp.column(rule.column, quoted=True).isin(*(exp.Literal.string(v) for v in values))


def _direct(access: Access, kind: str, source: str, tables: Iterable[str]) -> dict[str, exp.Expression]:
    """Conditions from the rules themselves; several rules on one table must all hold (AND)."""
    known = {t.lower() for t in tables}
    parts: dict[str, list[exp.Expression]] = {}
    for rule in access.rules_for(kind, source):
        if rule.table.lower() in known:
            parts.setdefault(rule.table.lower(), []).append(_condition(rule, access))
    return {table: exp.and_(*conditions) for table, conditions in parts.items()}


def spreadsheet_conditions(access: Access, tables: Iterable[str]) -> dict[str, exp.Expression]:
    return _direct(access, "spreadsheet", "", tables)


def database_conditions(access: Access, database: str, tables: list[Table]) -> dict[str, exp.Expression]:
    """Direct rules, plus inheritance along foreign keys.

    If Customers is filtered by country, Orders (CustomerID -> Customers) only keeps orders of those
    customers, and [Order Details] (OrderID -> Orders) only their lines - otherwise totals over orders
    would still include every country.
    """
    by_name = {t.name.lower(): t for t in tables}
    conditions = _direct(access, "database", database, by_name)
    if not conditions:
        return {}
    for _ in range(MAX_DEPTH):
        inherited: dict[str, exp.Expression] = {}
        for key, table in by_name.items():
            if key in conditions:
                continue
            parts = []
            for column, ref_table, ref_column in table.foreign_keys:
                parent = ref_table.lower()
                if parent in conditions and parent != key:
                    parent_rows = (
                        exp.select(exp.column(ref_column, quoted=True))
                        .from_(exp.Table(this=exp.to_identifier(by_name[parent].name), db=exp.to_identifier(by_name[parent].schema)))
                        .where(conditions[parent].copy())
                    )
                    parts.append(exp.column(column, quoted=True).isin(query=parent_rows))
            if parts:
                inherited[key] = exp.and_(*parts)
        if not inherited:
            break
        conditions.update(inherited)
    return conditions


def restriction_note(applied: list[str]) -> str:
    """Told to the model when a result was filtered, so it doesn't present it as the full data."""
    if not applied:
        return ""
    return (
        f"\nNote: rows were filtered to what this user may see ({', '.join(applied)}). Say that the result covers "
        "only their data."
    )
