from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import CurrentAccess
from app.sql_guard import GuardError
from app.tables.catalog import QueryError, get_catalog
from app.tools.tables import allowed_tables

router = APIRouter(prefix="/api/tables", tags=["tables"])


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10_000)


@router.get("")
def list_tables(access: CurrentAccess) -> dict:
    catalog = get_catalog()
    catalog.refresh()
    allowed = allowed_tables(access)
    tables = [
        {
            "name": t.name,
            "source": t.source,
            "rows": t.rows,
            "columns": [{"name": c, "type": kind} for c, kind in t.columns],
        }
        for t in (catalog.tables[n] for n in catalog.visible(allowed))
    ]
    return {"tables": tables, "schema": catalog.schema_text(allowed)}


@router.post("/query")
def query(access: CurrentAccess, request: QueryRequest) -> dict:
    catalog = get_catalog()
    catalog.refresh()
    try:
        return catalog.query(request.sql, allowed_tables(access))
    except (GuardError, QueryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
