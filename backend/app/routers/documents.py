from fastapi import APIRouter, HTTPException, Query

from app.ingest.indexer import IndexBusyError, index_documents
from app.ingest.store import get_store

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Plain `def`, not `async def`: Qdrant local mode and the indexer are blocking (sync) code.
# FastAPI runs `def` endpoints on a thread pool, so they don't freeze the server meanwhile.


@router.get("")
def list_documents() -> list[dict]:
    counts = get_store().chunk_counts()
    return [{"source": source, "chunks": n} for source, n in sorted(counts.items())]


@router.post("/index")
def index(force: bool = False) -> dict:
    try:
        return index_documents(force=force)
    except IndexBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/search")
def search(
    q: str = Query(min_length=2, max_length=1000),
    k: int = Query(5, ge=1, le=20),
    source: str | None = None,
    min_score: float | None = Query(None, ge=0.0, le=1.0),
) -> list[dict]:
    return get_store().search(q, k=k, source=source, min_score=min_score)
