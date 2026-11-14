from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # app_version: str = "1.0.0"
    app_name: str = "Local RAG Chat Application"
    ollama_host:str="http://localhost:11434"
    chat_model:str="qwen3:14b"
    embed_model:str="nomic-embed-text"
    cors_origins:list[str] = ["http://localhost:4200"]
    data_dir:str="../data"
    # # debug: bool = True
    # # api_prefix: str = "/api"
    # qdrant_url: str = "http://localhost:6333"
    # qdrant_collection: str = "documents"
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

# Shared settings instance
settings = Settings()