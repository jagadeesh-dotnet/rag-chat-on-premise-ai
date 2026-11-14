"""Account administration from the command line (works without the web app running).

    python -m app.auth.cli create-admin <username>
    python -m app.auth.cli reset-password <username>
    python -m app.auth.cli seed-test-users      # test-admin, test-sales, test-hr with random passwords

Passwords are asked for with getpass (not shown, not in shell history) and never printed.
"""

import argparse
import getpass
import json
import secrets
import sys

from app.auth import service
from app.auth.db import ADMIN_ROLE, connect
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
    with connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        sys.exit(f"No user {username!r}.")
    return row["id"]


def create_admin(username: str) -> None:
    password = _ask_password()
    service.create_user(None, username, username, password, [ADMIN_ROLE], must_change=False)
    adopted = _adopt_orphan_conversations(username)
    print(
        f"Admin {username!r} created."
        + (f" {adopted} older conversation(s) assigned to it." if adopted else "")
    )


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
    service.save_role(
        None,
        "hr",
        "HR documents only",
        {"folder": ["hr"], "spreadsheet": [], "database": []},
    )
    accounts = {}
    for username, roles in (
        ("test-admin", [ADMIN_ROLE]),
        ("test-sales", ["sales"]),
        ("test-hr", ["hr"]),
    ):
        password = secrets.token_urlsafe(12)
        try:
            service.create_user(None, username, username, password, roles, must_change=False)
        except service.AccountError:
            service.reset_password(None, _user_id(username), password)
            with connect() as conn:
                conn.execute(
                    "UPDATE users SET must_change_password = 0, is_active = 1 WHERE username = ?",
                    (username,),
                )
        accounts[username] = password
    TEST_ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    _adopt_orphan_conversations("test-admin")
    print(f"Test users ready: {', '.join(accounts)}. Passwords are in {TEST_ACCOUNTS_FILE}")


def _adopt_orphan_conversations(username: str) -> int:
    """Conversations saved before login existed have no owner: give them to this admin."""
    from app import conversations

    return conversations.adopt_orphans(_user_id(username))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create-admin").add_argument("username")
    sub.add_parser("reset-password").add_argument("username")
    sub.add_parser("seed-test-users")
    args = parser.parse_args()
    try:
        if args.command == "create-admin":
            create_admin(args.username)
        elif args.command == "reset-password":
            reset_password(args.username)
        else:
            seed_test_users()
    except service.AccountError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
