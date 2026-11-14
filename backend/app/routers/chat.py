import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agent import run_agent
from app.schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])
log = logging.getLogger(__name__)


def to_ndjson(event: dict) -> str:
    """One event = one line of JSON."""
    return json.dumps(event, ensure_ascii=False) + "\n"


@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        try:
            async for event in run_agent(request.messages):
                yield to_ndjson(event)
            yield to_ndjson({"type": "done"})
        except Exception as exc:
            log.exception("Chat stream failed")
            yield to_ndjson({"type": "error", "message": str(exc)})

    return StreamingResponse(events(), media_type="application/x-ndjson")