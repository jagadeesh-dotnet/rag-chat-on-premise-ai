"""Read spreadsheets into clean DataFrames: one table per sheet (Excel) or per file (CSV)."""

import re
from pathlib import Path

import pandas as pd

_NOT_WORD = re.compile(r"[^0-9a-z]+")
_EXCEL_RANGE_SUFFIX = re.compile(r"\+[A-Z0-9]+:[A-Z]+\d+$")  # junk like "Row ID+O6G3A1:R6"
_TOTAL_LABEL = re.compile(r"^\s*(grand\s+)?(sub)?total\b", re.IGNORECASE)


def snake_name(text: str) -> str:
    """'Order Date' -> 'order_date', 'Sub-Category' -> 'sub_category'."""
    name = _NOT_WORD.sub("_", _EXCEL_RANGE_SUFFIX.sub("", str(text)).strip().lower()).strip("_")
    if not name or name[0].isdigit():
        name = f"col_{name}"
    return name


def clean_columns(columns: list) -> list[str]:
    """snake_case and unique: a second 'Sales' becomes 'sales_2'."""
    seen: dict[str, int] = {}
    result = []
    for column in columns:
        name = snake_name(column)
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result


def _is_total_row(row: pd.Series, text_columns: list[str]) -> bool:
    """A summary row: labelled 'Total'/'Grand Total', or numbers with every text column empty."""
    texts = [row[c] for c in text_columns if pd.notna(row[c]) and str(row[c]).strip()]
    if texts:
        return bool(_TOTAL_LABEL.match(str(texts[0])))
    return row.notna().any()


def drop_total_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove summary rows at the bottom; they would double every SUM."""
    text_columns = [c for c in df.columns if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])]
    end = len(df)
    while end > 0 and _is_total_row(df.iloc[end - 1], text_columns):
        end -= 1
    return df.iloc[:end]


def _tidy_types(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_float_dtype(series) and series.dropna().mod(1).eq(0).all():
            df[column] = series.astype("Int64")  # 3.0 -> 3 (quantities, counts, IDs)
        elif pd.api.types.is_string_dtype(series) or series.dtype == object:
            converted = pd.to_datetime(series, errors="coerce", format="mixed")
            if series.notna().sum() and converted.notna().sum() >= 0.9 * series.notna().sum():
                df[column] = converted  # text dates -> real dates (sortable, groupable by month)
    return df


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").dropna(axis=1, how="all")  # empty rows and columns
    df.columns = clean_columns(list(df.columns))
    df = drop_total_rows(df).reset_index(drop=True)
    return _tidy_types(df)


def read_spreadsheet(path: Path) -> dict[str, pd.DataFrame]:
    """{table_name: DataFrame}. Single-sheet files are named after the file, others file_sheet."""
    base = snake_name(path.stem)
    if path.suffix.lower() == ".csv":
        return {base: clean_frame(pd.read_csv(path))}
    sheets = pd.read_excel(path, sheet_name=None)
    tables = {}
    for sheet, df in sheets.items():
        name = base if len(sheets) == 1 else f"{base}_{snake_name(sheet)}"
        frame = clean_frame(df)
        if not frame.empty:
            tables[name] = frame
    return tables
