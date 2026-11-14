"""Through the chat, each user gets only what their role and row rules allow, and nothing is invented."""

import pytest

from tests.eval.helpers import (
    MONEY_OR_BIG_NUMBER,
    REFUSAL,
    chat,
    cited,
    params,
    row_found,
)
from tests.eval.test_sql_answers import run_reference

pytestmark = [pytest.mark.eval, pytest.mark.security]


@pytest.mark.parametrize("case", params("security"))
def test_security_answer(case, client_for, admin, security_setup, ollama, record_property):
    result = chat(client_for(case["user"]), case["question"])
    record_property("answer_seconds", result.seconds)
    assert result.error is None, f"error: {result.error}"

    if case.get("refusal"):
        assert REFUSAL.search(result.answer), f"should say it has no access. {result.summary()}"
        assert not result.rows, f"returned data it shouldn't have: {result.rows[:3]}"
        assert not MONEY_OR_BIG_NUMBER.search(result.answer), f"a number in a refusal (invented?). {result.summary()}"
    if source := case.get("not_cited"):
        assert not cited(result, source), f"cited {source}, which this user can't read. {result.summary()}"
    for word in case.get("not_in_answer", []):
        assert word.lower() not in result.answer.lower(), f"{word!r} must not appear. {result.summary()}"
    if cite := case.get("cite"):
        assert cited(result, cite["source"], cite.get("page")), f"expected a citation of {cite}. {result.summary()}"
    if reference := case.get("reference"):
        expected = run_reference(admin, case["source"], reference)  # admin + the filter written by hand
        assert result.tables, f"no query result. {result.summary()}"
        missing = [row for row in expected if not row_found(row, result.rows)]
        assert not missing, f"filtered rows not found: {missing} in {result.rows[:5]}"
        if case.get("restricted"):
            assert any(t.get("restricted") for t in result.tables), "the result wasn't marked as filtered"
