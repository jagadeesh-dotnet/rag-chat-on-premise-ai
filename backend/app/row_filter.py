"""Row-level permissions: rewrite a query so every restricted table only yields the user's rows.

    SELECT category, SUM(sales) FROM amazon_store_sales_data GROUP BY category
becomes
    SELECT category, SUM(sales)
    FROM (SELECT * FROM amazon_store_sales_data WHERE region IN ('East')) AS amazon_store_sales_data
    GROUP BY category

The rewrite works on the parsed tree (sqlglot), so tables are caught wherever they appear (joins,
subqueries, CTEs, UNION), and values are inserted as literals, never as SQL text. It runs after the guard
(app/sql_guard.py) has accepted the query, on the guard's tree.
"""

from sqlglot import exp

from app.sql_guard import GuardError


def apply_row_filters(
    tree: exp.Expression, conditions: dict[str, exp.Expression], dialect: str
) -> tuple[str, list[str]]:
    """Return (SQL to run, names of the tables that were filtered).

    conditions: lowercase table name -> a boolean expression over that table's own, unqualified columns.
    Tables without a condition are left alone.
    """
    if not conditions:
        return tree.sql(dialect=dialect), []
    tree = tree.copy()

    # A WITH name equal to a restricted table would make "FROM table" mean the CTE, not the table:
    # the filter would land on the wrong thing. Refuse instead of guessing.
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    clash = cte_names & conditions.keys()
    if clash:
        raise GuardError(f"A WITH name can't be the same as a table name: {', '.join(sorted(clash))}")
    if tree.find(exp.Pivot):
        raise GuardError("PIVOT and UNPIVOT can't be used here.")

    applied: set[str] = set()
    for table in list(tree.find_all(exp.Table)):  # a fixed list: the subqueries we insert aren't visited
        name = table.name.lower()
        if name not in conditions:
            continue
        alias = table.args.get("alias")
        if alias is not None and alias.columns:
            raise GuardError("Column aliases on a table (FROM t AS x(a, b)) can't be used here.")
        # Same name as before (its alias, or the table name), so every reference like t.column still works.
        visible_name = table.alias or table.name
        source = exp.Table(this=table.this.copy(), db=table.args["db"].copy() if table.args.get("db") else None)
        filtered = exp.select(exp.Star()).from_(source).where(conditions[name].copy())
        table.replace(filtered.subquery(alias=exp.to_identifier(visible_name)))
        applied.add(name)
    return tree.sql(dialect=dialect), sorted(applied)
