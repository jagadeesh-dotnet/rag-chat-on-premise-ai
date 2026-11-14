"""User, role and audit administration. Every endpoint requires the admin role."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import service
from app.auth.access import Access
from app.auth.deps import AdminAccess
from app.auth.passwords import PasswordPolicyError
from app.config import settings
from app.databases.registry import load_databases
from app.ingest.indexer import find_documents
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
        service.update_user(_actor(access), user_id, change.display_name, change.is_active, change.roles)
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
    """What can be granted: document folders, spreadsheet tables, databases."""
    docs = settings.docs_dir
    folders = {"/"} | {
        p.relative_to(docs).parent.as_posix() for p in find_documents(docs) if p.parent != docs
    }
    catalog = get_catalog()
    catalog.refresh()
    return {
        "folder": sorted(folders),
        "spreadsheet": sorted(catalog.tables),
        "database": sorted(load_databases()),
    }


@router.get("/audit")
def audit(
    _: AdminAccess,
    limit: int = Query(200, ge=1, le=1000),
    username: str | None = None,
    action: str | None = None,
) -> list[dict]:
    return service.list_audit(limit, username, action)
