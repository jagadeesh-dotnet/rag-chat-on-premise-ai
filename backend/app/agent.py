"""The chat agent: the model decides which tool to use, our code runs it, the model answers.

Tools: search_documents (passages, cited as [n]), query_tables (SQL over spreadsheets), get_schema and
run_sql (read-only T-SQL on SQL Server databases). Query results are shown as tables.
"""

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ollama import AsyncClient

from app.auth.access import Access
from app.config import settings
from app.databases.query import visible_databases
from app.schemas import ChatMessage
from app.tables.catalog import get_catalog
from app.tools import databases, documents, tables

# No real source names in here: this text goes to every user, and naming a database or spreadsheet would tell
# users without access that it exists (and gave the model a name to invent an answer around).
SYSTEM_PROMPT = """You are a helpful assistant that answers questions from the user's own files. \
Never answer a factual question from your own knowledge: unless it is small talk (greetings, thanks, \
questions about yourself), use a tool first.

You can only use the tools you have and the sources listed in this prompt - they are exactly what this user \
is allowed to see. If a question needs data you have no tool or source for, say you don't have access to that \
information. Never guess or invent numbers, names or citations.

Rules for documents (search_documents):
- Use search_documents for anything written in documents: policies, rules, procedures, HR topics such as \
leave, standards, manuals, papers - also when it was discussed earlier in the conversation, so the answer can \
be cited.
- Write the search query as a standalone question: resolve "it", "that" or "again" from the conversation, \
and keep document names and clause or control numbers.
- Answer only from the passages returned. Cite every fact with its passage number in square brackets, \
like [1] or [2][3]. Never cite a number that wasn't returned.
- If the passages don't contain the answer, say you couldn't find it in the documents. Don't make up an answer.
- Say where something comes from: a requirement of a standard (a control or clause it lists) is not the \
organisation's own policy.
- If several sources could answer (e.g. a spreadsheet and a database both have products, categories and \
sales), ask the user which one they mean before querying - unless the question names the source. When you \
answer from data, start by naming the database or spreadsheet that the tool result says it came from.
- Be concise."""

SPREADSHEET_PROMPT = """

Spreadsheet tables (query them with query_tables, DuckDB SQL):
{schema}

Rules for spreadsheets (query_tables):
- Use query_tables only for numbers computed from these spreadsheet tables: totals, counts, averages, rankings, \
trends. Questions about the SQL Server databases below use get_schema/run_sql instead.
- Run a new query for every number you report, even if earlier answers contain related numbers: never add up \
or recalculate numbers from previous answers yourself.
- Rows are often order lines, not orders: count orders, customers or products with COUNT(DISTINCT id_column), \
never COUNT(*).
- Show names, not IDs (a name column instead of an ID column). For "top N" use ORDER BY ... DESC LIMIT N.
- Group by month with strftime(date_column, '%Y-%m') and ORDER BY it ascending. Round money with ROUND(x, 2).
- If the data has no column for what was asked, say so; don't guess.
- If a query fails, read the error and fix the SQL.
- The result table is shown to the user automatically: state the key numbers in words, don't repeat the table."""

DATABASE_PROMPT = """

SQL Server databases (use get_schema, then run_sql with T-SQL):
{databases}

Rules for databases:
- Use them for questions about their business data (customers, orders, products, employees, books, authors...).
- Always call get_schema for a database before writing SQL for it, and use only the tables and columns it shows.
- T-SQL: TOP n instead of LIMIT; put brackets around names with spaces, like [Order Details].
- Show names, not IDs: join to the table that has the name.
- For "top N" with joins, rank first in a CTE (aggregate on the IDs, TOP N), then join the names onto those \
N rows - joining first can multiply rows and inflate totals.
- Use the formulas from the notes (e.g. revenue). If a query fails, read the error and fix the SQL.
- The result table is shown to the user automatically: state the key numbers in words, don't repeat the table."""

FOLLOW_UP_REMINDER = "\n\n(Look this up with a tool; don't guess, and don't reuse numbers from earlier answers.)"

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


async def _search_hint(history: list[ChatMessage], access: Access) -> str:
    """Pre-search with the latest question. If the documents have related passages, say where.

    A rule alone ("never answer from your own knowledge") isn't enough: for questions that sound general,
    like "Compare Azure Repos with GitHub", the model answers from memory. Naming the files works.
    """
    question = next((m.content for m in reversed(history) if m.role == "user"), "")
    if len(question.strip()) < 3:
        return ""
    hits = await asyncio.to_thread(documents.run_search, question, access)  # only permitted files
    files = list(dict.fromkeys(h["source"] for h in hits))  # unique, best first
    if not files:
        return ""
    return (
        f"\n\nHint: a quick search for the latest question found related passages in {', '.join(files)}. "
        "Call search_documents and answer from those passages."
    )


@dataclass
class ToolOutcome:
    text: str  # what the model reads
    passages: list[dict] = field(default_factory=list)  # search results (for citations)
    table: dict | None = None  # query result (shown in the UI)
    count: int = 0  # for the UI step line: passages, rows or tables

    def __post_init__(self) -> None:
        self.count = self.count or (len(self.table["rows"]) if self.table else len(self.passages))


def _argument(args: dict, key: str) -> str | None:
    value = args.get(key)
    return value.strip() if isinstance(value, str) and len(value.strip()) >= 2 else None


async def _run_tool(
    name: str, args: dict, first_number: int, allowed: set[str], access: Access
) -> ToolOutcome:
    """Run one tool call. Problems go back to the model as the result, so it can recover."""
    if name not in allowed:
        return ToolOutcome(f"Error: unknown tool {name!r}. Available: {', '.join(sorted(allowed))}.")
    if name == documents.NAME:
        query = _argument(args, "query")
        if query is None:
            return ToolOutcome("Error: 'query' must be a non-empty string.")
        results = await asyncio.to_thread(
            documents.run_search, query, access
        )  # sync code, off the event loop
        text, passages = documents.format_results(results, first_number)
        return ToolOutcome(text, passages=passages)
    if name in (databases.SCHEMA_NAME, databases.SQL_NAME):
        database = _argument(args, "database")
        if database is None:
            return ToolOutcome("Error: 'database' is required (a name from the list in the system prompt).")
        if name == databases.SCHEMA_NAME:
            text, table_count = await asyncio.to_thread(databases.run_get_schema, database, access)
            return ToolOutcome(text, count=table_count)
    sql = _argument(args, "sql")
    if sql is None:
        return ToolOutcome("Error: 'sql' must be a non-empty SQL query.")
    if name == databases.SQL_NAME:
        text, table = await asyncio.to_thread(databases.run_sql, database, sql, access)
    else:
        text, table = await asyncio.to_thread(tables.run_query, sql, access)
    return ToolOutcome(text, table=table)


async def run_agent(history: list[ChatMessage], access: Access) -> AsyncIterator[dict]:
    """Yield events: tool_call, tool_result, table, token, sources.

    The model only learns about sources this user may use: tools, table schemas and databases it may not
    use aren't in the prompt at all, and every tool call is checked again with `access`.
    """
    catalog = get_catalog()
    await asyncio.to_thread(catalog.refresh)  # reloads only if a spreadsheet changed
    spreadsheets = tables.allowed_tables(access)
    has_tables = bool(catalog.visible(spreadsheets))
    has_databases = bool(visible_databases(access))
    # Every user gets every tool (their descriptions name no sources). A user without spreadsheet access gets
    # "no access" back from query_tables; without the tool, the model invented an answer instead.
    tools = [documents.TOOL, tables.TOOL, databases.SCHEMA_TOOL, databases.SQL_TOOL]
    allowed = {t["function"]["name"] for t in tools}
    prompt = SYSTEM_PROMPT
    prompt += SPREADSHEET_PROMPT.format(schema=catalog.schema_text(spreadsheets)) if has_tables else ""
    prompt += DATABASE_PROMPT.format(databases=databases.database_list(access)) if has_databases else ""
    prompt += await _search_hint(history, access)

    messages = [{"role": "system", "content": prompt}, *_history(history)]
    if messages[-1]["role"] == "user":
        # Without this the model reused numbers from earlier answers (follow-ups) or invented them (questions
        # about data the user can't access). Rules in the system prompt didn't help; words in the user's own
        # message did (measured 3/3; small talk still uses no tool). Only the copy sent to the model changes.
        messages[-1] = {"role": "user", "content": messages[-1]["content"] + FOLLOW_UP_REMINDER}
    passages: dict[int, dict] = {}  # every passage shown to the model in this answer, by number
    answer = ""

    for round_number in range(settings.max_tool_rounds + 1):
        last_round = round_number == settings.max_tool_rounds
        stream = await _client.chat(
            model=settings.chat_model,
            messages=messages,
            tools=None if last_round else tools,  # last round: no tools, so it must answer
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
            outcome = await _run_tool(name, args, len(passages) + 1, allowed, access)
            passages.update({p["number"]: p for p in outcome.passages})
            messages.append({"role": "tool", "tool_name": name, "content": outcome.text})
            ok = not outcome.text.startswith("Error")
            yield {"type": "tool_result", "name": name, "count": outcome.count, "ok": ok}
            if outcome.table:
                yield outcome.table

    cited = sorted(n for n in cited_numbers(answer) if n in passages)
    if cited:
        yield {"type": "sources", "items": [passages[n] for n in cited]}
