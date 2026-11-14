"""Faithfulness, graded by the local model: is every claim in the answer supported by the passages it read?

A second opinion, not the truth: an LLM judge misses things and can be fooled, so the fact and citation checks
in test_document_answers.py stay the main grader. It is good at catching made-up claims.
"""

import json

import pytest
from ollama import Client

from app.config import settings
from tests.eval.helpers import chat, load_dataset

pytestmark = [pytest.mark.eval, pytest.mark.judge]

JUDGE_PROMPT = """You check an assistant's answer against source passages.
List every factual claim in the ANSWER that is NOT supported by the PASSAGES. Ignore citation markers like [1],
greetings and statements about what the documents contain. Reply with JSON only:
{{"unsupported_claims": ["..."], "supported": true or false}}

PASSAGES:
{passages}

ANSWER:
{answer}"""

CASES = [pytest.param(c, id=c["id"]) for c in load_dataset("document_answers") if c.get("judge")]


@pytest.mark.parametrize("case", CASES)
def test_answer_is_supported_by_its_passages(case, admin, ollama):
    result = chat(admin, case["question"], case.get("history"))
    queries = [args.get("query", "") for name, args in result.tools if name == "search_documents"]
    assert queries, f"didn't search, nothing to judge. {result.summary()}"

    # The passages the model actually saw: re-run its own search queries (same filters, same ranking).
    passages = []
    for query in queries:
        passages += admin.get("/api/documents/search", params={"q": query, "k": settings.search_k}).json()
    text = "\n\n".join(f"[{p['source']} p.{p.get('page')}]\n{p['text']}" for p in passages)

    verdict = Client(host=settings.ollama_host).chat(
        model=settings.chat_model,
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(passages=text, answer=result.answer)}],
        format="json",
        think=False,
        options={"temperature": 0, "num_ctx": settings.num_ctx},
    )
    judged = json.loads(verdict.message.content)
    unsupported = judged.get("unsupported_claims") or []
    assert judged.get("supported") is True and not unsupported, f"unsupported claims: {unsupported}"
