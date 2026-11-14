from app.routers import chat
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(chat.router)

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
