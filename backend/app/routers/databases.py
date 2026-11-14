from concurrent.futures import ThreadPoolExecutor

import pyodbc
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.databases.connection import is_reachable
from app.databases.query import DatabaseError, GuardError, get_database, run_select
from app.databases.registry import load_databases
from app.databases.schema import render, schema_cache

router = APIRouter(prefix="/api/databases", tags=["databases"])


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10_000)


def _database(name: str):
    try:
        return get_database(name)
    except DatabaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("")
def list_databases() -> list[dict]:
    databases = list(load_databases().values())
    with ThreadPoolExecutor(max_workers=max(1, len(databases))) as pool:  # check all at once, not one by one
        reachable = list(pool.map(is_reachable, databases))
    return [
        {"name": db.name, "database": db.database, "description": db.description, "reachable": ok}
        for db, ok in zip(databases, reachable)
    ]


@router.get("/{name}/schema")
def schema(name: str, refresh: bool = False) -> dict:
    db = _database(name)
    try:
        tables = schema_cache.tables(db, force=refresh)
    except pyodbc.Error as exc:
        raise HTTPException(status_code=503, detail=f"Database {name!r} can't be reached") from exc
    return {"name": db.name, "tables": len(tables), "schema": render(db, tables)}


@router.post("/{name}/query")
def query(name: str, request: QueryRequest) -> dict:
    db = _database(name)
    try:
        return run_select(db, request.sql)
    except (GuardError, DatabaseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except pyodbc.Error as exc:
        raise HTTPException(status_code=503, detail=f"Database {name!r} can't be reached") from exc
