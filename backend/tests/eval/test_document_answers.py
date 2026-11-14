"""Document answers: the agent searched (or didn't), the answer holds the facts, and the citation is right."""

import pytest

from tests.eval.helpers import REFUSAL, chat, cited, params

pytestmark = [pytest.mark.eval, pytest.mark.documents]


@pytest.mark.parametrize("case", params("document_answers"))
def test_document_answer(case, admin, ollama, record_property):
    result = chat(admin, case["question"], case.get("history"))
    record_property("answer_seconds", result.seconds)
    assert result.error is None, f"error: {result.error}"

    if case.get("must_search") is True:
        assert "search_documents" in result.tool_names, f"didn't search. {result.summary()}"
    if case.get("must_search") is False:
        assert not result.tools, f"used a tool for small talk. {result.summary()}"
    for fact in case.get("facts", []):
        assert fact.lower() in result.answer.lower(), f"missing {fact!r}. {result.summary()}"
    if cite := case.get("cite"):
        assert cited(result, cite["source"], cite.get("page")), f"expected a citation of {cite}. {result.summary()}"
    if case.get("no_citations"):
        assert not result.sources, f"cited sources in small talk. {result.summary()}"
    if case.get("refusal"):
        assert REFUSAL.search(result.answer), f"should say it couldn't find it. {result.summary()}"
        assert not result.sources, f"cited something for an answer that isn't in the documents. {result.summary()}"
