"""Fetch a repo and chunk it into semantic units.

Fetch: shallow ``git clone`` (free) or a GitLab REST file walk (read-only targets).
Chunk: tree-sitter grammars split source into functions/classes/methods; when no
grammar is available the file is split into fixed line windows so nothing is missed.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import structlog

from quolab.config import Settings
from quolab.models import Chunk

log = structlog.get_logger(__name__)

# File extension → tree-sitter language name.
_EXT_LANG = {
    ".py": "python", ".go": "go", ".java": "java", ".ts": "typescript",
    ".tsx": "tsx", ".js": "javascript", ".jsx": "javascript", ".rb": "ruby",
    ".rs": "rust", ".cs": "c_sharp", ".kt": "kotlin", ".c": "c", ".cpp": "cpp",
    ".cc": "cpp", ".h": "cpp", ".hpp": "cpp", ".php": "php", ".scala": "scala",
}

# tree-sitter node types that represent a "definition" worth its own chunk.
_DEF_NODES = {
    "function_definition", "function_declaration", "method_definition",
    "method_declaration", "class_definition", "class_declaration",
    "function_item", "impl_item", "struct_item", "constructor_declaration",
    "interface_declaration", "trait_item",
}


def _repo_key(project_id: str, ref: str) -> str:
    return hashlib.sha1(f"{project_id}@{ref}".encode()).hexdigest()[:16]


def fetch_repo(settings: Settings, project_id: str, ref: str) -> Path:
    """Return a local path containing the repo's files for ``project_id@ref``.

    ``project_id`` may be a full clone URL or a ``group/repo`` path.
    """
    cache = Path(settings.repo_cache) / _repo_key(project_id, ref)
    if cache.exists():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)

    if settings.fetch == "git":
        url = _clone_url(settings, project_id)
        cmd = ["git", "clone", "--depth", "1"]
        if ref and ref not in ("HEAD", "default"):
            cmd += ["--branch", ref]
        cmd += [url, str(cache)]
        log.info("git_clone", project_id=project_id, ref=ref)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"git clone failed: {proc.stderr.strip()[:300]}")
        return cache

    if settings.fetch == "rest":
        _fetch_via_rest(settings, project_id, ref, cache)
        return cache

    raise ValueError(f"Unknown fetch method: {settings.fetch!r}")


def _fetch_via_rest(settings: Settings, project_id: str, ref: str, cache: Path) -> None:
    """Download matching source files via the GitLab REST API (read-only, no clone).

    Uses the free-tier repository tree + raw-file endpoints, so it works on any plan
    and on repos we only have read access to.
    """
    import httpx
    from urllib.parse import quote

    if project_id.startswith(("http://", "https://")):
        raise ValueError("QUOLAB_FETCH=rest expects a 'group/repo' path, not a URL")

    base = settings.gitlab_url.rstrip("/")
    pid = quote(project_id, safe="")
    headers = {"PRIVATE-TOKEN": settings.gitlab_token} if settings.gitlab_token else {}
    params_ref = {} if ref in ("", "HEAD", "default") else {"ref": ref}
    allowed = _allowed_suffixes(settings.include_glob_list)

    with httpx.Client(timeout=30, headers=headers) as client:
        # paginate the recursive tree
        blobs: list[str] = []
        page = 1
        while True:
            resp = client.get(
                f"{base}/api/v4/projects/{pid}/repository/tree",
                params={"recursive": "true", "per_page": 100, "page": page, **params_ref},
            )
            resp.raise_for_status()
            entries = resp.json()
            if not entries:
                break
            blobs += [
                e["path"] for e in entries
                if e.get("type") == "blob" and (not allowed or Path(e["path"]).suffix in allowed)
            ]
            if resp.headers.get("x-next-page"):
                page = int(resp.headers["x-next-page"])
            else:
                break

        for path in blobs:
            enc = quote(path, safe="")
            r = client.get(
                f"{base}/api/v4/projects/{pid}/repository/files/{enc}/raw", params=params_ref
            )
            if r.status_code != 200:
                continue
            dest = cache / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
    log.info("rest_fetch_complete", project_id=project_id, ref=ref, files=len(blobs))


def _clone_url(settings: Settings, project_id: str) -> str:
    if project_id.startswith(("http://", "https://", "git@")):
        url = project_id
    else:
        url = f"{settings.gitlab_url.rstrip('/')}/{project_id}.git"
    # Inject a read-only token for private repos (https only).
    if settings.gitlab_token and url.startswith("https://"):
        url = url.replace("https://", f"https://oauth2:{settings.gitlab_token}@", 1)
    return url


def _allowed_suffixes(globs: list[str]) -> set[str]:
    """Derive the set of file extensions from include globs (e.g. '**/*.py' -> '.py')."""
    suffixes: set[str] = set()
    for g in globs:
        suffix = Path(g).suffix  # '.py' from '**/*.py'
        if suffix:
            suffixes.add(suffix)
    return suffixes


def iter_source_files(root: Path, settings: Settings):
    """Yield (relative_path, text) for files matching the include globs."""
    allowed = _allowed_suffixes(settings.include_glob_list)
    for p in root.rglob("*"):
        if not p.is_file() or ".git" in p.parts:
            continue
        if allowed and p.suffix not in allowed:
            continue
        try:
            if p.stat().st_size > settings.max_file_bytes:
                continue
            yield p.relative_to(root).as_posix(), p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue


def _get_parser(lang: str):
    try:
        from tree_sitter_languages import get_parser

        return get_parser(lang)
    except Exception:  # pragma: no cover - grammar/install issues
        return None


def chunk_text(
    project_id: str, ref: str, path: str, text: str, settings: Settings
) -> list[Chunk]:
    """Chunk one file into semantic units, with a line-window fallback."""
    ext = Path(path).suffix
    lang = _EXT_LANG.get(ext)
    lines = text.splitlines()
    parser = _get_parser(lang) if lang else None

    if parser is not None:
        try:
            chunks = _chunk_with_treesitter(project_id, ref, path, text, parser)
            if chunks:
                return chunks
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("treesitter_failed_fallback", path=path, error=str(exc)[:120])

    return _chunk_by_lines(project_id, ref, path, lines, settings.chunk_max_lines)


def _chunk_with_treesitter(project_id, ref, path, text, parser) -> list[Chunk]:
    tree = parser.parse(text.encode("utf-8"))
    data = text.encode("utf-8")
    chunks: list[Chunk] = []

    def node_name(node) -> str:
        for child in node.children:
            if child.type in ("identifier", "name", "field_identifier", "type_identifier"):
                return data[child.start_byte:child.end_byte].decode("utf-8", "replace")
        return ""

    def visit(node) -> None:
        if node.type in _DEF_NODES:
            snippet = data[node.start_byte:node.end_byte].decode("utf-8", "replace")
            chunks.append(
                Chunk(
                    project_id=project_id, ref=ref, path=path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    symbol=node_name(node),
                    text=snippet,
                )
            )
            return  # don't descend into nested defs; the parent chunk covers them
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return chunks


def _chunk_by_lines(project_id, ref, path, lines, window) -> list[Chunk]:
    chunks: list[Chunk] = []
    for start in range(0, max(len(lines), 1), window):
        block = lines[start:start + window]
        if not any(line.strip() for line in block):
            continue
        chunks.append(
            Chunk(
                project_id=project_id, ref=ref, path=path,
                start_line=start + 1,
                end_line=start + len(block),
                symbol="",
                text="\n".join(block),
            )
        )
    return chunks


def resolve_commit(root: Path) -> str:
    """Return the HEAD commit SHA of a cloned repo, or '' if not a git checkout."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except OSError:
        return ""


def cleanup_repo(settings: Settings, project_id: str, ref: str) -> None:
    """Remove the cached clone for a project/ref."""
    cache = Path(settings.repo_cache) / _repo_key(project_id, ref)
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
