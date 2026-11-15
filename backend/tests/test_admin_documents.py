"""Admin Documents tab: file status (new / changed / indexed / missing) and audited index runs."""

import pytest

from app.config import settings
from app.ingest.indexer import IndexBusyError, file_hash
from app.routers import admin, documents
from tests.conftest import add_user, make_client, signed_in


class FakeStore:
    def __init__(self, hashes: dict[str, str], counts: dict[str, int]) -> None:
        self.hashes, self.counts = hashes, counts

    def file_hashes(self) -> dict[str, str]:
        return self.hashes

    def chunk_counts(self) -> dict[str, int]:
        return self.counts


@pytest.fixture
def docs(isolated, monkeypatch):
    folder = isolated / "docs"
    (folder / "hr").mkdir(parents=True)
    (folder / "same.pdf").write_bytes(b"unchanged content")
    (folder / "edited.docx").write_bytes(b"new content")
    (folder / "hr" / "fresh.docx").write_bytes(b"never indexed")
    (folder / "~$lock.docx").write_bytes(b"Word lock file")  # skipped, like the indexer does
    monkeypatch.setattr(settings, "docs_dir", folder)
    store = FakeStore(
        hashes={"same.pdf": file_hash(folder / "same.pdf"), "edited.docx": "old hash", "deleted.pdf": "x"},
        counts={"same.pdf": 3, "edited.docx": 2, "deleted.pdf": 1},
    )
    monkeypatch.setattr(admin, "get_store", lambda: store)
    return folder


def test_status_compares_disk_with_the_index(docs):
    add_user("root", ["admin"])
    body = signed_in(make_client(admin), "root").get("/api/admin/documents").json()
    status = {f["source"]: (f["status"], f["chunks"]) for f in body["files"]}
    assert status == {
        "same.pdf": ("indexed", 3),
        "edited.docx": ("changed", 2),
        "hr/fresh.docx": ("new", 0),
        "deleted.pdf": ("missing", 1),
    }
    fresh = next(f for f in body["files"] if f["source"] == "hr/fresh.docx")
    assert fresh["size"] == len(b"never indexed") and fresh["modified"]


def test_documents_and_indexing_need_the_admin_role(docs):
    add_user("alice", [])
    client = signed_in(make_client(admin, documents), "alice")
    assert client.get("/api/admin/documents").status_code == 403
    assert client.post("/api/documents/index").status_code == 403


def test_index_run_is_audited(docs, monkeypatch):
    summary = {"added": ["hr/fresh.docx"], "updated": ["edited.docx"], "removed": ["deleted.pdf"],
               "unchanged": ["same.pdf"], "errors": {}, "chunks": 7, "seconds": 1.5}
    calls = []
    monkeypatch.setattr(documents, "index_documents", lambda force: calls.append(force) or summary)
    add_user("root", ["admin"])
    root = signed_in(make_client(admin, documents), "root")

    assert root.post("/api/documents/index", params={"force": "true"}).json() == summary
    assert calls == [True]
    entry = next(a for a in root.get("/api/admin/audit").json() if a["action"] == "documents_indexed")
    assert entry["username"] == "root"
    assert entry["detail"] == "added 1, updated 1, removed 1, unchanged 1, errors 0, chunks 7, 1.5 s, full re-index"


def test_second_run_while_indexing_gets_409_and_no_audit(docs, monkeypatch):
    def busy(force):
        raise IndexBusyError("indexing is already running")

    monkeypatch.setattr(documents, "index_documents", busy)
    add_user("root", ["admin"])
    root = signed_in(make_client(admin, documents), "root")
    response = root.post("/api/documents/index")
    assert response.status_code == 409
    assert response.json()["detail"] == "indexing is already running"
    assert not [a for a in root.get("/api/admin/audit").json() if a["action"] == "documents_indexed"]
