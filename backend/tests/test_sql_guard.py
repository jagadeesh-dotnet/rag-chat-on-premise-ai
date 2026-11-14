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


NORTHWIND = {"orders", "customers", "order details"}
DBO = frozenset({"dbo"})

TSQL_ALLOWED = [
    "SELECT TOP 5 c.CompanyName FROM dbo.Customers c ORDER BY c.CompanyName",
    (
        "SELECT o.OrderID, SUM(od.UnitPrice * od.Quantity) FROM Orders o JOIN [Order Details] od "
        "ON od.OrderID = o.OrderID GROUP BY o.OrderID"
    ),
    (
        "WITH t AS (SELECT TOP 3 CustomerID FROM dbo.Orders GROUP BY CustomerID ORDER BY COUNT(*) DESC) "
        "SELECT c.CompanyName FROM t JOIN dbo.Customers c ON c.CustomerID = t.CustomerID"
    ),
]

TSQL_BLOCKED = [
    "SELECT * FROM Northwind.dbo.Orders",  # three-part name: another database
    "SELECT * FROM master.sys.databases",
    "SELECT * FROM sys.tables",  # system schema
    "SELECT * FROM INFORMATION_SCHEMA.COLUMNS",
    "EXEC xp_cmdshell 'dir'",
    "SELECT * FROM OPENROWSET('SQLNCLI', 'Server=x;', 'SELECT 1')",
    "SELECT * INTO #copy FROM dbo.Orders",
    "UPDATE dbo.Orders SET Freight = 0",
    "WAITFOR DELAY '00:01:00'",
    "SELECT * FROM dbo.Orders; DROP TABLE dbo.Orders",
]


@pytest.mark.parametrize("sql", TSQL_ALLOWED)
def test_tsql_selects_with_dbo_and_brackets_are_allowed(sql):
    check_select(sql, "tsql", NORTHWIND, DBO)


@pytest.mark.parametrize("sql", TSQL_BLOCKED)
def test_tsql_attacks_are_rejected(sql):
    with pytest.raises(GuardError):
        check_select(sql, "tsql", NORTHWIND, DBO)


def test_unknown_table_error_lists_the_real_tables():
    with pytest.raises(GuardError, match="Available tables: sales"):
        check_select("SELECT * FROM orders", "duckdb", TABLES)
