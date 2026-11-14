"""Row-level permissions: the rewrite must hold whatever SQL the model (or a crafted question) produces."""

import re

import pytest
from sqlglot import exp

from app.auth.access import Access, RowRule
from app.data_access import database_conditions, spreadsheet_conditions
from app.databases.schema import Table
from app.row_filter import apply_row_filters
from app.sql_guard import GuardError, check_select

RULE = RowRule("spreadsheet", "spreadsheets", "sales", "region", "region")


def user(*values: str, rules=(RULE,)) -> Access:
    attributes = (("region", values),) if values else ()
    return Access(1, "u", "u", attributes=attributes, row_rules=rules)


def rewrite(sql: str, access: Access, dialect: str = "duckdb") -> str:
    conditions = spreadsheet_conditions(access, ["sales", "other"])
    return apply_row_filters(check_select(sql, dialect, {"sales", "other"}), conditions, dialect)[0]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sales",
        "SELECT COUNT(*), SUM(amount) FROM sales",
        "SELECT s.amount FROM sales AS s",
        "SELECT a.id FROM sales a JOIN sales b ON a.id = b.id",  # self-join: both sides
        "SELECT * FROM other o JOIN sales s ON s.id = o.id",
        "SELECT * FROM (SELECT * FROM sales) x",
        "SELECT * FROM other WHERE id IN (SELECT id FROM sales)",
        "SELECT * FROM other WHERE EXISTS (SELECT 1 FROM sales WHERE sales.id = other.id)",
        "WITH t AS (SELECT * FROM sales) SELECT * FROM t",
        "SELECT id FROM other UNION ALL SELECT id FROM sales",
        "SELECT * FROM SALES",  # case
        'SELECT * FROM "sales"',  # quoted
    ],
)
def test_every_reference_is_filtered(sql):
    out = rewrite(sql, user("East"))
    assert "\"region\" IN ('East')" in out
    # Remove the filtered scans; no other read of the table may be left anywhere in the query.
    remainder = re.sub(r"""\(SELECT \* FROM "?sales"? WHERE "region" IN \('East'\)\)""", "", out, flags=re.IGNORECASE)
    assert not re.search(r"""(?i)\b(FROM|JOIN)\s+"?sales"?\b""", remainder), out


def test_self_join_filters_both_sides():
    out = rewrite("SELECT a.id FROM sales a JOIN sales b ON a.id = b.id", user("East"))
    assert out.count("\"region\" IN ('East')") == 2
    assert "AS a" in out and "AS b" in out  # aliases kept, so a.id / b.id still work


def test_unrestricted_tables_are_left_alone():
    assert rewrite("SELECT * FROM other", user("East")) == "SELECT * FROM other"


def test_missing_attribute_means_no_rows():
    assert "1 = 0" in rewrite("SELECT * FROM sales", user())


def test_several_values_and_quotes_are_data_not_sql():
    out = rewrite("SELECT * FROM sales", user("East", "O'Brien"))
    assert "IN ('East', 'O''Brien')" in out  # the quote is escaped inside the literal


def test_admin_is_never_filtered():
    admin = Access(1, "a", "a", is_admin=True, row_rules=(RULE,))
    assert spreadsheet_conditions(admin, ["sales"]) == {}


@pytest.mark.parametrize(
    "sql",
    [
        "WITH sales AS (SELECT 1 AS amount) SELECT * FROM sales",  # a CTE shadowing the table
        "SELECT * FROM sales AS s(a, b, c)",  # column aliases
        "SELECT * FROM sales PIVOT (SUM(amount) FOR region IN ('East', 'West'))",
    ],
)
def test_unsafe_shapes_are_rejected(sql):
    with pytest.raises(GuardError):
        rewrite(sql, user("East"))


# --- SQL Server: inheritance along foreign keys ---------------------------------------------------------

NORTHWIND = [
    Table("dbo", "Customers", 91, ["CustomerID nchar(5) PK", "Country nvarchar(15)"]),
    Table("dbo", "Orders", 830, ["OrderID int PK", "CustomerID nchar(5)"], [["CustomerID", "Customers", "CustomerID"]]),
    Table("dbo", "Order Details", 2155, ["OrderID int PK"], [["OrderID", "Orders", "OrderID"]]),
    Table("dbo", "Products", 77, ["ProductID int PK"]),
    Table("dbo", "Employees", 9, ["EmployeeID int PK", "ReportsTo int"], [["ReportsTo", "Employees", "EmployeeID"]]),
]
COUNTRY = RowRule("database", "northwind", "Customers", "Country", "country")


def german() -> Access:
    return Access(1, "u", "u", attributes=(("country", ("Germany",)),), row_rules=(COUNTRY,))


def test_restrictions_are_inherited_through_foreign_keys():
    conditions = database_conditions(german(), "northwind", NORTHWIND)
    assert set(conditions) == {"customers", "orders", "order details"}  # not products, not employees
    details = conditions["order details"].sql("tsql")
    assert "[OrderID] IN (SELECT [OrderID] FROM dbo.Orders WHERE [CustomerID] IN" in details
    assert "[Country] IN ('Germany')" in details


def test_inherited_filter_is_applied_with_brackets_and_aliases():
    known = {t.name.lower() for t in NORTHWIND}
    sql = "SELECT SUM(od.OrderID) FROM [Order Details] od JOIN dbo.Orders o ON o.OrderID = od.OrderID"
    tree = check_select(sql, "tsql", known, frozenset({"dbo"}))
    out, applied = apply_row_filters(tree, database_conditions(german(), "northwind", NORTHWIND), "tsql")
    assert applied == ["order details", "orders"]
    assert "FROM [Order Details] WHERE [OrderID] IN" in out and "AS od" in out and "AS o" in out


def test_self_reference_does_not_loop():
    rule = RowRule("database", "northwind", "Employees", "EmployeeID", "employee")
    access = Access(1, "u", "u", attributes=(("employee", ("1",)),), row_rules=(rule,))
    assert set(database_conditions(access, "northwind", NORTHWIND)) == {"employees"}


def test_rules_for_another_database_do_not_apply():
    assert database_conditions(german(), "pubs", NORTHWIND) == {}


def test_condition_is_a_real_expression():
    assert isinstance(spreadsheet_conditions(user("East"), ["sales"])["sales"], exp.In)
