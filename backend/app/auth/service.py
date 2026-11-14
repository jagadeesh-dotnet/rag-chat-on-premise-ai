"""Accounts: login with lockout, sessions, users, roles and grants. Every change is written to the audit log."""

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from app.auth import passwords
from app.auth.db import ADMIN_ROLE, connect, now
from app.config import settings

GRANT_KINDS = ("folder", "spreadsheet", "database")


class LoginLocked(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("locked")
        self.retry_after = retry_after  # seconds


class AccountError(ValueError):
    """A request that breaks a rule (e.g. removing the last admin). The message is shown to the admin."""


# --- audit -------------------------------------------------------------------------------------------


def audit(
    conn: sqlite3.Connection,
    actor: dict | None,
    action: str,
    detail: str = "",
    username: str = "",
) -> None:
    conn.execute(
        "INSERT INTO audit (at, user_id, username, action, detail) VALUES (?, ?, ?, ?, ?)",
        (
            now(),
            actor["id"] if actor else None,
            actor["username"] if actor else username,
            action,
            detail,
        ),
    )


def list_audit(limit: int = 200, username: str | None = None, action: str | None = None) -> list[dict]:
    sql, args = "SELECT at, username, action, detail FROM audit WHERE 1 = 1", []
    if username:
        sql += " AND username = ? COLLATE NOCASE"
        args.append(username)
    if action:
        sql += " AND action = ?"
        args.append(action)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


# --- login and sessions ------------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _lock_remaining(conn: sqlite3.Connection, username: str) -> int:
    """Seconds left of a lockout: enough failures in the window since the last successful login."""
    window_start = datetime.now(UTC) - timedelta(minutes=settings.lockout_minutes)
    rows = conn.execute(
        """SELECT at FROM audit WHERE username = ? COLLATE NOCASE AND action = 'login_failed' AND at >= ?
           AND at > COALESCE((SELECT MAX(at) FROM audit WHERE username = ? COLLATE NOCASE
                              AND action = 'login_ok'), '')
           ORDER BY at""",
        (username, window_start.isoformat(timespec="seconds"), username),
    ).fetchall()
    if len(rows) < settings.lockout_attempts:
        return 0
    first = datetime.fromisoformat(rows[-settings.lockout_attempts]["at"])
    unlock = first + timedelta(minutes=settings.lockout_minutes)
    return max(1, int((unlock - datetime.now(UTC)).total_seconds()))


def authenticate(username: str, password: str) -> dict | None:
    """The user if the password is right. Raises LoginLocked after too many failures."""
    username = username.strip()
    with connect() as conn:
        remaining = _lock_remaining(conn, username)
        if remaining:
            audit(conn, None, "login_locked", username=username)
            raise LoginLocked(remaining)
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        # Always run bcrypt, also for unknown users: equal timing doesn't reveal which usernames exist.
        ok = passwords.verify_password(password, row["password_hash"] if row else passwords.DUMMY_HASH)
        if not row or not ok or not row["is_active"]:
            audit(
                conn,
                None,
                "login_failed",
                "inactive account" if row and ok else "",
                username=username,
            )
            return None
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now(), row["id"]))
        audit(conn, dict(row), "login_ok")
        return dict(row)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)  # goes into the cookie; only its hash is stored
    expires = datetime.now(UTC) + timedelta(hours=settings.session_hours)
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires < ?", (now(),))  # tidy up old ones
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created, expires) VALUES (?, ?, ?, ?)",
            (_hash_token(token), user_id, now(), expires.isoformat(timespec="seconds")),
        )
    return token


def user_for_session(token: str | None) -> dict | None:
    if not token:
        return None
    with connect() as conn:
        row = conn.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires > ? AND u.is_active = 1""",
            (_hash_token(token), now()),
        ).fetchone()
    return dict(row) if row else None


def end_session(token: str | None, user: dict | None) -> None:
    if not token:
        return
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))
        if user:
            audit(conn, user, "logout")


def change_password(user: dict, current: str, new: str) -> None:
    if not passwords.verify_password(current, user["password_hash"]):
        raise AccountError("The current password is wrong.")
    if current == new:
        raise AccountError("The new password must be different.")
    new_hash = passwords.hash_password(new)  # raises PasswordPolicyError
    with connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (new_hash, user["id"]),
        )
        audit(conn, user, "password_changed")


# --- users -------------------------------------------------------------------------------------------


def _roles_of(conn: sqlite3.Connection, user_id: int) -> list[str]:
    return [
        r[0]
        for r in conn.execute("SELECT role_name FROM user_roles WHERE user_id = ? ORDER BY 1", (user_id,))
    ]


def _active_admins(conn: sqlite3.Connection) -> int:
    return conn.execute(
        """SELECT COUNT(*) FROM users u JOIN user_roles r ON r.user_id = u.id
           WHERE r.role_name = ? AND u.is_active = 1""",
        (ADMIN_ROLE,),
    ).fetchone()[0]


def list_users() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, username, display_name, is_active, must_change_password, created, last_login "
            "FROM users ORDER BY username"
        ).fetchall()
        return [{**dict(r), "roles": _roles_of(conn, r["id"])} for r in rows]


def get_user(user_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return {**dict(row), "roles": _roles_of(conn, user_id)} if row else None


def _set_roles(conn: sqlite3.Connection, user_id: int, roles: list[str]) -> None:
    known = {r[0] for r in conn.execute("SELECT name FROM roles")}
    unknown = set(roles) - known
    if unknown:
        raise AccountError(f"Unknown role(s): {', '.join(sorted(unknown))}")
    conn.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO user_roles (user_id, role_name) VALUES (?, ?)",
        [(user_id, r) for r in roles],
    )


def create_user(
    actor: dict | None,
    username: str,
    display_name: str,
    password: str,
    roles: list[str],
    must_change: bool = True,
) -> int:
    username = username.strip()
    password_hash = passwords.hash_password(password)
    with connect() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, display_name, password_hash, must_change_password, created) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    username,
                    display_name.strip() or username,
                    password_hash,
                    int(must_change),
                    now(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise AccountError(f"The username {username!r} is already taken.") from exc
        _set_roles(conn, cursor.lastrowid, roles)
        audit(
            conn,
            actor,
            "user_created",
            f"{username} roles={','.join(roles) or '-'}",
            username="cli",
        )
        return cursor.lastrowid


def update_user(
    actor: dict,
    user_id: int,
    display_name: str | None = None,
    is_active: bool | None = None,
    roles: list[str] | None = None,
) -> None:
    with connect() as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            raise AccountError("User not found.")
        if user_id == actor["id"] and (is_active is False or (roles is not None and ADMIN_ROLE not in roles)):
            raise AccountError("You can't deactivate yourself or remove your own admin role.")
        changes = []
        if display_name is not None:
            conn.execute(
                "UPDATE users SET display_name = ? WHERE id = ?",
                (display_name.strip(), user_id),
            )
            changes.append("name")
        if is_active is not None:
            conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id))
            if not is_active:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))  # signed out immediately
            changes.append("active" if is_active else "deactivated")
        if roles is not None:
            _set_roles(conn, user_id, roles)
            changes.append(f"roles={','.join(roles) or '-'}")
        if _active_admins(conn) == 0:
            raise AccountError("There must always be at least one active admin.")  # rolls the change back
        audit(conn, actor, "user_updated", f"{target['username']}: {' '.join(changes)}")


def reset_password(actor: dict | None, user_id: int, temporary: str) -> None:
    password_hash = passwords.hash_password(temporary)
    with connect() as conn:
        target = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            raise AccountError("User not found.")
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
            (password_hash, user_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        audit(conn, actor, "password_reset", target["username"], username="cli")


# --- roles and grants --------------------------------------------------------------------------------


def list_roles() -> list[dict]:
    with connect() as conn:
        roles = [
            dict(r)
            for r in conn.execute("SELECT name, description, builtin FROM roles ORDER BY builtin DESC, name")
        ]
        for role in roles:
            grants = conn.execute(
                "SELECT kind, value FROM role_grants WHERE role_name = ? ORDER BY 1, 2",
                (role["name"],),
            )
            role["grants"] = {kind: [] for kind in GRANT_KINDS}
            for kind, value in grants:
                role["grants"][kind].append(value)
            role["members"] = conn.execute(
                "SELECT COUNT(*) FROM user_roles WHERE role_name = ?", (role["name"],)
            ).fetchone()[0]
        return roles


def save_role(actor: dict | None, name: str, description: str, grants: dict[str, list[str]]) -> None:
    name = name.strip().lower()
    if not name:
        raise AccountError("The role needs a name.")
    with connect() as conn:
        if name == ADMIN_ROLE:
            raise AccountError("The admin role always has full access and can't be edited.")
        conn.execute(
            "INSERT INTO roles (name, description) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET description = excluded.description",
            (name, description.strip()),
        )
        conn.execute("DELETE FROM role_grants WHERE role_name = ?", (name,))
        for kind in GRANT_KINDS:
            for value in sorted({v.strip().strip("/") or "/" for v in grants.get(kind, []) if v.strip()}):
                conn.execute(
                    "INSERT INTO role_grants (role_name, kind, value) VALUES (?, ?, ?)",
                    (name, kind, value),
                )
        summary = "; ".join(f"{k}={','.join(grants.get(k, [])) or '-'}" for k in GRANT_KINDS)
        audit(conn, actor, "role_saved", f"{name}: {summary}", username="cli")


def delete_role(actor: dict, name: str) -> None:
    with connect() as conn:
        if name == ADMIN_ROLE:
            raise AccountError("The admin role can't be deleted.")
        if conn.execute("DELETE FROM roles WHERE name = ?", (name,)).rowcount == 0:
            raise AccountError("Role not found.")
        audit(conn, actor, "role_deleted", name)


def grants_for(user_id: int) -> tuple[bool, dict[str, set[str]]]:
    """(is_admin, {kind: values}) across all the user's roles."""
    with connect() as conn:
        roles = _roles_of(conn, user_id)
        rows = conn.execute(
            "SELECT kind, value FROM role_grants WHERE role_name IN (SELECT role_name FROM user_roles WHERE user_id = ?)",
            (user_id,),
        ).fetchall()
    grants: dict[str, set[str]] = {kind: set() for kind in GRANT_KINDS}
    for kind, value in rows:
        grants[kind].add(value)
    return ADMIN_ROLE in roles, grants
