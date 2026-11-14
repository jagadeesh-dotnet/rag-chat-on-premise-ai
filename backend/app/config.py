from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute paths built from this file's location, so they're the same whichever folder you start from.
# config.py -> parents[0] = app, parents[1] = backend, parents[2] = project root
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Local RAG Chat Application"
    ollama_host: str = "http://localhost:11434"
    chat_model: str = "qwen3:14b"
    embed_model: str = "nomic-embed-text"
    cors_origins: list[str] = ["http://localhost:4200"]
    data_dir: Path = PROJECT_ROOT / "data"
    think: bool = False
    docs_dir: Path = PROJECT_ROOT / "data" / "docs"
    cache_dir: Path = PROJECT_ROOT / "data" / "cache"
    chunk_size: int = 1200
    chunk_overlap: int = 200
    embed_batch: int = 32
    qdrant_path: Path = PROJECT_ROOT / "data" / "qdrant"
    qdrant_collection: str = "documents"
    min_score: float = 0.6  # dense cosine below this = unrelated (measured: off-topic ~0.55, hits 0.6-0.9)


# Shared settings instance
settings = Settings()
