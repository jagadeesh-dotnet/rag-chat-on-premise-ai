from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.ingest.store import get_store
from app.routers import chat, conversations, databases, documents, tables


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield  # the app runs here
    get_store().close()  # on shutdown: release data/qdrant cleanly


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(tables.router)
app.include_router(databases.router)
app.include_router(conversations.router)


@app.get("/api/health")
async def health() -> dict:
    ollama_ok = False
    model_ready = False
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.ollama_host}/api/tags")
            response.raise_for_status()
            names = [m["name"] for m in response.json().get("models", [])]
            ollama_ok = True
            model_ready = settings.chat_model in names
    except httpx.HTTPError:
        pass  # Ollama is down or slow: report it, don't crash

    return {
        "status": "ok",
        "app_name": settings.app_name,
        "chat_model": settings.chat_model,
        "ollama": ollama_ok,
        "chat_model_ready": model_ready,
    }
