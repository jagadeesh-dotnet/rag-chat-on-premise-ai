"""Shared test helpers: a clean RagChatAppTest database per test, users, and signed-in clients."""

import re

import pyodbc
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import service
from app.auth.db import connect_as_administrator
from app.config import PROJECT_ROOT, settings
from app.databases.connection import connection_string
from app.routers import auth

PASSWORD = "correct horse battery"
TEST_DATABASE = "RagChatAppTest"
_TABLES = ("sessions", "user_attributes", "user_roles", "role_grants", "row_rules", "audit", "users")


@pytest.fixture(scope="session")
def app_test_database() -> str:
    """Create RagChatAppTest from the real setup script (same tables, same chat_app permissions)."""
    script = (PROJECT_ROOT / "db-scripts" / "create_app_database.sql").read_text(encoding="utf-8")
    script = script.replace("RagChatApp", TEST_DATABASE)
    try:
        conn = pyodbc.connect(connection_string("master"), autocommit=True, timeout=5)
    except pyodbc.Error:
        pytest.skip("SQL Server is not reachable: account tests need it")
    for batch in re.split(r"^\s*GO\s*$", script, flags=re.MULTILINE):
        if batch.strip():
            conn.execute(batch)
    conn.close()
    return TEST_DATABASE


@pytest.fixture
def isolated(tmp_path, monkeypatch, app_test_database):
    """Empty account tables and a fresh conversation database for this test."""
    monkeypatch.setattr(settings, "app_database", app_test_database)
    monkeypatch.setattr(settings, "chat_db_path", tmp_path / "chat.db")
    with connect_as_administrator() as db:
        for table in _TABLES:
            db.execute(f"DELETE FROM {table}")
        db.execute("DELETE FROM roles WHERE builtin = 0")
    return tmp_path


def make_client(*routers) -> TestClient:
    """An app with the auth router plus the given ones (no Qdrant or Ollama needed)."""
    app = FastAPI()
    for module in (auth, *routers):
        app.include_router(module.router)
    return TestClient(app)


def add_user(username: str, roles: list[str], password: str = PASSWORD, must_change: bool = False) -> int:
    return service.create_user(None, username, username, password, roles, must_change=must_change)


def signed_in(client: TestClient, username: str, password: str = PASSWORD) -> TestClient:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client
