"""SQL Server tests. Skipped when the server or the databases aren't available."""

import pytest

from app.databases.connection import connect_read_only, is_reachable
from app.databases.query import DatabaseError, GuardError, get_database, run_select
from app.databases.schema import render, schema_cache


@pytest.fixture(scope="module")
def northwind():
    try:
        db = get_database("northwind")
    except DatabaseError:
        pytest.skip("northwind is not in databases.json")
    if not is_reachable(db):
        pytest.skip("SQL Server / Northwind not reachable")
    return db


def test_queries_run_as_the_read_only_user(northwind):
    result = run_select(northwind, "SELECT USER_NAME() AS db_user, COUNT(*) AS orders FROM dbo.Orders")
    assert result["rows"] == [["chat_reader", 830]]


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO dbo.Shippers (CompanyName) VALUES ('test')",
        "UPDATE dbo.Shippers SET Phone = 'x'",
        "DELETE FROM dbo.Shippers WHERE 1 = 0",
        "DROP TABLE dbo.Shippers",
        "EXEC xp_cmdshell 'dir'",
        "REVERT",
    ],
)
def test_sql_server_refuses_changes_even_without_the_guard(northwind, sql):
    with connect_read_only(northwind) as conn, pytest.raises(Exception, match="(?i)permission|denied|revert|not exist"):
        conn.execute(sql)


def test_guard_rejects_other_databases(northwind):
    with pytest.raises(GuardError):
        run_select(northwind, "SELECT * FROM master.sys.databases")


def test_schema_has_keys_and_row_counts(northwind):
    text = render(northwind, schema_cache.tables(northwind))
    assert "dbo.Orders (830 rows)" in text
    assert "CustomerID nchar(5) -> Customers.CustomerID" in text
    assert "dbo.[Order Details]" in text


def test_nchar_padding_is_stripped(northwind):
    rows = run_select(northwind, "SELECT TOP 1 CustomerID FROM dbo.Customers ORDER BY CustomerID")["rows"]
    assert rows == [["ALFKI"]]


def test_wrong_column_error_includes_the_real_columns(northwind):
    with pytest.raises(DatabaseError) as error:
        run_select(northwind, "SELECT CompanyNmae FROM dbo.Customers")
    assert "Invalid column name 'CompanyNmae'" in str(error.value)
    assert "CompanyName nvarchar(40)" in str(error.value)


def test_unknown_database():
    with pytest.raises(DatabaseError, match="Available"):
        get_database("nope")
