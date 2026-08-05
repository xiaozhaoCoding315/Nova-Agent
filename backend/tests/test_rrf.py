from app.core.rag.rrf import rrf_fuse
from app.models.domain import RetrievedChunk


def test_single_list_preserves_order():
    chunks = [
        RetrievedChunk(id="1", content="A", source="d", score_type="dense"),
        RetrievedChunk(id="2", content="B", source="d", score_type="dense"),
        RetrievedChunk(id="3", content="C", source="d", score_type="dense"),
    ]
    result = rrf_fuse([chunks], top_n=2)
    assert [c.id for c in result] == ["1", "2"]


def test_multi_list_cross_boost():
    l1 = [
        RetrievedChunk(id="1", content="A", source="d", score_type="dense"),
        RetrievedChunk(id="2", content="B", source="d", score_type="dense"),
    ]
    l2 = [
        RetrievedChunk(id="2", content="B", source="d", score_type="keyword"),
        RetrievedChunk(id="3", content="C", source="d", score_type="keyword"),
    ]
    result = rrf_fuse([l1, l2], top_n=3)
    assert result[0].id == "2"  # appears in both → boosted
    assert len(result) == 3


def test_empty_input():
    assert rrf_fuse([], top_n=5) == []
    assert rrf_fuse([[]], top_n=5) == []


def test_top_n_limits_output():
    l1 = [RetrievedChunk(id=str(i), content=str(i), source="d", score_type="dense") for i in range(20)]
    result = rrf_fuse([l1], top_n=5)
    assert len(result) == 5
