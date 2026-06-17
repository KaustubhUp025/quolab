from quolab.config import Settings
from quolab.indexer import _allowed_suffixes, chunk_text

PY_SOURCE = '''\
import os


def acquire_lock(key):
    """Forward step."""
    return redis.set(key, "locked", nx=True)


class SagaOrchestrator:
    def step(self, action):
        self.actions.append(action)

    def compensate(self):
        for a in reversed(self.actions):
            a.undo()
'''


def test_allowed_suffixes_from_globs():
    suffixes = _allowed_suffixes(["**/*.py", "**/*.go", "src/*.java"])
    assert suffixes == {".py", ".go", ".java"}


def test_chunk_python_splits_into_definitions():
    s = Settings()
    chunks = chunk_text("proj", "HEAD", "saga.py", PY_SOURCE, s)
    symbols = {c.symbol for c in chunks}
    # tree-sitter (if installed) yields named defs; fallback yields one line-window chunk.
    assert chunks
    if any(c.symbol for c in chunks):
        assert "acquire_lock" in symbols
        assert "SagaOrchestrator" in symbols
    for c in chunks:
        assert c.path == "saga.py"
        assert c.start_line >= 1
        assert c.end_line >= c.start_line


def test_line_window_fallback_for_unknown_language():
    s = Settings(chunk_max_lines=2)
    text = "a\nb\nc\nd\ne\n"
    chunks = chunk_text("proj", "HEAD", "notes.unknownext", text, s)
    assert len(chunks) == 3  # 5 lines / window 2 -> 3 chunks
    assert chunks[0].symbol == ""
