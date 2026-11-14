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
    chat_db_path: Path = PROJECT_ROOT / "data" / "chat.db"  # saved conversations
    ocr_enabled: bool = True  # read scanned PDF pages and images with RapidOCR
    ocr_min_chars: int = 50  # a page with less text than this (and an image on it) is OCR'd
    ocr_dpi: int = 200  # render resolution for OCR: higher = sharper but slower
    ocr_min_confidence: float = 0.5  # drop recognised text the engine is unsure about
    sql_server: str = "localhost"
    odbc_driver: str = "ODBC Driver 18 for SQL Server"
    databases_file: Path = BACKEND_DIR / "databases.json"
    db_reader_user: str = "chat_reader"  # read-only user the model's SQL runs as (EXECUTE AS USER)
    db_login_timeout_s: int = 5
    schema_recheck_s: int = 300  # how often to check whether a database schema changed
    max_result_rows: int = 50  # rows from a SQL query given to the model and the UI
    query_timeout_s: float = 10  # SQL queries running longer are stopped
    search_k: int = 5  # passages per search given to the model
    num_ctx: int = 16384  # model context window; Ollama's small default silently drops the system prompt
    max_tool_rounds: int = 4  # searches per answer before the model must answer
    min_score: float = 0.6  # dense cosine below this = unrelated (measured: off-topic ~0.55, hits 0.6-0.9)


# Shared settings instance
settings = Settings()
