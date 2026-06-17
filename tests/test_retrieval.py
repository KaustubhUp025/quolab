from quolab.models import Chunk, SearchResult
from quolab.retrieval import (
    HYBRID,
    SEMANTIC,
    reciprocal_rank_fusion,
    select_mode,
)


def _r(path, score=0.0):
    return SearchResult(Chunk("p", "HEAD", path, 1, 2, "", "x"), score)


def test_select_mode_code_query_is_hybrid():
    assert select_mode("acquire_lock()") == HYBRID
    assert select_mode("SagaOrchestrator.compensate") == HYBRID
    assert select_mode('"exactly this"') == HYBRID
    assert select_mode("src/lock/redis.py") == HYBRID


def test_select_mode_natural_language_is_semantic():
    assert select_mode("where do we roll back a failed payment saga") == SEMANTIC


def test_rrf_rewards_agreement_across_lists():
    # 'b.py' appears high in both lists -> should win after fusion.
    vector = [_r("a.py"), _r("b.py"), _r("c.py")]
    lexical = [_r("b.py"), _r("d.py"), _r("a.py")]
    fused = reciprocal_rank_fusion([vector, lexical])
    assert fused[0].chunk.path == "b.py"
    # fused score is descending
    assert all(fused[i].score >= fused[i + 1].score for i in range(len(fused) - 1))


def test_rrf_dedupes_by_chunk_id():
    fused = reciprocal_rank_fusion([[_r("a.py")], [_r("a.py")]])
    assert len(fused) == 1


def test_rrf_empty():
    assert reciprocal_rank_fusion([[], []]) == []
