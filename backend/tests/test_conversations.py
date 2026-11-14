import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import conversations


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "chat_db_path", tmp_path / "chat.db")
    app = FastAPI()
    app.include_router(conversations.router)  # only this router: no Qdrant or Ollama needed
    return TestClient(app)


MESSAGES = [
    {"role": "user", "content": "Which category sold most in the spreadsheet?"},
    {
        "role": "assistant",
        "content": "Office Supplies [1].",
        "steps": ["Queried spreadsheets (1 rows)"],
        "tables": [{"sql": "SELECT 1", "columns": ["category"], "rows": [["Office Supplies"]], "truncated": False}],
    },
]


def test_save_list_get_rename_delete(client):
    cid = str(uuid.uuid4())
    assert client.put(f"/api/conversations/{cid}", json={"messages": MESSAGES}).status_code == 200

    listed = client.get("/api/conversations").json()
    assert [c["id"] for c in listed] == [cid]
    assert listed[0]["title"] == "Which category sold most in the spreadsheet?"

    saved = client.get(f"/api/conversations/{cid}").json()
    assert saved["messages"] == MESSAGES  # display data (steps, tables) survives the round trip

    assert client.patch(f"/api/conversations/{cid}", json={"title": "Sales"}).json()["title"] == "Sales"
    client.put(f"/api/conversations/{cid}", json={"messages": MESSAGES + MESSAGES})
    assert client.get("/api/conversations").json()[0]["title"] == "Sales"  # saving keeps a renamed title

    assert client.delete(f"/api/conversations/{cid}").status_code == 204
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_newest_first(client):
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    client.put(f"/api/conversations/{first}", json={"messages": MESSAGES})
    client.put(f"/api/conversations/{second}", json={"messages": MESSAGES})
    client.patch(f"/api/conversations/{first}", json={"title": "touched later"})
    assert [c["id"] for c in client.get("/api/conversations").json()] == [first, second]


def test_long_titles_are_shortened(client):
    cid = str(uuid.uuid4())
    client.put(f"/api/conversations/{cid}", json={"messages": [{"role": "user", "content": "word " * 40}]})
    title = client.get("/api/conversations").json()[0]["title"]
    assert len(title) == 60 and title.endswith("...")


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/conversations/not-a-uuid", None),
        ("put", f"/api/conversations/{uuid.uuid4()}", {"messages": [{"role": "system", "content": "x"}]}),
        ("patch", f"/api/conversations/{uuid.uuid4()}", {"title": ""}),
    ],
)
def test_invalid_requests_are_rejected(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 422


def test_unknown_conversation_is_404(client):
    cid = uuid.uuid4()
    assert client.patch(f"/api/conversations/{cid}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/conversations/{cid}").status_code == 404
