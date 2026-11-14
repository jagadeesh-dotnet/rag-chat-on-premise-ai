"""The chat agent: the model decides when to search, our code runs the search, the model answers with citations."""

import asyncio
import re
from collections.abc import AsyncIterator

from ollama import AsyncClient

from app.config import settings
from app.schemas import ChatMessage
from app.tools import documents

SYSTEM_PROMPT = """You are a helpful assistant that answers questions about the user's own documents \
(policies, standards, manuals, papers).

Rules:
- For any question the documents could answer, call search_documents first - also when it was discussed \
earlier in the conversation, so the answer can be cited. Don't search for greetings, thanks or questions \
about yourself.
- Write the search query as a standalone question: resolve "it", "that" or "again" from the conversation, \
and keep document names and clause or control numbers.
- Answer only from the passages returned. Cite every fact with its passage number in square brackets, \
like [1] or [2][3]. Never cite a number that wasn't returned.
- If the passages don't contain the answer, say you couldn't find it in the documents. Don't make up an answer.
- Say where something comes from: a requirement of a standard (e.g. ISO 27001 control A.6.7) is not the \
organisation's own policy.
- Be concise."""

_client = AsyncClient(host=settings.ollama_host)
_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")  # [1], [2, 3]


def strip_citations(text: str) -> str:
    """Remove [n] markers: old numbers in the history would be copied into new answers."""
    return re.sub(r"\s?" + _CITATION.pattern, "", text)


def cited_numbers(text: str) -> set[int]:
    return {int(n) for group in _CITATION.findall(text) for n in group.split(",")}


def _history(messages: list[ChatMessage]) -> list[dict]:
    return [
        {"role": m.role, "content": strip_citations(m.content) if m.role == "assistant" else m.content}
        for m in messages
    ]


async def _run_tool(name: str, args: dict, first_number: int) -> tuple[str, list[dict]]:
    """Run one tool call. Problems go back to the model as the result, so it can recover."""
    if name != documents.NAME:
        return f"Error: unknown tool {name!r}. The only tool is {documents.NAME}.", []
    query = args.get("query")
    if not isinstance(query, str) or len(query.strip()) < 2:
        return "Error: 'query' must be a non-empty string.", []
    results = await asyncio.to_thread(documents.run_search, query.strip())  # sync code, off the event loop
    return documents.format_results(results, first_number)


async def run_agent(history: list[ChatMessage]) -> AsyncIterator[dict]:
    """Yield events: tool_call, tool_result, token, sources."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *_history(history)]
    passages: dict[int, dict] = {}  # every passage shown to the model in this answer, by number
    answer = ""

    for round_number in range(settings.max_tool_rounds + 1):
        last_round = round_number == settings.max_tool_rounds
        stream = await _client.chat(
            model=settings.chat_model,
            messages=messages,
            tools=None if last_round else [documents.TOOL],  # last round: no tools, so it must answer
            stream=True,
            think=settings.think,
            options={"num_ctx": settings.num_ctx},
        )
        content, calls = "", []
        async for chunk in stream:
            if chunk.message.content:
                content += chunk.message.content
                yield {"type": "token", "content": chunk.message.content}
            if chunk.message.tool_calls:  # may arrive in any chunk: collect them all
                calls.extend(chunk.message.tool_calls)
        answer += content

        if not calls:
            break

        # The model's request must be in the history before the results, or it loses track.
        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"function": {"name": c.function.name, "arguments": dict(c.function.arguments or {})}}
                    for c in calls
                ],
            }
        )
        for call in calls:
            name, args = call.function.name, dict(call.function.arguments or {})
            yield {"type": "tool_call", "name": name, "arguments": args}
            text, found = await _run_tool(name, args, first_number=len(passages) + 1)
            passages.update({p["number"]: p for p in found})
            messages.append({"role": "tool", "tool_name": name, "content": text})
            yield {"type": "tool_result", "name": name, "count": len(found)}

    cited = sorted(n for n in cited_numbers(answer) if n in passages)
    if cited:
        yield {"type": "sources", "items": [passages[n] for n in cited]}
