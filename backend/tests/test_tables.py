import pandas as pd
import pytest

from app.sql_guard import GuardError
from app.tables.catalog import QueryError, TableCatalog
from app.tables.loader import clean_columns, read_spreadsheet


def _write_sales(path):
    rows = pd.DataFrame(
        {
            "Row ID+O6G3A1:R6": [1, 2, 3],
            "Order ID": ["A-1", "A-1", "B-2"],
            "Order Date": ["2024-01-05", "2024-01-05", "2024-02-10"],
            "Category": ["Furniture", "Technology", "Furniture"],
            "Sales": [100.0, 50.0, 25.5],
            "Quantity": [1.0, 2.0, 3.0],
        }
    )
    total = pd.DataFrame({"Sales": [175.5]})  # the sheet's own grand total, below an empty row
    pd.concat([rows, pd.DataFrame([{}]), total]).to_excel(path, index=False)
    return path


def test_clean_columns():
    assert clean_columns(["Order Date", "Sub-Category", "Row ID+O6G3A1:R6", "Sales", "sales", "2024"]) == [
        "order_date",
        "sub_category",
        "row_id",
        "sales",
        "sales_2",
        "col_2024",
    ]


def test_loader_drops_total_row_and_fixes_types(tmp_path):
    (name, df), = read_spreadsheet(_write_sales(tmp_path / "Shop Sales.xlsx")).items()
    assert name == "shop_sales"
    assert len(df) == 3
    assert df["sales"].sum() == 175.5  # not 351: the total row is gone
    assert str(df["quantity"].dtype) == "Int64"
    assert pd.api.types.is_datetime64_any_dtype(df["order_date"])


@pytest.fixture
def catalog(tmp_path):
    _write_sales(tmp_path / "Shop Sales.xlsx")
    c = TableCatalog(tmp_path, timeout_s=1, max_rows=2)
    c.refresh()
    return c


def test_query_returns_rows_and_marks_truncation(catalog):
    result = catalog.query("SELECT category, SUM(sales) AS total FROM shop_sales GROUP BY 1 ORDER BY 2 DESC")
    assert result["columns"] == ["category", "total"]
    assert result["rows"] == [["Furniture", 125.5], ["Technology", 50.0]]
    assert result["truncated"] is False
    assert catalog.query("SELECT * FROM shop_sales")["truncated"] is True  # 3 rows, max 2


def test_orders_are_counted_distinct(catalog):
    assert catalog.query("SELECT COUNT(DISTINCT order_id) FROM shop_sales")["rows"] == [[2]]


def test_guard_runs_before_the_database(catalog):
    with pytest.raises(GuardError):
        catalog.query("DROP TABLE shop_sales")


def test_bad_column_is_a_query_error(catalog):
    with pytest.raises(QueryError, match="catgory"):
        catalog.query("SELECT catgory FROM shop_sales")


def test_duckdb_itself_refuses_files_even_without_the_guard(catalog):
    with pytest.raises(Exception, match="(?i)permission|disabled"):
        catalog._con.execute("SELECT * FROM read_csv('C:/Windows/win.ini')")
    with pytest.raises(Exception, match="(?i)cannot change"):
        catalog._con.execute("SET enable_external_access = true")


def test_slow_query_is_stopped(catalog):
    with pytest.raises(QueryError, match="longer than"):
        catalog.query(
            "SELECT COUNT(*) FROM shop_sales a, shop_sales b, shop_sales c, shop_sales d, shop_sales e, "
            "shop_sales f, shop_sales g, shop_sales h, shop_sales i, shop_sales j, shop_sales k, shop_sales l, "
            "shop_sales m, shop_sales n, shop_sales o, shop_sales p, shop_sales q, shop_sales r, shop_sales s, "
            "shop_sales t, shop_sales u, shop_sales v"
        )
