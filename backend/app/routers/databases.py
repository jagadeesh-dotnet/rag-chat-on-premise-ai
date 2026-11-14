from concurrent.futures import ThreadPoolExecutor

import pyodbc
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth.access import Access
from app.auth.deps import CurrentAccess
from app.databases.connection import is_reachable
from app.databases.query import (
    DatabaseError,
    GuardError,
    get_database,
    run_select,
    visible_databases,
)
from app.databases.registry import DatabaseConfig
from app.databases.schema import render, schema_cache

router = APIRouter(prefix="/api/databases", tags=["databases"])


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10_000)


def _database(name: str, access: Access) -> DatabaseConfig:
    try:
        return get_database(name, access)
    except DatabaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc  # not granted looks like not existing


@router.get("")
def list_databases(access: CurrentAccess) -> list[dict]:
    databases = list(visible_databases(access).values())
    if not databases:
        return []
    with ThreadPoolExecutor(max_workers=len(databases)) as pool:  # check all at once, not one by one
        reachable = list(pool.map(is_reachable, databases))
    return [
        {"name": db.name, "database": db.database, "description": db.description, "reachable": ok}
        for db, ok in zip(databases, reachable)
    ]


@router.get("/{name}/schema")
def schema(access: CurrentAccess, name: str, refresh: bool = False) -> dict:
    db = _database(name, access)
    try:
        tables = schema_cache.tables(db, force=refresh)
    except pyodbc.Error as exc:
        raise HTTPException(status_code=503, detail=f"Database {name!r} can't be reached") from exc
    return {"name": db.name, "tables": len(tables), "schema": render(db, tables)}


@router.post("/{name}/query")
def query(access: CurrentAccess, name: str, request: QueryRequest) -> dict:
    db = _database(name, access)
    try:
        return run_select(db, request.sql)
    except (GuardError, DatabaseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except pyodbc.Error as exc:
        raise HTTPException(status_code=503, detail=f"Database {name!r} can't be reached") from exc
