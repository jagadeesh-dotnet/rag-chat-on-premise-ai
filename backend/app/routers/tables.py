from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import CurrentAccess
from app.sql_guard import GuardError
from app.tables.catalog import QueryError, get_catalog
from app.tools.tables import allowed_tables, row_conditions, schema_for

router = APIRouter(prefix="/api/tables", tags=["tables"])


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10_000)


@router.get("")
def list_tables(access: CurrentAccess) -> dict:
    catalog = get_catalog()
    catalog.refresh()
    allowed = allowed_tables(access)
    restricted = set(row_conditions(access))
    tables = [
        {
            "name": t.name,
            "source": t.source,
            "rows": None if t.name in restricted else t.rows,  # the total would reveal other people's rows
            "restricted": t.name in restricted,
            "columns": [{"name": c, "type": kind} for c, kind in t.columns],
        }
        for t in (catalog.tables[n] for n in catalog.visible(allowed))
    ]
    return {"tables": tables, "schema": schema_for(access)}


@router.post("/query")
def query(access: CurrentAccess, request: QueryRequest) -> dict:
    """The same row filters apply here as in the chat: a direct API call can't see more."""
    catalog = get_catalog()
    catalog.refresh()
    try:
        return catalog.query(request.sql, allowed_tables(access), row_conditions(access))
    except (GuardError, QueryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
