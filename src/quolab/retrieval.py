"""Hybrid + adaptive retrieval: fuse lexical (BM25) and semantic (vector) results.

This is quolab's quality differentiator. Pure embeddings miss exact identifiers; pure
lexical misses intent. We run both and fuse with **Reciprocal Rank Fusion (RRF)**, and
let callers (or an LLM agent) pick a ``mode`` — with an ``auto`` heuristic that reads the
query shape.
"""

from __future__ import annotations

import re

from quolab.models import SearchResult

# Retrieval modes.
SEMANTIC = "semantic"
LEXICAL = "lexical"
HYBRID = "hybrid"
AUTO = "auto"
MODES = {SEMANTIC, LEXICAL, HYBRID, AUTO}

_RRF_K = 60  # standard RRF damping constant

# Signals that a query is "code-shaped" (favour including lexical search).
_CODE_SIGNALS = re.compile(
    r"""
    [a-z0-9]_[a-z0-9]      # snake_case
    | [a-z][A-Z]           # camelCase
    | \w+\(                # call()
    | \w+\.\w+             # member.access
    | /                    # path/like
    | ["'].+["']           # quoted exact phrase
    """,
    re.VERBOSE,
)


def select_mode(query: str) -> str:
    """Resolve ``auto`` to a concrete mode from the query's shape.

    - code-shaped (identifiers, calls, paths, quotes) → ``hybrid`` (lexical matters)
    - long natural-language intent (≥5 words, no code signals) → ``semantic``
    - otherwise → ``hybrid`` (safe default; fusion can't hurt)
    """
    if _CODE_SIGNALS.search(query):
        return HYBRID
    if len(query.split()) >= 5:
        return SEMANTIC
    return HYBRID


def reciprocal_rank_fusion(
    rankings: list[list[SearchResult]], k: int = _RRF_K
) -> list[SearchResult]:
    """Fuse several ranked result lists into one via RRF.

    RRF score for an item = sum over lists of 1 / (k + rank). Rank is 0-based position
    within each list. The fused score is written onto the returned SearchResult.
    """
    fused: dict[str, float] = {}
    best: dict[str, SearchResult] = {}
    for results in rankings:
        for rank, r in enumerate(results):
            key = f"{r.chunk.path}:{r.chunk.start_line}-{r.chunk.end_line}"
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank)
            # keep the richest copy (prefer the one already stored)
            best.setdefault(key, r)
    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    out: list[SearchResult] = []
    for key, score in ordered:
        r = best[key]
        out.append(SearchResult(chunk=r.chunk, score=score))
    return out
