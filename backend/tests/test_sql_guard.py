import pytest

from app.sql_guard import GuardError, check_select

TABLES = {"sales"}

ALLOWED = [
    "SELECT * FROM sales",
    "SELECT category, SUM(sales) FROM sales GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
    (
        "WITH m AS (SELECT strftime(order_date, '%Y-%m') AS month, COUNT(DISTINCT order_id) AS n "
        "FROM sales GROUP BY 1) SELECT * FROM m ORDER BY month"
    ),
    "SELECT a.category FROM sales a JOIN sales b ON a.order_id = b.order_id",
    "SELECT 1 UNION ALL SELECT 2",
    "SELECT * FROM SALES",  # table names are case-insensitive
]

BLOCKED = [
    "DROP TABLE sales",
    "DELETE FROM sales",
    "UPDATE sales SET sales = 0",
    "INSERT INTO sales VALUES (1)",
    "CREATE TABLE x AS SELECT * FROM sales",
    "SELECT * INTO copy FROM sales",
    "SELECT 1; SELECT 2",
    "SELECT * FROM read_csv('C:/Windows/win.ini')",
    "SELECT read_text('C:/Windows/win.ini')",
    "SELECT * FROM glob('*')",
    "SELECT getenv('PATH')",
    "SELECT * FROM range(10)",
    "SELECT * FROM 'C:/data.csv'",
    "ATTACH 'x.db' AS x",
    "COPY sales TO 'out.csv'",
    "PRAGMA database_list",
    "SET enable_external_access = true",
    "INSTALL httpfs",
    "SELECT * FROM other_table",
    "SELECT * FROM main.sales",
    "not sql at all",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_plain_selects_are_allowed(sql):
    check_select(sql, "duckdb", TABLES)


@pytest.mark.parametrize("sql", BLOCKED)
def test_anything_else_is_rejected(sql):
    with pytest.raises(GuardError):
        check_select(sql, "duckdb", TABLES)


def test_unknown_table_error_lists_the_real_tables():
    with pytest.raises(GuardError, match="Available tables: sales"):
        check_select("SELECT * FROM orders", "duckdb", TABLES)
