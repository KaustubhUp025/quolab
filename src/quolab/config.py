"""Configuration for quolab. All settings are env-driven (prefix ``QUOLAB_``)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="QUOLAB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Embeddings ---
    embedder: str = Field(
        default="local", description="Embedder backend: 'local' (default), 'gemini' or 'hash'"
    )
    embed_model: str = Field(
        default="Qwen/Qwen3-Embedding-0.6B",
        description="Embedding model id (sentence-transformers id when embedder=local, Gemini model id when embedder=gemini)",
    )
    embed_dim: int = Field(
        default=1024, description="Embedding dimensionality (Qwen3-Embedding-0.6B native = 1024)"
    )
    embed_concurrency: int = Field(
        default=4, ge=1, description="Parallel embedding batches during indexing"
    )
    embed_device: str = Field(
        default="auto",
        description="Device for the local embedder: 'auto' (GPU if it fits, else CPU), 'cuda' or 'cpu'",
    )
    embed_batch_size: int = Field(
        default=16, ge=1, description="Encode batch size for the local embedder"
    )
    gemini_api_key: str = Field(
        default="", description="Gemini API key (only used when embedder=gemini)"
    )

    # --- Vector store ---
    store: str = Field(default="sqlite", description="Vector store backend: 'sqlite' or 'pgvector'")
    sqlite_path: str = Field(default=".quolab_cache/index.db", description="SQLite index path")
    pg_dsn: str = Field(default="", description="Postgres DSN (when store=pgvector)")

    # --- Source fetch ---
    fetch: str = Field(default="git", description="Repo fetch method: 'git' (clone) or 'rest'")
    gitlab_url: str = Field(default="https://gitlab.com", description="GitLab base URL")
    gitlab_token: str = Field(default="", description="GitLab read-only PAT (for fetch=rest)")
    repo_cache: str = Field(default=".repos", description="Where shallow clones are stored")

    # --- Indexing ---
    max_file_bytes: int = Field(default=400_000, description="Skip files larger than this")
    chunk_max_lines: int = Field(default=120, description="Line-window size when no grammar")
    include_globs: str = Field(
        default="**/*.py,**/*.go,**/*.java,**/*.ts,**/*.js,**/*.rb,**/*.rs,**/*.cs,**/*.kt",
        description="Comma-separated globs of files to index",
    )

    # --- Server ---
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    log_level: str = Field(default="info")

    @property
    def include_glob_list(self) -> list[str]:
        return [g.strip() for g in self.include_globs.split(",") if g.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
