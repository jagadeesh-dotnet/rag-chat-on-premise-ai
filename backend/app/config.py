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


# Shared settings instance
settings = Settings()
