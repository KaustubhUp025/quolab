from quolab.models import Chunk
from quolab.store import SqliteVecStore, _cosine_topk

import numpy as np


def test_cosine_topk_orders_by_similarity():
    query = np.array([1.0, 0.0, 0.0])
    matrix = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.5, 0.5, 0.0]])
    ranked = _cosine_topk(query, matrix, k=2)
    assert ranked[0][0] == 1  # exact match first
    assert ranked[0][1] > ranked[1][1]


def test_sqlite_store_roundtrip(tmp_path, fake_embedder):
    store = SqliteVecStore(str(tmp_path / "db.sqlite"))
    chunks = [
        Chunk("proj", "HEAD", "a.py", 1, 5, "acquire_lock", "redis.set nx locked"),
        Chunk("proj", "HEAD", "b.py", 1, 5, "compensate", "saga compensation undo rollback"),
    ]
    vecs = fake_embedder.embed_documents([c.text for c in chunks])

    assert store.has_index("proj", "HEAD") is False
    store.add(chunks, vecs)
    assert store.has_index("proj", "HEAD") is True

    qvec = fake_embedder.embed_query("saga compensation undo rollback")
    results = store.search("proj", "HEAD", qvec, k=2)
    assert results[0].chunk.symbol == "compensate"  # exact text -> top hit
    assert results[0].score >= results[1].score


def test_lexical_search_finds_exact_identifier(tmp_path, fake_embedder):
    store = SqliteVecStore(str(tmp_path / "db.sqlite"))
    chunks = [
        Chunk("proj", "HEAD", "a.py", 1, 5, "acquire_lock", "def acquire_lock(): redis.set"),
        Chunk("proj", "HEAD", "b.py", 1, 5, "ship", "def ship_order(): pass"),
    ]
    store.add(chunks, fake_embedder.embed_documents([c.text for c in chunks]))
    results = store.lexical_search("proj", "HEAD", "acquire_lock", k=5)
    assert results
    assert results[0].chunk.path == "a.py"


def test_lexical_search_empty_when_no_terms(tmp_path, fake_embedder):
    store = SqliteVecStore(str(tmp_path / "db.sqlite"))
    store.add([Chunk("p", "HEAD", "a.py", 1, 2, "x", "code")],
              fake_embedder.embed_documents(["code"]))
    assert store.lexical_search("p", "HEAD", "!!!", k=5) == []


def test_lexical_search_after_clear_is_empty(tmp_path, fake_embedder):
    store = SqliteVecStore(str(tmp_path / "db.sqlite"))
    store.add([Chunk("p", "HEAD", "a.py", 1, 2, "acquire_lock", "acquire_lock here")],
              fake_embedder.embed_documents(["acquire_lock here"]))
    store.clear("p", "HEAD")
    assert store.lexical_search("p", "HEAD", "acquire_lock", k=5) == []


def test_clear_removes_only_target_ref(tmp_path, fake_embedder):
    store = SqliteVecStore(str(tmp_path / "db.sqlite"))
    c1 = Chunk("proj", "main", "a.py", 1, 2, "x", "alpha")
    c2 = Chunk("proj", "dev", "a.py", 1, 2, "x", "beta")
    store.add([c1], fake_embedder.embed_documents(["alpha"]))
    store.add([c2], fake_embedder.embed_documents(["beta"]))
    store.clear("proj", "main")
    assert store.has_index("proj", "main") is False
    assert store.has_index("proj", "dev") is True
