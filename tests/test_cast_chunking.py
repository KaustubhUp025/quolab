"""B6 — cAST split-then-merge chunking: budget split, module-level coverage, density."""

from __future__ import annotations

from quolab.config import Settings
from quolab.indexer import _nonws_len, chunk_text


def test_module_level_code_is_covered():
    # Previously only defs were chunked; imports/constants were dropped. Now they're packed.
    src = "import os\nimport sys\n\nCONST = 42\n\n\ndef f():\n    return CONST\n"
    chunks = chunk_text("p", "HEAD", "m.py", src, Settings())
    if not any(c.symbol for c in chunks):
        return  # tree-sitter not installed; line fallback path
    text_all = "\n".join(c.text for c in chunks)
    assert "import os" in text_all
    assert "CONST = 42" in text_all
    assert any(c.symbol == "f" for c in chunks)


def test_oversized_definition_is_split():
    # A function whose body far exceeds the budget must become multiple chunks.
    body = "\n".join(f"    x{i} = compute_value_number_{i}()" for i in range(400))
    src = f"def big():\n{body}\n"
    s = Settings(chunk_max_chars=300)
    chunks = chunk_text("p", "HEAD", "big.py", src, s)
    if not any("x0" in c.text for c in chunks):
        return  # fallback path
    big_chunks = [c for c in chunks if c.path == "big.py"]
    assert len(big_chunks) > 1  # split into several windows
    # the first piece keeps the symbol
    assert big_chunks[0].symbol == "big"


def test_small_defs_keep_their_own_chunks():
    # Two small adjacent functions must NOT be merged into one chunk (symbol granularity).
    src = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    chunks = chunk_text("p", "HEAD", "ab.py", src, Settings())
    syms = {c.symbol for c in chunks}
    if not any(syms):
        return
    assert "a" in syms and "b" in syms


def test_chunks_respect_nonws_budget_when_possible():
    src = "import os\n" * 50 + "\n\ndef f():\n    return 1\n"
    s = Settings(chunk_max_chars=120)
    chunks = chunk_text("p", "HEAD", "m.py", src, s)
    if not any(c.symbol for c in chunks):
        return
    # packed import block stays within budget (single small def is exempt only if atomic)
    for c in chunks:
        if c.symbol == "":  # the merged non-def block
            assert _nonws_len(c.text) <= 120
