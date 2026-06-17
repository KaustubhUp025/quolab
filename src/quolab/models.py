"""Shared data types for quolab."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A semantic unit of code extracted from a file."""

    project_id: str
    ref: str
    path: str
    start_line: int
    end_line: int
    symbol: str  # function/class/method name, or "" for a line-window chunk
    text: str

    @property
    def chunk_id(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


@dataclass
class SearchResult:
    """A scored chunk returned from a query."""

    chunk: Chunk
    score: float


@dataclass
class IndexStats:
    """Outcome of indexing a project."""

    project_id: str
    ref: str
    files: int = 0
    chunks: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
