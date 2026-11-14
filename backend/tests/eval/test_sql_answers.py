"""Numbers from SQL: the rows of a reference query must appear in what the model's query returned."""

import httpx
import pytest

from tests.eval.helpers import chat, params, row_found

pytestmark = [pytest.mark.eval, pytest.mark.sql]


def run_reference(client: httpx.Client, source: str, sql: str) -> list[list]:
    url = "/api/tables/query" if source == "spreadsheet" else f"/api/databases/{source}/query"
    response = client.post(url, json={"sql": sql})
    assert response.status_code == 200, f"the reference query itself failed: {response.text}"
    return response.json()["rows"]


@pytest.mark.parametrize("case", params("sql_answers"))
def test_sql_answer(case, admin, ollama, record_property):
    expected = run_reference(admin, case["source"], case["reference"])
    if columns := case.get("match_columns"):
        expected = [[row[i] for i in columns] for row in expected]
    assert expected, "the reference query returned no rows"

    result = chat(admin, case["question"])
    record_property("answer_seconds", result.seconds)
    assert result.error is None, f"error: {result.error}"
    assert result.tables, f"no query result. {result.summary()}"
    missing = [row for row in expected if not row_found(row, result.rows)]
    assert not missing, f"rows not found: {missing[:3]} in {result.rows[:5]} (sql: {result.tables[-1]['sql'][:150]})"
