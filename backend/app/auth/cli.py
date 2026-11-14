"""Account administration from the command line (works without the web app running).

    python -m app.auth.cli create-admin <username>
    python -m app.auth.cli reset-password <username>
    python -m app.auth.cli seed-test-users      # test-admin, test-sales, test-hr with random passwords
    python -m app.auth.cli migrate-sqlite       # copy accounts from the old data/app.db into RagChatApp

Passwords are asked for with getpass (not shown, not in shell history) and never printed.
"""

import argparse
import getpass
import json
import secrets
import sqlite3
import sys
from datetime import UTC, datetime

from app.auth import service
from app.auth.db import ADMIN_ROLE, connect_as_administrator
from app.auth.passwords import PasswordPolicyError, check_policy
from app.config import settings

TEST_ACCOUNTS_FILE = settings.data_dir / "test-accounts.local.json"  # *.local.json is git-ignored


def _ask_password() -> str:
    while True:
        password = getpass.getpass("Password: ")
        try:
            check_policy(password)
        except PasswordPolicyError as exc:
            print(exc)
            continue
        if getpass.getpass("Repeat: ") == password:
            return password
        print("The passwords don't match.")


def _user_id(username: str) -> int:
    user_id = service.user_id_for(username)
    if user_id is None:
        sys.exit(f"No user {username!r}.")
    return user_id


def create_admin(username: str) -> None:
    password = _ask_password()
    service.create_user(None, username, username, password, [ADMIN_ROLE], must_change=False)
    adopted = _adopt_orphan_conversations(username)
    print(f"Admin {username!r} created." + (f" {adopted} older conversation(s) assigned to it." if adopted else ""))


def reset_password(username: str) -> None:
    service.reset_password(None, _user_id(username), _ask_password())
    print(f"Password of {username!r} reset; it must be changed at the next sign-in.")


def seed_test_users() -> None:
    """Accounts for testing permissions. Passwords go to a git-ignored file, never to the screen."""
    service.save_role(
        None,
        "sales",
        "Northwind and the spreadsheets; top-level documents, not HR",
        {"folder": ["/"], "spreadsheet": ["*"], "database": ["northwind"]},
    )
    service.save_role(None, "hr", "HR documents only", {"folder": ["hr"], "spreadsheet": [], "database": []})
    accounts = {}
    for username, roles in (("test-admin", [ADMIN_ROLE]), ("test-sales", ["sales"]), ("test-hr", ["hr"])):
        password = secrets.token_urlsafe(12)
        try:
            service.create_user(None, username, username, password, roles, must_change=False)
        except service.AccountError:
            service.reset_password(None, _user_id(username), password)
            service.set_user_flags(username, must_change=False, active=True)
        accounts[username] = password
    TEST_ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    _adopt_orphan_conversations("test-admin")
    print(f"Test users ready: {', '.join(accounts)}. Passwords are in {TEST_ACCOUNTS_FILE}")


def _utc(text: str | None) -> datetime | None:
    """'2026-11-14T13:00:00+00:00' (old SQLite format) -> naive UTC datetime for DATETIME2."""
    if not text:
        return None
    return datetime.fromisoformat(text).astimezone(UTC).replace(tzinfo=None)


def migrate_sqlite() -> None:
    """Copy users (with their ids, so conversations keep their owner), roles, grants and audit history."""
    path = settings.legacy_app_db_path
    if not path.exists():
        sys.exit(f"Nothing to migrate: {path} doesn't exist.")
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    with connect_as_administrator() as db:  # IDENTITY_INSERT needs more than chat_app's rights
        if db.scalar("SELECT COUNT(*) FROM users"):
            sys.exit("RagChatApp already has users; the migration only runs into an empty database.")
        for role in old.execute("SELECT * FROM roles WHERE builtin = 0"):
            db.execute("INSERT INTO roles (name, description) VALUES (?, ?)", role["name"], role["description"])
        db.execute("SET IDENTITY_INSERT users ON")
        for u in old.execute("SELECT * FROM users"):
            db.execute(
                "INSERT INTO users (id, username, display_name, password_hash, is_active, must_change_password, "
                "created, last_login) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                u["id"],
                u["username"],
                u["display_name"],
                u["password_hash"],
                u["is_active"],
                u["must_change_password"],
                _utc(u["created"]),
                _utc(u["last_login"]),
            )
        db.execute("SET IDENTITY_INSERT users OFF")
        for r in old.execute("SELECT * FROM user_roles"):
            db.execute("INSERT INTO user_roles (user_id, role_name) VALUES (?, ?)", r["user_id"], r["role_name"])
        for g in old.execute("SELECT * FROM role_grants"):
            db.execute(
                "INSERT INTO role_grants (role_name, kind, value) VALUES (?, ?, ?)", g["role_name"], g["kind"], g["value"]
            )
        audit_rows = old.execute("SELECT * FROM audit ORDER BY id").fetchall()
        for a in audit_rows:
            db.execute(
                "INSERT INTO audit (at, user_id, username, action, detail) VALUES (?, ?, ?, ?, ?)",
                _utc(a["at"]),
                a["user_id"],
                a["username"],
                a["action"],
                a["detail"],
            )
        users = db.scalar("SELECT COUNT(*) FROM users")
        roles = db.scalar("SELECT COUNT(*) FROM roles")
        db.execute(
            "INSERT INTO audit (at, user_id, username, action, detail) VALUES (SYSUTCDATETIME(), NULL, 'cli', "
            "'migrated', ?)",
            f"from {path.name}: {users} users, {roles} roles, {len(audit_rows)} audit entries",
        )
    old.close()
    print(f"Migrated {users} users, {roles} roles and {len(audit_rows)} audit entries into {settings.app_database}.")
    print(f"Sessions were not copied (everyone signs in again). You can now delete {path}.")


def _adopt_orphan_conversations(username: str) -> int:
    """Conversations saved before login existed have no owner: give them to this admin."""
    from app import conversations

    return conversations.adopt_orphans(_user_id(username))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create-admin").add_argument("username")
    sub.add_parser("reset-password").add_argument("username")
    sub.add_parser("seed-test-users")
    sub.add_parser("migrate-sqlite")
    args = parser.parse_args()
    try:
        if args.command == "create-admin":
            create_admin(args.username)
        elif args.command == "reset-password":
            reset_password(args.username)
        elif args.command == "migrate-sqlite":
            migrate_sqlite()
        else:
            seed_test_users()
    except service.AccountError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
