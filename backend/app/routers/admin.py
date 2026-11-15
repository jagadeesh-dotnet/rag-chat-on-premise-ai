"""User, role and audit administration. Every endpoint requires the admin role."""

from datetime import UTC, datetime
from typing import Literal

import pyodbc
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import service
from app.auth.access import Access
from app.auth.deps import AdminAccess
from app.auth.passwords import PasswordPolicyError
from app.config import settings
from app.databases.registry import load_databases
from app.databases.schema import schema_cache
from app.ingest.indexer import file_hash, find_documents
from app.ingest.store import get_store
from app.tables.catalog import get_catalog

router = APIRouter(prefix="/api/admin", tags=["admin"])


class NewUser(BaseModel):
    username: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9._\-]+$")
    display_name: str = Field("", max_length=100)
    temporary_password: str = Field(min_length=1, max_length=200)
    roles: list[str] = []


class UserChange(BaseModel):
    display_name: str | None = Field(None, max_length=100)
    is_active: bool | None = None
    roles: list[str] | None = None
    attributes: dict[str, list[str]] | None = None  # e.g. {"region": ["East"]}, compared by row rules


class NewRule(BaseModel):
    kind: Literal["spreadsheet", "database"]
    source: str = Field("", max_length=100)  # database name; ignored for spreadsheets
    table: str = Field(min_length=1, max_length=128)
    column: str = Field(min_length=1, max_length=128)
    attribute: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_\-]+$")


class PasswordReset(BaseModel):
    temporary_password: str = Field(min_length=1, max_length=200)


class RoleData(BaseModel):
    description: str = Field("", max_length=200)
    grants: dict[str, list[str]] = {}


def _actor(access: Access) -> dict:
    return {"id": access.user_id, "username": access.username}


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/users")
def users(_: AdminAccess) -> list[dict]:
    return service.list_users()


@router.post("/users", status_code=201)
def create_user(access: AdminAccess, user: NewUser) -> dict:
    try:
        user_id = service.create_user(
            _actor(access),
            user.username,
            user.display_name,
            user.temporary_password,
            user.roles,
        )
    except (service.AccountError, PasswordPolicyError) as exc:
        raise _fail(exc) from exc
    return {"id": user_id}


@router.patch("/users/{user_id}")
def update_user(access: AdminAccess, user_id: int, change: UserChange) -> dict:
    try:
        service.update_user(
            _actor(access), user_id, change.display_name, change.is_active, change.roles, change.attributes
        )
    except service.AccountError as exc:
        raise _fail(exc) from exc
    return {"id": user_id}


@router.post("/users/{user_id}/password", status_code=204)
def reset_password(access: AdminAccess, user_id: int, body: PasswordReset) -> None:
    try:
        service.reset_password(_actor(access), user_id, body.temporary_password)
    except (service.AccountError, PasswordPolicyError) as exc:
        raise _fail(exc) from exc


@router.get("/roles")
def roles(_: AdminAccess) -> list[dict]:
    return service.list_roles()


@router.put("/roles/{name}")
def save_role(access: AdminAccess, name: str, role: RoleData) -> dict:
    try:
        service.save_role(_actor(access), name, role.description, role.grants)
    except service.AccountError as exc:
        raise _fail(exc) from exc
    return {"name": name.strip().lower()}


@router.delete("/roles/{name}", status_code=204)
def delete_role(access: AdminAccess, name: str) -> None:
    try:
        service.delete_role(_actor(access), name)
    except service.AccountError as exc:
        raise _fail(exc) from exc


@router.get("/resources")
def resources(_: AdminAccess) -> dict:
    """What can be granted (folders, spreadsheet tables, databases) and the columns row rules can use."""
    docs = settings.docs_dir
    folders = {"/"} | {
        p.relative_to(docs).parent.as_posix() for p in find_documents(docs) if p.parent != docs
    }
    catalog = get_catalog()
    catalog.refresh()
    databases = load_databases()
    database_columns: dict[str, dict[str, list[str]]] = {}
    for name, db in databases.items():
        try:
            database_columns[name] = {t.name: t.column_names for t in schema_cache.tables(db)}
        except pyodbc.Error:
            database_columns[name] = {}  # unreachable right now: no column suggestions
    return {
        "folder": sorted(folders),
        "spreadsheet": sorted(catalog.tables),
        "database": sorted(databases),
        "columns": {
            "spreadsheet": {name: [c for c, _ in info.columns] for name, info in catalog.tables.items()},
            "database": database_columns,
        },
    }


@router.get("/documents")
def documents(_: AdminAccess) -> dict:
    """Every document file on disk compared with the index, so the admin sees what the next run will do.

    status: indexed (up to date), changed (re-indexed next run), new (added next run),
    missing (in the index but the file is gone: removed next run).
    """
    docs = settings.docs_dir
    store = get_store()
    indexed = store.file_hashes()  # {source: SHA-256 at indexing time}
    chunks = store.chunk_counts()
    files = []
    for path in find_documents(docs):
        source = path.relative_to(docs).as_posix()
        if source not in indexed:
            status = "new"
        elif indexed[source] != file_hash(path):
            status = "changed"
        else:
            status = "indexed"
        stat = path.stat()
        files.append(
            {
                "source": source,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
                "chunks": chunks.get(source, 0),
                "status": status,
            }
        )
    for source in sorted(indexed.keys() - {f["source"] for f in files}):
        files.append({"source": source, "size": None, "modified": None, "chunks": chunks.get(source, 0), "status": "missing"})
    return {"folder": str(docs), "files": files}


@router.get("/rules")
def rules(_: AdminAccess) -> list[dict]:
    return service.list_rules()


@router.post("/rules", status_code=201)
def add_rule(access: AdminAccess, rule: NewRule) -> dict:
    try:
        rule_id = service.add_rule(_actor(access), rule.kind, rule.source, rule.table, rule.column, rule.attribute)
    except service.AccountError as exc:
        raise _fail(exc) from exc
    return {"id": rule_id}


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(access: AdminAccess, rule_id: int) -> None:
    try:
        service.delete_rule(_actor(access), rule_id)
    except service.AccountError as exc:
        raise _fail(exc) from exc


@router.get("/audit")
def audit(
    _: AdminAccess,
    limit: int = Query(200, ge=1, le=1000),
    username: str | None = None,
    action: str | None = None,
) -> list[dict]:
    return service.list_audit(limit, username, action)
