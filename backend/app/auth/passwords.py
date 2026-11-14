"""Password hashing with bcrypt: deliberately slow and salted, so a stolen database is hard to crack."""

import bcrypt

MIN_LENGTH = 10
MAX_BYTES = 72  # bcrypt ignores everything after 72 bytes: reject instead of silently cutting


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str) -> None:
    if password != password.strip():
        raise PasswordPolicyError("The password can't start or end with a space.")
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"The password must have at least {MIN_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_BYTES:
        raise PasswordPolicyError(f"The password can be at most {MAX_BYTES} bytes long.")


def hash_password(password: str) -> str:
    check_policy(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:MAX_BYTES], password_hash.encode("ascii"))
    except ValueError:  # malformed hash
        return False


# Checked when the username doesn't exist, so unknown users take as long as wrong passwords
# (otherwise response times would reveal which usernames exist).
DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode("ascii")
