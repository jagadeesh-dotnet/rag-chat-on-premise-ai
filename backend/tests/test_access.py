"""Permissions: what each role can reach, checked on the server."""

import pytest

from app.auth import service
from app.auth.access import Access
from app.routers import databases, tables
from app.tools import documents
from tests.conftest import add_user, make_client, signed_in


def access(**grants) -> Access:
    return Access(user_id=1, username="u", display_name="u", **{k: frozenset(v) for k, v in grants.items()})


@pytest.mark.parametrize(
    ("folders", "source", "allowed"),
    [
        ({"hr"}, "hr/handbook.docx", True),
        ({"hr"}, "hr/2024/salaries.xlsx", True),  # subfolders are included
        ({"hr"}, "hrx/file.pdf", False),  # not a prefix match on the name
        ({"hr"}, "iso27001.pdf", False),
        ({"/"}, "iso27001.pdf", True),  # "/" = files directly in data/docs
        ({"/"}, "hr/handbook.docx", False),
        ({"*"}, "hr/handbook.docx", True),
        (set(), "iso27001.pdf", False),
    ],
)
def test_folder_grants(folders, source, allowed):
    assert access(folders=folders).can_read_document(source) is allowed


def test_admin_reads_everything():
    assert Access(user_id=1, username="a", display_name="a", is_admin=True).can_read_document("hr/x.docx")


def test_search_is_limited_to_permitted_files(monkeypatch):
    class FakeStore:
        def chunk_counts(self):
            return {"hr/handbook.docx": 3, "iso27001.pdf": 66, "Azure.docx": 1}

    monkeypatch.setattr(documents, "get_store", lambda: FakeStore())
    assert sorted(documents.allowed_sources(access(folders={"/"}))) == ["Azure.docx", "iso27001.pdf"]
    assert documents.allowed_sources(access(folders={"hr"})) == ["hr/handbook.docx"]
    assert documents.allowed_sources(access()) == []


@pytest.fixture
def roles(isolated):
    service.save_role(None, "sales", "", {"folder": ["/"], "spreadsheet": ["*"], "database": ["northwind"]})
    service.save_role(None, "hr", "", {"folder": ["hr"], "spreadsheet": [], "database": []})
    add_user("sam", ["sales"])
    add_user("helen", ["hr"])


def test_spreadsheets_follow_the_role(roles):
    sam = signed_in(make_client(tables), "sam")
    helen = signed_in(make_client(tables), "helen")
    assert sam.get("/api/tables").json()["tables"]  # sales sees the spreadsheet
    assert helen.get("/api/tables").json()["tables"] == []
    table = sam.get("/api/tables").json()["tables"][0]["name"]
    assert sam.post("/api/tables/query", json={"sql": f"SELECT COUNT(*) FROM {table}"}).status_code == 200
    denied = helen.post("/api/tables/query", json={"sql": f"SELECT COUNT(*) FROM {table}"})
    assert denied.status_code == 400 and "Unknown table" in denied.json()["detail"]  # looks like it doesn't exist


def test_databases_follow_the_role(roles):
    helen = signed_in(make_client(databases), "helen")
    assert helen.get("/api/databases").json() == []
    assert helen.post("/api/databases/northwind/query", json={"sql": "SELECT 1"}).status_code == 404
    sam = signed_in(make_client(databases), "sam")
    assert sam.post("/api/databases/pubs/query", json={"sql": "SELECT 1"}).status_code == 404  # not granted
    assert [d["name"] for d in sam.get("/api/databases").json()] == ["northwind"]


def test_everything_needs_sign_in(isolated):
    client = make_client(tables, databases)
    assert client.get("/api/tables").status_code == 401
    assert client.get("/api/databases").status_code == 401
