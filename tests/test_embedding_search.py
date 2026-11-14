"""Tests for the production Faiss chunk-search path (embedding/search.py)."""

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from embedding.search import (
    EMBEDDING_DIM,
    ChunkSearchEngine,
    ChunkVectorIndex,
    EmbeddingDataError,
    JinaQueryEncoder,
    _batch_vectors,
    iter_embedding_batches,
    main,
)

SCHEMA = pa.schema(
    [
        ("id", pa.int64()),
        ("chunk_index", pa.int16()),
        ("start_offset", pa.int32()),
        ("end_offset", pa.int32()),
        ("chunk_text", pa.string()),
        ("embedding", pa.list_(pa.float32(), EMBEDDING_DIM)),
    ]
)


def _vector(position: int, scale: float = 1.0) -> np.ndarray:
    vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    vector[position] = scale
    return vector


def _write_shard(path, rows, dimension: int = EMBEDDING_DIM) -> None:
    ids = pa.array([row[0] for row in rows], type=pa.int64())
    chunk_indices = pa.array([row[1] for row in rows], type=pa.int16())
    start_offsets = pa.array([0] * len(rows), type=pa.int32())
    end_offsets = pa.array([1] * len(rows), type=pa.int32())
    texts = pa.array([f"chunk {row[1]}" for row in rows], type=pa.string())
    flat = pa.array([value for row in rows for value in row[2]], type=pa.float32())
    embeddings = pa.FixedSizeListArray.from_arrays(flat, dimension)
    schema = (
        SCHEMA
        if dimension == EMBEDDING_DIM
        else pa.schema(
            [
                ("id", pa.int64()),
                ("chunk_index", pa.int16()),
                ("start_offset", pa.int32()),
                ("end_offset", pa.int32()),
                ("chunk_text", pa.string()),
                ("embedding", pa.list_(pa.float32(), dimension)),
            ]
        )
    )
    table = pa.Table.from_arrays(
        [ids, chunk_indices, start_offsets, end_offsets, texts, embeddings],
        schema=schema,
    )
    pq.write_table(table, path)


class _FakeTensor:
    def __init__(self, values: np.ndarray) -> None:
        self.values = values

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self) -> np.ndarray:
        return self.values


class _FakeModel:
    def __init__(self, vector: np.ndarray) -> None:
        self.vector = vector
        self.calls: list[tuple[list[str], str, str]] = []

    def encode(self, texts, task, prompt_name):
        self.calls.append((texts, task, prompt_name))
        return [_FakeTensor(self.vector)]


class _FakeEncoder:
    dimension = EMBEDDING_DIM

    def __init__(self, vector: np.ndarray) -> None:
        self.vector = vector
        self.queries: list[str] = []

    def encode(self, query: str) -> np.ndarray:
        self.queries.append(query)
        return self.vector


def test_iter_embedding_batches_streams_every_shard(tmp_path):
    rows_a = [(10, 0, _vector(0)), (10, 1, _vector(1))]
    rows_b = [(20, 0, _vector(2, scale=3.0))]
    _write_shard(tmp_path / "part-00.parquet", rows_a)
    _write_shard(tmp_path / "part-01.parquet", rows_b)

    batches = list(iter_embedding_batches(tmp_path, batch_size=2))

    assert [batch.ids.tolist() for batch in batches] == [[10, 10], [20]]
    assert [batch.chunk_indices.tolist() for batch in batches] == [[0, 1], [0]]
    vectors = np.vstack([batch.vectors for batch in batches])
    assert vectors.dtype == np.float32
    np.testing.assert_array_equal(
        vectors, np.array([_vector(0), _vector(1), _vector(2, scale=3.0)])
    )


def test_missing_required_column_raises(tmp_path):
    table = pa.table(
        {
            "id": pa.array([1], type=pa.int64()),
            "embedding": pa.array(
                [_vector(0)], type=pa.list_(pa.float32(), EMBEDDING_DIM)
            ),
        }
    )
    pq.write_table(table, tmp_path / "broken.parquet")

    with pytest.raises(EmbeddingDataError, match="chunk_index"):
        list(iter_embedding_batches(tmp_path))


def test_wrong_embedding_dimension_raises(tmp_path):
    _write_shard(
        tmp_path / "part-00.parquet",
        [(1, 0, np.ones(8, dtype=np.float32))],
        dimension=8,
    )

    with pytest.raises(EmbeddingDataError, match="list size 8, expected 1024"):
        list(iter_embedding_batches(tmp_path))


def test_null_embedding_raises(tmp_path):
    embeddings = pa.FixedSizeListArray.from_arrays(
        pa.array(np.zeros(EMBEDDING_DIM, dtype=np.float32), type=pa.float32()),
        EMBEDDING_DIM,
        mask=pa.array([True]),
    )

    with pytest.raises(EmbeddingDataError, match="null rows"):
        _batch_vectors(embeddings, tmp_path / "shard.parquet", EMBEDDING_DIM)


def test_non_finite_embedding_raises(tmp_path):
    vector = _vector(0)
    vector[1] = np.nan
    _write_shard(tmp_path / "part-00.parquet", [(101, 0, vector)])

    with pytest.raises(EmbeddingDataError, match="NaN or infinite"):
        ChunkVectorIndex.from_parquet(tmp_path)


def test_empty_embedding_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="no Parquet shards"):
        list(iter_embedding_batches(tmp_path))


def test_empty_shard_raises(tmp_path):
    table = pa.Table.from_arrays(
        [
            pa.array([], type=pa.int64()),
            pa.array([], type=pa.int16()),
            pa.array([], type=pa.int32()),
            pa.array([], type=pa.int32()),
            pa.array([], type=pa.string()),
            pa.array([], type=pa.list_(pa.float32(), EMBEDDING_DIM)),
        ],
        schema=SCHEMA,
    )
    pq.write_table(table, tmp_path / "empty.parquet")

    with pytest.raises(EmbeddingDataError, match="no embeddings"):
        ChunkVectorIndex.from_parquet(tmp_path)


def test_index_normalises_and_ranks_by_cosine_similarity(tmp_path):
    _write_shard(
        tmp_path / "part-00.parquet",
        [
            (101, 0, _vector(1)),
            (202, 3, _vector(0, scale=100.0)),
            (303, 1, _vector(2)),
        ],
    )

    index = ChunkVectorIndex.from_parquet(tmp_path)
    hits = index.search(_vector(0), top_k=2)

    assert index.size == 3
    assert (hits[0].story_id, hits[0].chunk_index) == (202, 3)
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)
    assert hits[1].score == pytest.approx(0.0, abs=1e-6)


def test_search_returns_all_hits_when_top_k_exceeds_index_size(tmp_path):
    _write_shard(
        tmp_path / "part-00.parquet",
        [
            (101, 0, _vector(0)),
            (202, 1, _vector(1)),
        ],
    )

    index = ChunkVectorIndex.from_parquet(tmp_path)
    hits = index.search(_vector(0), top_k=10)

    assert len(hits) == 2
    assert all(hit.story_id > 0 and hit.chunk_index >= 0 for hit in hits)
    assert hits[0].story_id == 101


def test_query_vector_dimension_mismatch_raises(tmp_path):
    _write_shard(tmp_path / "part-00.parquet", [(101, 0, _vector(0))])
    index = ChunkVectorIndex.from_parquet(tmp_path)

    with pytest.raises(ValueError, match="dimensions"):
        index.search(np.zeros(EMBEDDING_DIM - 1, dtype=np.float32), top_k=1)


def test_search_rejects_non_positive_top_k(tmp_path):
    _write_shard(tmp_path / "part-00.parquet", [(101, 0, _vector(0))])
    index = ChunkVectorIndex.from_parquet(tmp_path)

    with pytest.raises(ValueError, match="top_k"):
        index.search(_vector(0), top_k=0)


def test_max_vectors_limits_the_index(tmp_path):
    _write_shard(
        tmp_path / "part-00.parquet",
        [
            (101, 0, _vector(0)),
            (202, 1, _vector(1)),
            (303, 2, _vector(2)),
        ],
    )

    index = ChunkVectorIndex.from_parquet(tmp_path, max_vectors=2)

    assert index.size == 2
    assert [hit.story_id for hit in index.search(_vector(0), top_k=3)] == [101, 202]


def test_engine_encodes_the_query_and_returns_hits(tmp_path):
    _write_shard(
        tmp_path / "part-00.parquet",
        [
            (101, 0, _vector(0)),
            (202, 1, _vector(1)),
        ],
    )
    encoder = _FakeEncoder(_vector(1))

    engine = ChunkSearchEngine.from_parquet(tmp_path, encoder=encoder)
    hits = engine.search("a cabin weekend", top_k=1)

    assert encoder.queries == ["a cabin weekend"]
    assert (hits[0].story_id, hits[0].chunk_index) == (202, 1)
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)


def test_engine_rejects_mismatched_dimensions(tmp_path):
    _write_shard(tmp_path / "part-00.parquet", [(101, 0, _vector(0))])
    index = ChunkVectorIndex.from_parquet(tmp_path)
    encoder = _FakeEncoder(_vector(0))
    encoder.dimension = EMBEDDING_DIM - 1

    with pytest.raises(ValueError, match="does not match"):
        ChunkSearchEngine(index, encoder)


def test_query_encoder_rejects_unknown_task_and_prompt():
    with pytest.raises(ValueError, match="task"):
        JinaQueryEncoder(task="reranking")
    with pytest.raises(ValueError, match="prompt_name"):
        JinaQueryEncoder(prompt_name="passage")


def test_query_encoder_returns_a_float32_vector():
    model = _FakeModel(_vector(4))
    encoder = JinaQueryEncoder()
    encoder._model = model

    vector = encoder.encode("rivals to lovers at summer camp")

    assert vector.shape == (EMBEDDING_DIM,)
    assert vector.dtype == np.float32
    assert model.calls == [(["rivals to lovers at summer camp"], "retrieval", "query")]


def test_query_encoder_rejects_wrong_model_dimension():
    encoder = JinaQueryEncoder()
    encoder._model = _FakeModel(np.zeros(8, dtype=np.float32))

    with pytest.raises(ValueError, match="expected 1024"):
        encoder.encode("query")


def test_query_encoder_rejects_empty_queries():
    with pytest.raises(ValueError, match="non-empty"):
        JinaQueryEncoder().encode("   ")


def test_cli_reports_a_missing_embedding_directory(tmp_path, capsys):
    exit_code = main(["--parquet-dir", str(tmp_path / "missing"), "query"])

    assert exit_code == 1
    assert "does not exist" in capsys.readouterr().err
