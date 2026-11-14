"""Loading datasets, talking to the running app, and grading answers."""

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
import yaml

API = os.environ.get("EVAL_API", "http://localhost:8000")
DATASETS = Path(__file__).parent / "datasets"

# How an answer says "I couldn't / can't": used for refusal checks.
REFUSAL = re.compile(
    r"(couldn'?t|could not|can'?t|cannot|unable to|don'?t have|do not have|no access|not available|not found|"
    r"no (relevant )?information|isn'?t (in|available)|not (in|part of) the)",
    re.IGNORECASE,
)
MONEY_OR_BIG_NUMBER = re.compile(r"\$\s?\d|\d{1,3}(,\d{3})+(\.\d+)?|\d{4,}\.\d+")


def load_dataset(name: str) -> list[dict]:
    return yaml.safe_load((DATASETS / f"{name}.yaml").read_text(encoding="utf-8"))


def params(name: str) -> list:
    """Cases as pytest params; a case with known_issue runs as xfail (reported, not counted against the score)."""
    cases = []
    for case in load_dataset(name):
        marks = [pytest.mark.xfail(reason=case["known_issue"], strict=False)] if case.get("known_issue") else []
        cases.append(pytest.param(case, id=case["id"], marks=marks))
    return cases


@dataclass
class ChatResult:
    answer: str = ""
    tools: list[tuple[str, dict]] = field(default_factory=list)
    tool_ok: list[bool] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0

    @property
    def rows(self) -> list[list]:
        return [row for table in self.tables for row in table["rows"]]

    @property
    def tool_names(self) -> list[str]:
        return [name for name, _ in self.tools]

    def summary(self) -> str:
        """For assertion messages: what the agent did and said."""
        return f"tools={self.tool_names} sources={[(s['source'], s.get('page')) for s in self.sources]} answer={self.answer[:200]!r}"


def chat(client: httpx.Client, question: str, history: list[dict] | None = None) -> ChatResult:
    messages = [*(history or []), {"role": "user", "content": question}]
    result = ChatResult()
    started = time.perf_counter()
    with client.stream("POST", "/api/chat", json={"messages": messages}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            kind = event["type"]
            if kind == "token":
                result.answer += event["content"]
            elif kind == "tool_call":
                result.tools.append((event["name"], event["arguments"]))
            elif kind == "tool_result":
                result.tool_ok.append(event.get("ok", True))
            elif kind == "table":
                result.tables.append(event)
            elif kind == "sources":
                result.sources = event["items"]
            elif kind == "error":
                result.error = event["message"]
    result.seconds = round(time.perf_counter() - started, 2)
    return result


def cells_match(expected, actual) -> bool:
    """Numbers within 0.01 (or 0.01 %); text equal or contained, case-insensitive."""
    if expected is None or actual is None:
        return expected is actual
    if isinstance(expected, int | float) and not isinstance(expected, bool):
        try:
            value = float(actual)
        except (TypeError, ValueError):
            return False
        return abs(value - expected) <= max(0.01, abs(expected) * 1e-4)
    e, a = str(expected).strip().lower(), str(actual).strip().lower()
    return e == a or (len(e) >= 3 and e in a)


def row_found(expected: list, rows: list[list]) -> bool:
    """Every value of the expected row appears in one of the model's rows (extra columns allowed).

    A row's text values joined with spaces count as one more value, so a name split over two columns
    (['Abraham', 'Bennet']) still matches 'Abraham Bennet'.
    """
    for row in rows:
        values = [*row, " ".join(str(v) for v in row if isinstance(v, str))]
        if all(any(cells_match(e, a) for a in values) for e in expected):
            return True
    return False


def cited(result: ChatResult, source: str, page: int | None = None) -> bool:
    return any(s["source"] == source and (page is None or s.get("page") == page) for s in result.sources)
