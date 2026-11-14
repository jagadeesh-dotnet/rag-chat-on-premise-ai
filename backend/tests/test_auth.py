import hashlib

import pyodbc
import pytest

from app.auth.db import connect, connect_as_administrator
from app.auth.passwords import PasswordPolicyError, check_policy
from app.config import settings
from app.routers import admin, conversations
from tests.conftest import PASSWORD, add_user, make_client, signed_in


@pytest.mark.parametrize("password", ["short", " leading-space-123", "trailing-space-123 ", "x" * 73, "é" * 37])
def test_password_policy_rejects(password):
    with pytest.raises(PasswordPolicyError):
        check_policy(password)


def test_login_sets_a_safe_cookie_and_stores_only_hashes(isolated):
    add_user("alice", [])
    client = make_client()
    response = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie

    token = client.cookies.get(settings.session_cookie)
    with connect_as_administrator() as db:
        assert db.scalar("SELECT password_hash FROM users").startswith("$2b$")  # bcrypt
        stored = [r["token_hash"] for r in db.all("SELECT token_hash FROM sessions")]
        audit = str(db.all("SELECT * FROM audit"))
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]  # the token itself is never stored
    assert PASSWORD not in audit


def test_the_app_cannot_change_or_delete_audit_entries(isolated):
    with connect() as db:  # as chat_app, like the running app
        db.execute("INSERT INTO audit (at, username, action) VALUES (SYSUTCDATETIME(), 'x', 'test')")
    for sql in ("UPDATE audit SET detail = 'edited'", "DELETE FROM audit", "DROP TABLE audit"):
        with pytest.raises(pyodbc.Error, match="(?i)denied|permission"), connect() as db:
            db.execute(sql)


def test_wrong_password_and_unknown_user_look_the_same(isolated):
    add_user("alice", [])
    client = make_client()
    wrong = client.post("/api/auth/login", json={"username": "alice", "password": "wrong password!"})
    unknown = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong password!"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_lockout_after_five_failures(isolated):
    add_user("alice", [])
    client = make_client()
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "alice", "password": "nope nope nope"}).status_code == 401
    locked = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert locked.status_code == 429  # even the right password is refused while locked
    assert int(locked.headers["retry-after"]) > 0


def test_temporary_password_must_be_changed_first(isolated):
    add_user("bob", [], must_change=True)
    client = signed_in(make_client(conversations), "bob")
    assert client.get("/api/auth/me").json()["must_change_password"] is True
    blocked = client.get("/api/conversations")
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"

    bad = client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"})
    assert bad.status_code == 400
    ok = client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "a new long password"})
    assert ok.status_code == 204
    assert client.get("/api/conversations").status_code == 200


def test_logout_ends_the_session(isolated):
    add_user("alice", [])
    client = signed_in(make_client(), "alice")
    token = client.cookies.get(settings.session_cookie)
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set(settings.session_cookie, token)  # even if the old cookie is replayed
    assert client.get("/api/auth/me").status_code == 401


def test_admin_endpoints_need_the_admin_role(isolated):
    add_user("alice", [])
    assert signed_in(make_client(admin), "alice").get("/api/admin/users").status_code == 403


def test_admin_manages_users_roles_and_sessions(isolated):
    add_user("root", ["admin"])
    root = signed_in(make_client(admin), "root")

    role = {"description": "HR", "grants": {"folder": ["hr/"], "spreadsheet": [], "database": []}}
    assert root.put("/api/admin/roles/hr", json=role).status_code == 200
    created = root.post("/api/admin/users", json={"username": "carol", "temporary_password": "temporary pass 1", "roles": ["hr"]})
    assert created.status_code == 201
    carol_id = created.json()["id"]

    carol = signed_in(make_client(), "carol", "temporary pass 1")
    me = carol.get("/api/auth/me").json()
    assert me["must_change_password"] is True and me["folders"] == ["hr"]  # "hr/" stored as "hr"

    assert root.patch(f"/api/admin/users/{carol_id}", json={"is_active": False}).status_code == 200
    assert carol.get("/api/auth/me").status_code == 401  # deactivated: signed out at once

    actions = [a["action"] for a in root.get("/api/admin/audit").json()]
    assert {"role_saved", "user_created", "user_updated", "login_ok"} <= set(actions)


def test_admin_cannot_lock_themselves_out(isolated):
    root_id = add_user("root", ["admin"])
    root = signed_in(make_client(admin), "root")
    assert root.patch(f"/api/admin/users/{root_id}", json={"is_active": False}).status_code == 400
    assert root.patch(f"/api/admin/users/{root_id}", json={"roles": []}).status_code == 400
    assert root.delete("/api/admin/roles/admin").status_code == 400


def test_last_active_admin_cannot_be_removed(isolated):
    add_user("root", ["admin"])
    other_id = add_user("other", ["admin"])
    root = signed_in(make_client(admin), "root")
    assert root.patch(f"/api/admin/users/{other_id}", json={"roles": []}).status_code == 200  # root is still admin
