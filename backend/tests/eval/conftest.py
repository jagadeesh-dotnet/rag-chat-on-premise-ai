"""Evaluation fixtures (signed-in clients against the running app) and the report written after every run."""

import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from app.config import settings
from tests.eval.helpers import API

ACCOUNTS_FILE = settings.data_dir / "test-accounts.local.json"
REPORTS = Path(__file__).parent / "reports"
AREAS = ("retrieval", "sql", "documents", "judge", "security")
_results: list[dict] = []


# --- fixtures -----------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def backend() -> dict:
    try:
        return httpx.get(f"{API}/api/health", timeout=10).json()
    except httpx.HTTPError:
        pytest.skip(f"backend not running at {API} (start uvicorn first)")


@pytest.fixture(scope="session")
def ollama(backend) -> None:
    if not backend.get("chat_model_ready"):
        pytest.skip("Ollama or the chat model isn't available")


@pytest.fixture(scope="session")
def accounts() -> dict[str, str]:
    if not ACCOUNTS_FILE.exists():
        pytest.skip("no test accounts: run `python -m app.auth.cli seed-test-users` first")
    return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def client_for(backend, accounts):
    """client_for('test-sales') -> a signed-in client (one per account, reused)."""
    clients: dict[str, httpx.Client] = {}

    def make(username: str) -> httpx.Client:
        if username not in clients:
            client = httpx.Client(base_url=API, timeout=300)
            response = client.post("/api/auth/login", json={"username": username, "password": accounts[username]})
            if response.status_code != 200:
                pytest.skip(f"can't sign in as {username} ({response.status_code}): re-run seed-test-users")
            clients[username] = client
        return clients[username]

    yield make
    for client in clients.values():
        client.close()


@pytest.fixture(scope="session")
def admin(client_for) -> httpx.Client:
    return client_for("test-admin")


SECURITY_RULES = [
    {"kind": "spreadsheet", "source": "", "table": "amazon_store_sales_data", "column": "region", "attribute": "region"},
    {"kind": "database", "source": "northwind", "table": "Customers", "column": "Country", "attribute": "country"},
]
SECURITY_ATTRIBUTES = {"test-sales": {"region": ["East"], "country": ["Germany"]}, "test-hr": {}}


@pytest.fixture(scope="session")
def security_setup(admin):
    """The row rules and attributes the security cases expect; whatever was there before is put back."""
    users = {u["username"]: u for u in admin.get("/api/admin/users").json()}
    before_rules = admin.get("/api/admin/rules").json()
    existing = {(r["kind"], r["table_name"].lower(), r["column_name"].lower()) for r in before_rules}
    added = []
    for rule in SECURITY_RULES:
        if (rule["kind"], rule["table"].lower(), rule["column"].lower()) not in existing:
            added.append(admin.post("/api/admin/rules", json=rule).json()["id"])
    before_attributes = {name: users[name]["attributes"] for name in SECURITY_ATTRIBUTES}
    for name, attributes in SECURITY_ATTRIBUTES.items():
        admin.patch(f"/api/admin/users/{users[name]['id']}", json={"attributes": attributes})
    yield
    for rule_id in added:
        admin.delete(f"/api/admin/rules/{rule_id}")
    for name, attributes in before_attributes.items():
        admin.patch(f"/api/admin/users/{users[name]['id']}", json={"attributes": attributes})


# --- report -------------------------------------------------------------------------------------------


def pytest_runtest_logreport(report):
    if "eval" not in report.keywords:
        return
    # the call phase, or setup when it didn't pass (a skip, or an error before the test ran)
    if report.when != "call" and not (report.when == "setup" and report.outcome != "passed"):
        return
    area = next((a for a in AREAS if a in report.keywords), "other")
    known = hasattr(report, "wasxfail")
    outcome = report.outcome
    if known:
        outcome = "fixed" if report.outcome == "passed" else "known"  # a known issue that now passes
    entry = {"test": report.nodeid, "area": area, "outcome": outcome, "seconds": round(report.duration, 2)}
    entry.update(dict(report.user_properties))
    if known:
        entry["detail"] = report.wasxfail
    elif report.outcome == "failed":
        crash = getattr(report.longrepr, "reprcrash", None)  # the assertion message, not just file:line
        entry["detail"] = (crash.message if crash else str(report.longrepr)).splitlines()[0][:300]
    elif report.outcome == "skipped" and isinstance(report.longrepr, tuple):
        entry["detail"] = report.longrepr[2]
    _results.append(entry)


def _summary(results: list[dict]) -> dict:
    areas: dict[str, dict] = defaultdict(lambda: {"passed": 0, "failed": 0, "known": 0, "fixed": 0, "skipped": 0})
    for r in results:
        areas[r["area"]][r["outcome"]] += 1
    for name, a in areas.items():
        ran = a["passed"] + a["fixed"] + a["failed"]
        a["score"] = round((a["passed"] + a["fixed"]) / ran, 3) if ran else None
        mine = [r for r in results if r["area"] == name]
        ranks = [r["rank"] for r in mine if "rank" in r]
        if ranks:  # rank 0 = not found in the top results
            a["recall_at_3"] = round(sum(0 < k <= 3 for k in ranks) / len(ranks), 3)
            a["mrr"] = round(statistics.mean(1 / k if k else 0 for k in ranks), 3)
        seconds = [r["answer_seconds"] for r in mine if "answer_seconds" in r]
        if seconds:
            a["median_answer_s"] = round(statistics.median(seconds), 1)
    return dict(sorted(areas.items(), key=lambda item: AREAS.index(item[0]) if item[0] in AREAS else 99))


def pytest_sessionfinish(session, exitstatus):
    if not _results:
        return
    REPORTS.mkdir(exist_ok=True)
    now = datetime.now()
    summary = _summary(_results)
    # A run of a few chosen tests (-k, or test ids) isn't a full evaluation: it's recorded as partial and never
    # used as the baseline for the Change column.
    options = session.config.option
    partial = (
        bool(options.keyword)  # -k
        or options.markexpr.strip() != "eval"  # only some areas, e.g. -m "eval and sql"
        or any("::" in arg or arg.endswith(".py") for arg in session.config.args)  # chosen tests or files
        or all(r["outcome"] == "skipped" for r in _results)  # nothing ran (backend or Ollama down)
    )
    history = REPORTS / "history.jsonl"
    previous = None
    if history.exists():
        runs = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines() if line.strip()]
        previous = next((r for r in reversed(runs) if not r.get("partial")), None)
    run = {
        "started": now.isoformat(timespec="seconds"),
        "model": settings.chat_model,
        "partial": partial,
        "summary": summary,
    }
    with history.open("a", encoding="utf-8") as f:
        f.write(json.dumps(run) + "\n")
    (REPORTS / f"eval-{now:%Y%m%d-%H%M%S}.json").write_text(
        json.dumps({**run, "results": _results}, indent=2), encoding="utf-8"
    )

    lines = [
        f"# Evaluation report - {now:%Y-%m-%d %H:%M} ({settings.chat_model}){' - PARTIAL RUN' if partial else ''}",
        "",
        "Score = passed / (passed + failed). Known issues are tracked failures and don't count.",
        "",
        "| Area | Passed | Failed | Known issues | Skipped | Score | Change | Extra |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, a in summary.items():
        before = ((previous or {}).get("summary", {}).get(name) or {}).get("score")
        change = "" if before is None or a["score"] is None else f"{(a['score'] - before) * 100:+.0f} pts"
        extra = ", ".join(f"{k} {a[k]}" for k in ("recall_at_3", "mrr", "median_answer_s") if k in a)
        score = "-" if a["score"] is None else f"{a['score']:.0%}"
        passed = a["passed"] + a["fixed"]
        lines.append(f"| {name} | {passed} | {a['failed']} | {a['known']} | {a['skipped']} | {score} | {change} | {extra} |")
    for title, outcome in (("Failures", "failed"), ("Known issues", "known"), ("Known issues that now pass", "fixed")):
        entries = [r for r in _results if r["outcome"] == outcome]
        if entries:
            lines += ["", f"## {title}", ""] + [f"- `{r['test']}`: {r.get('detail', '')}" for r in entries]
    (REPORTS / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter:
        reporter.write_sep("=", "evaluation summary")
        for line in lines[4:]:
            reporter.write_line(line)
        reporter.write_line(f"report: {REPORTS / 'latest.md'}")
