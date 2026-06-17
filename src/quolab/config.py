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
    gemini_api_key: str = Field(default="", description="Gemini API key for the default embedder")
    embedder: str = Field(default="gemini", description="Embedder backend: 'gemini' or 'local'")
    embed_model: str = Field(
        default="gemini-embedding-001",
        description="Embedding model id (Gemini model, or sentence-transformers id when embedder=local)",
    )
    embed_dim: int = Field(default=768, description="Embedding dimensionality")
    embed_concurrency: int = Field(
        default=4, ge=1, description="Parallel embedding batches during indexing"
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
