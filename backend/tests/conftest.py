"""Shared test helpers: a throwaway app.db / chat.db per test, users, and signed-in clients."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import service
from app.config import settings
from app.routers import auth

PASSWORD = "correct horse battery"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Fresh, empty account and conversation databases for this test."""
    monkeypatch.setattr(settings, "app_db_path", tmp_path / "app.db")
    monkeypatch.setattr(settings, "chat_db_path", tmp_path / "chat.db")
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
