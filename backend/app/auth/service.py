"""Accounts: login with lockout, sessions, users, roles, grants, attributes and row rules.

Stored in SQL Server (RagChatApp, see app/auth/db.py). Every change is written to the audit log.
"""

import hashlib
import secrets
from datetime import timedelta

import pyodbc

from app.auth import passwords
from app.auth.db import ADMIN_ROLE, Db, connect, iso, now
from app.config import settings

GRANT_KINDS = ("folder", "spreadsheet", "database")
RULE_KINDS = ("spreadsheet", "database")
SPREADSHEETS = "spreadsheets"  # the source name of spreadsheet row rules


class LoginLocked(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("locked")
        self.retry_after = retry_after  # seconds


class AccountError(ValueError):
    """A request that breaks a rule (e.g. removing the last admin). The message is shown to the admin."""


# --- audit -------------------------------------------------------------------------------------------


def audit(db: Db, actor: dict | None, action: str, detail: str = "", username: str = "") -> None:
    db.execute(
        "INSERT INTO audit (at, user_id, username, action, detail) VALUES (?, ?, ?, ?, ?)",
        now(),
        actor["id"] if actor else None,
        actor["username"] if actor else username,
        action,
        detail[:1000],
    )


def record(actor: dict, action: str, detail: str = "") -> None:
    """One audit entry in its own transaction, for actions outside the account tables (e.g. indexing)."""
    with connect() as db:
        audit(db, actor, action, detail)


def list_audit(limit: int = 200, username: str | None = None, action: str | None = None) -> list[dict]:
    sql, args = "SELECT TOP (?) at, username, action, detail FROM audit WHERE 1 = 1", [limit]
    if username:
        sql += " AND username = ?"
        args.append(username)
    if action:
        sql += " AND action = ?"
        args.append(action)
    with connect() as db:
        rows = db.all(sql + " ORDER BY id DESC", *args)
    return [{**r, "at": iso(r["at"])} for r in rows]


# --- login and sessions ------------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _lock_remaining(db: Db, username: str) -> int:
    """Seconds left of a lockout: enough failures in the window since the last successful login."""
    window_start = now() - timedelta(minutes=settings.lockout_minutes)
    failures = db.all(
        """SELECT at FROM audit
           WHERE username = ? AND action = 'login_failed' AND at >= ?
             AND at > COALESCE((SELECT MAX(at) FROM audit WHERE username = ? AND action = 'login_ok'), '19000101')
           ORDER BY at""",
        username,
        window_start,
        username,
    )
    if len(failures) < settings.lockout_attempts:
        return 0
    unlock = failures[-settings.lockout_attempts]["at"] + timedelta(minutes=settings.lockout_minutes)
    return max(1, int((unlock - now()).total_seconds()))


def authenticate(username: str, password: str) -> dict | None:
    """The user if the password is right. Raises LoginLocked after too many failures."""
    username = username.strip()
    user, locked = None, None
    with connect() as db:
        remaining = _lock_remaining(db, username)
        if remaining:
            audit(db, None, "login_locked", username=username)
            locked = LoginLocked(remaining)
        else:
            row = db.one("SELECT * FROM users WHERE username = ?", username)
            # Always run bcrypt, also for unknown users: equal timing doesn't reveal which usernames exist.
            ok = passwords.verify_password(password, row["password_hash"] if row else passwords.DUMMY_HASH)
            if not row or not ok or not row["is_active"]:
                audit(db, None, "login_failed", "inactive account" if row and ok else "", username=username)
            else:
                db.execute("UPDATE users SET last_login = ? WHERE id = ?", now(), row["id"])
                audit(db, row, "login_ok")
                user = row
    if locked:
        raise locked  # raised after the block, so the audit entry is committed
    return user


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)  # goes into the cookie; only its hash is stored
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE expires < ?", now())  # tidy up old ones
        db.execute(
            "INSERT INTO sessions (token_hash, user_id, created, expires) VALUES (?, ?, ?, ?)",
            _hash_token(token),
            user_id,
            now(),
            now() + timedelta(hours=settings.session_hours),
        )
    return token


def user_for_session(token: str | None) -> dict | None:
    if not token:
        return None
    with connect() as db:
        return db.one(
            """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires > ? AND u.is_active = 1""",
            _hash_token(token),
            now(),
        )


def end_session(token: str | None, user: dict | None) -> None:
    if not token:
        return
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", _hash_token(token))
        if user:
            audit(db, user, "logout")


def change_password(user: dict, current: str, new: str) -> None:
    if not passwords.verify_password(current, user["password_hash"]):
        raise AccountError("The current password is wrong.")
    if current == new:
        raise AccountError("The new password must be different.")
    new_hash = passwords.hash_password(new)  # raises PasswordPolicyError
    with connect() as db:
        db.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?", new_hash, user["id"])
        audit(db, user, "password_changed")


# --- users -------------------------------------------------------------------------------------------


def _roles_of(db: Db, user_id: int) -> list[str]:
    return [r["role_name"] for r in db.all("SELECT role_name FROM user_roles WHERE user_id = ? ORDER BY 1", user_id)]


def _attributes_of(db: Db, user_id: int) -> dict[str, list[str]]:
    attributes: dict[str, list[str]] = {}
    for row in db.all("SELECT name, value FROM user_attributes WHERE user_id = ? ORDER BY name, value", user_id):
        attributes.setdefault(row["name"], []).append(row["value"])
    return attributes


def _active_admins(db: Db) -> int:
    return db.scalar(
        "SELECT COUNT(*) FROM users u JOIN user_roles r ON r.user_id = u.id WHERE r.role_name = ? AND u.is_active = 1",
        ADMIN_ROLE,
    )


def list_users() -> list[dict]:
    with connect() as db:
        rows = db.all(
            "SELECT id, username, display_name, is_active, must_change_password, created, last_login "
            "FROM users ORDER BY username"
        )
        return [
            {
                **r,
                "created": iso(r["created"]),
                "last_login": iso(r["last_login"]),
                "roles": _roles_of(db, r["id"]),
                "attributes": _attributes_of(db, r["id"]),
            }
            for r in rows
        ]


def _set_roles(db: Db, user_id: int, roles: list[str]) -> None:
    known = {r["name"] for r in db.all("SELECT name FROM roles")}
    unknown = set(roles) - known
    if unknown:
        raise AccountError(f"Unknown role(s): {', '.join(sorted(unknown))}")
    db.execute("DELETE FROM user_roles WHERE user_id = ?", user_id)
    for role in roles:
        db.execute("INSERT INTO user_roles (user_id, role_name) VALUES (?, ?)", user_id, role)


def _set_attributes(db: Db, user_id: int, attributes: dict[str, list[str]]) -> None:
    db.execute("DELETE FROM user_attributes WHERE user_id = ?", user_id)
    for name, values in attributes.items():
        for value in sorted({v.strip() for v in values if v.strip()}):
            db.execute(
                "INSERT INTO user_attributes (user_id, name, value) VALUES (?, ?, ?)",
                user_id,
                name.strip().lower(),
                value,
            )


def create_user(
    actor: dict | None, username: str, display_name: str, password: str, roles: list[str], must_change: bool = True
) -> int:
    username = username.strip()
    password_hash = passwords.hash_password(password)
    with connect() as db:
        try:
            new_id = db.scalar(
                "INSERT INTO users (username, display_name, password_hash, must_change_password, created) "
                "OUTPUT INSERTED.id VALUES (?, ?, ?, ?, ?)",
                username,
                display_name.strip() or username,
                password_hash,
                int(must_change),
                now(),
            )
        except pyodbc.IntegrityError as exc:
            raise AccountError(f"The username {username!r} is already taken.") from exc
        _set_roles(db, new_id, roles)
        audit(db, actor, "user_created", f"{username} roles={','.join(roles) or '-'}", username="cli")
        return new_id


def update_user(
    actor: dict,
    user_id: int,
    display_name: str | None = None,
    is_active: bool | None = None,
    roles: list[str] | None = None,
    attributes: dict[str, list[str]] | None = None,
) -> None:
    with connect() as db:
        target = db.one("SELECT * FROM users WHERE id = ?", user_id)
        if target is None:
            raise AccountError("User not found.")
        if user_id == actor["id"] and (is_active is False or (roles is not None and ADMIN_ROLE not in roles)):
            raise AccountError("You can't deactivate yourself or remove your own admin role.")
        changes = []
        if display_name is not None:
            db.execute("UPDATE users SET display_name = ? WHERE id = ?", display_name.strip(), user_id)
            changes.append("name")
        if is_active is not None:
            db.execute("UPDATE users SET is_active = ? WHERE id = ?", int(is_active), user_id)
            if not is_active:
                db.execute("DELETE FROM sessions WHERE user_id = ?", user_id)  # signed out immediately
            changes.append("active" if is_active else "deactivated")
        if roles is not None:
            _set_roles(db, user_id, roles)
            changes.append(f"roles={','.join(roles) or '-'}")
        if attributes is not None:
            _set_attributes(db, user_id, attributes)
            shown = "; ".join(f"{k}={','.join(v)}" for k, v in sorted(attributes.items())) or "-"
            changes.append(f"attributes={shown}")
        if _active_admins(db) == 0:
            raise AccountError("There must always be at least one active admin.")  # rolls the change back
        audit(db, actor, "user_updated", f"{target['username']}: {' '.join(changes)}")


def reset_password(actor: dict | None, user_id: int, temporary: str) -> None:
    password_hash = passwords.hash_password(temporary)
    with connect() as db:
        target = db.one("SELECT username FROM users WHERE id = ?", user_id)
        if target is None:
            raise AccountError("User not found.")
        db.execute("UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?", password_hash, user_id)
        db.execute("DELETE FROM sessions WHERE user_id = ?", user_id)
        audit(db, actor, "password_reset", target["username"], username="cli")


def set_user_flags(username: str, must_change: bool, active: bool) -> None:
    """For the CLI's test accounts."""
    with connect() as db:
        db.execute(
            "UPDATE users SET must_change_password = ?, is_active = ? WHERE username = ?",
            int(must_change),
            int(active),
            username,
        )


def user_id_for(username: str) -> int | None:
    with connect() as db:
        return db.scalar("SELECT id FROM users WHERE username = ?", username)


# --- roles and grants --------------------------------------------------------------------------------


def list_roles() -> list[dict]:
    with connect() as db:
        roles = db.all("SELECT name, description, builtin FROM roles ORDER BY builtin DESC, name")
        for role in roles:
            role["grants"] = {kind: [] for kind in GRANT_KINDS}
            grants = db.all("SELECT kind, value FROM role_grants WHERE role_name = ? ORDER BY kind, value", role["name"])
            for grant in grants:
                role["grants"][grant["kind"]].append(grant["value"])
            role["members"] = db.scalar("SELECT COUNT(*) FROM user_roles WHERE role_name = ?", role["name"])
        return roles


def save_role(actor: dict | None, name: str, description: str, grants: dict[str, list[str]]) -> None:
    name = name.strip().lower()
    if not name:
        raise AccountError("The role needs a name.")
    if name == ADMIN_ROLE:
        raise AccountError("The admin role always has full access and can't be edited.")
    with connect() as db:
        if db.scalar("SELECT COUNT(*) FROM roles WHERE name = ?", name):
            db.execute("UPDATE roles SET description = ? WHERE name = ?", description.strip(), name)
        else:
            db.execute("INSERT INTO roles (name, description) VALUES (?, ?)", name, description.strip())
        db.execute("DELETE FROM role_grants WHERE role_name = ?", name)
        for kind in GRANT_KINDS:
            for value in sorted({v.strip().strip("/") or "/" for v in grants.get(kind, []) if v.strip()}):
                db.execute("INSERT INTO role_grants (role_name, kind, value) VALUES (?, ?, ?)", name, kind, value)
        summary = "; ".join(f"{k}={','.join(grants.get(k, [])) or '-'}" for k in GRANT_KINDS)
        audit(db, actor, "role_saved", f"{name}: {summary}", username="cli")


def delete_role(actor: dict, name: str) -> None:
    if name == ADMIN_ROLE:
        raise AccountError("The admin role can't be deleted.")
    with connect() as db:
        if db.execute("DELETE FROM roles WHERE name = ?", name).rowcount == 0:
            raise AccountError("Role not found.")
        audit(db, actor, "role_deleted", name)


# --- row rules ---------------------------------------------------------------------------------------


def list_rules() -> list[dict]:
    with connect() as db:
        rows = db.all(
            "SELECT id, kind, source, table_name, column_name, attribute, created FROM row_rules "
            "ORDER BY kind, source, table_name, column_name"
        )
    return [{**r, "created": iso(r["created"])} for r in rows]


def add_rule(actor: dict | None, kind: str, source: str, table: str, column: str, attribute: str) -> int:
    if kind not in RULE_KINDS:
        raise AccountError(f"kind must be one of {', '.join(RULE_KINDS)}")
    source = SPREADSHEETS if kind == "spreadsheet" else source.strip().lower()
    if not all(v.strip() for v in (source, table, column, attribute)):
        raise AccountError("Source, table, column and attribute are required.")
    with connect() as db:
        try:
            rule_id = db.scalar(
                "INSERT INTO row_rules (kind, source, table_name, column_name, attribute, created) "
                "OUTPUT INSERTED.id VALUES (?, ?, ?, ?, ?, ?)",
                kind,
                source,
                table.strip(),
                column.strip(),
                attribute.strip().lower(),
                now(),
            )
        except pyodbc.IntegrityError as exc:
            raise AccountError("There is already a rule for that column.") from exc
        audit(db, actor, "rule_added", f"{kind} {source}.{table}.{column} = user.{attribute}", username="cli")
        return rule_id


def delete_rule(actor: dict, rule_id: int) -> None:
    with connect() as db:
        rule = db.one("SELECT * FROM row_rules WHERE id = ?", rule_id)
        if rule is None:
            raise AccountError("Rule not found.")
        db.execute("DELETE FROM row_rules WHERE id = ?", rule_id)
        audit(db, actor, "rule_deleted", f"{rule['source']}.{rule['table_name']}.{rule['column_name']}")


# --- everything one user's Access needs, in one connection ---------------------------------------------


def permissions_for(user_id: int) -> dict:
    """is_admin, grants {kind: values}, attributes {name: values} and all row rules."""
    with connect() as db:
        roles = _roles_of(db, user_id)
        grants: dict[str, set[str]] = {kind: set() for kind in GRANT_KINDS}
        rows = db.all(
            "SELECT kind, value FROM role_grants WHERE role_name IN "
            "(SELECT role_name FROM user_roles WHERE user_id = ?)",
            user_id,
        )
        for row in rows:
            grants[row["kind"]].add(row["value"])
        attributes = _attributes_of(db, user_id)
        rules = db.all("SELECT kind, source, table_name, column_name, attribute FROM row_rules")
    return {"is_admin": ADMIN_ROLE in roles, "grants": grants, "attributes": attributes, "rules": rules}
