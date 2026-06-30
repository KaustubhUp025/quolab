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

    # --- Reranking (opt-in cross-encoder second stage) ---
    rerank_enabled: bool = Field(
        default=False,
        description="Rerank fused candidates with a cross-encoder (accuracy up, latency up). "
        "Needs the 'local' extra; downloads the reranker model on first use.",
    )
    rerank_model: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        description="Cross-encoder reranker id (sentence-transformers CrossEncoder). "
        "Default is Apache-2.0 — avoid CC-BY-NC rerankers for an OSS deployment.",
    )
    rerank_device: str = Field(
        default="auto", description="Device for the reranker: 'auto' | 'cuda' | 'cpu'"
    )
    rerank_top_k: int = Field(
        default=20, ge=1,
        description="How many top candidates to rerank; the reranked best max_results win.",
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
    fetch_allow_hosts: str = Field(
        default="",
        description="Comma-separated host allowlist for remote fetch (clone/REST). "
        "Empty = derive from QUOLAB_GITLAB_URL's host. Use '*' to allow any host. "
        "Blocks SSRF / token exfiltration to arbitrary hosts.",
    )
    allow_local_path: bool = Field(
        default=True,
        description="Allow indexing a local on-disk directory passed as project_id "
        "(needed for CLI/dev/bench). Set false in any deployed or multi-tenant "
        "service to prevent arbitrary local-file reads.",
    )

    # --- Indexing ---
    max_file_bytes: int = Field(default=400_000, description="Skip files larger than this")
    chunk_max_lines: int = Field(default=120, description="Line-window size when no grammar")
    chunk_max_chars: int = Field(
        default=1500,
        description="cAST chunk budget in non-whitespace characters: a definition larger "
        "than this is split; small adjacent non-definition statements are packed up to it.",
    )
    include_globs: str = Field(
        default="**/*.py,**/*.go,**/*.java,**/*.ts,**/*.js,**/*.rb,**/*.rs,**/*.cs,**/*.kt",
        description="Comma-separated globs of files to index",
    )

    # --- Server / limits ---
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    log_level: str = Field(default="info")
    allow_auto_index: bool = Field(
        default=True,
        description="Let search build the index on first use. Set false on a read-only "
        "deployment so search never triggers a clone (pre-warm explicitly via /index).",
    )
    max_results_cap: int = Field(
        default=50, ge=1,
        description="Hard cap on results per query across all entrypoints (DoS guard).",
    )

    @property
    def include_glob_list(self) -> list[str]:
        return [g.strip() for g in self.include_globs.split(",") if g.strip()]

    @property
    def fetch_allow_host_list(self) -> list[str]:
        """Hosts quolab may fetch from. Defaults to the QUOLAB_GITLAB_URL host."""
        if self.fetch_allow_hosts.strip():
            return [h.strip().lower() for h in self.fetch_allow_hosts.split(",") if h.strip()]
        from urllib.parse import urlsplit

        host = urlsplit(self.gitlab_url).hostname
        return [host.lower()] if host else []


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
