"""Tests for the production Faiss chunk-search path (embedding/search.py and split modules)."""

from __future__ import annotations

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import embedding.search as search_facade
from embedding.data_loading import (
    DEFAULT_SAMPLE_PATH,
    EMBEDDING_DIM,
    EmbeddingDataError,
    _batch_vectors,
    iter_embedding_batches,
    iter_sample_chunks,
)
from embedding.search import main
from embedding.search_engine import ChunkSearchEngine
from embedding.text_encoder import JinaTextEncoder
from embedding.vector_index import ChunkVectorIndex

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


def _write_sample(path, rows) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


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
    def __init__(self, vectors: np.ndarray) -> None:
        self.vectors = np.atleast_2d(np.asarray(vectors, dtype=np.float32))
        self.calls: list[tuple[list[str], str, str, int | None]] = []

    def encode(self, texts, task, prompt_name, max_length=None):
        self.calls.append((list(texts), task, prompt_name, max_length))
        rows = np.tile(self.vectors[0], (len(texts), 1))
        return _FakeTensor(rows)


class _FakeEncoder:
    dimension = EMBEDDING_DIM

    def __init__(self, query_vector=None, document_map=None) -> None:
        self.query_vector = _vector(0) if query_vector is None else query_vector
        self.document_map = document_map or {}
        self.queries: list[str] = []
        self.documents: list[str] = []

    def encode_query(self, query: str) -> np.ndarray:
        self.queries.append(query)
        return self.query_vector

    def encode_documents(self, documents) -> np.ndarray:
        documents = list(documents)
        self.documents.extend(documents)
        if self.document_map:
            return np.vstack([self.document_map[text] for text in documents])
        return np.tile(_vector(0), (len(documents), 1))


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


def test_committed_sample_has_200_unique_chunks():
    batches = list(iter_sample_chunks(DEFAULT_SAMPLE_PATH, batch_size=64))

    assert [len(batch.ids) for batch in batches] == [64, 64, 64, 8]
    ids = np.concatenate([batch.ids for batch in batches])
    chunk_indices = np.concatenate([batch.chunk_indices for batch in batches])
    texts = [text for batch in batches for text in batch.texts]

    assert len(ids) == 200
    assert len(set(ids.tolist())) == 200
    np.testing.assert_array_equal(chunk_indices, np.zeros(200, dtype=np.int32))
    assert all(text.strip() for text in texts)


def test_sample_loader_numbers_repeated_ids(tmp_path):
    sample = tmp_path / "sample.jsonl"
    _write_sample(
        sample,
        [
            {"id": 7, "content": "first chunk"},
            {"id": 7, "content": "second chunk"},
            {"id": 9, "content": "other story"},
        ],
    )

    batches = list(iter_sample_chunks(sample, batch_size=10))

    assert [batch.ids.tolist() for batch in batches] == [[7, 7, 9]]
    assert [batch.chunk_indices.tolist() for batch in batches] == [[0, 1, 0]]
    assert batches[0].texts == ["first chunk", "second chunk", "other story"]


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("{not json", "invalid JSON"),
        ('{"content": "text"}', "'id' must be an integer"),
        ('{"id": "7", "content": "text"}', "'id' must be an integer"),
        ('{"id": 7}', "'content' must be a non-empty string"),
        ('{"id": 7, "content": "   "}', "'content' must be a non-empty string"),
    ],
)
def test_sample_loader_rejects_malformed_rows(tmp_path, line, message):
    sample = tmp_path / "sample.jsonl"
    sample.write_text(line + "\n", encoding="utf-8")

    with pytest.raises(EmbeddingDataError, match=message):
        list(iter_sample_chunks(sample))


def test_sample_loader_rejects_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="sample file does not exist"):
        list(iter_sample_chunks(tmp_path / "missing.jsonl"))


def test_index_from_sample_encodes_documents_and_ranks(tmp_path):
    sample = tmp_path / "sample.jsonl"
    _write_sample(
        sample,
        [
            {"id": 101, "content": "sailing"},
            {"id": 202, "content": "camping"},
            {"id": 303, "content": "hiking"},
        ],
    )
    encoder = _FakeEncoder(
        _vector(1),
        document_map={
            "sailing": _vector(0),
            "camping": _vector(1),
            "hiking": _vector(2),
        },
    )

    index = ChunkVectorIndex.from_sample(sample, encoder=encoder, batch_size=2)
    hits = index.search(_vector(1), top_k=1)

    assert encoder.documents == ["sailing", "camping", "hiking"]
    assert index.size == 3
    assert (hits[0].story_id, hits[0].chunk_index) == (202, 0)


def test_index_from_sample_respects_max_vectors(tmp_path):
    sample = tmp_path / "sample.jsonl"
    _write_sample(
        sample,
        [{"id": 101, "content": "one"}, {"id": 202, "content": "two"}],
    )
    encoder = _FakeEncoder()

    index = ChunkVectorIndex.from_sample(
        sample, encoder=encoder, batch_size=1, max_vectors=1
    )

    assert index.size == 1
    assert encoder.documents == ["one"]


def test_engine_from_sample_indexes_and_searches(tmp_path):
    sample = tmp_path / "sample.jsonl"
    _write_sample(
        sample,
        [
            {"id": 101, "content": "sailing"},
            {"id": 202, "content": "camping"},
        ],
    )
    encoder = _FakeEncoder(
        _vector(1),
        document_map={"sailing": _vector(0), "camping": _vector(1)},
    )

    engine = ChunkSearchEngine.from_sample(sample, encoder=encoder, batch_size=1)
    hits = engine.search("a tent weekend", top_k=1)

    assert engine.index.size == 2
    assert encoder.documents == ["sailing", "camping"]
    assert encoder.queries == ["a tent weekend"]
    assert hits[0].story_id == 202


def test_jina_encoder_rejects_unknown_task():
    with pytest.raises(ValueError, match="task"):
        JinaTextEncoder(task="reranking")


def test_jina_encoder_rejects_invalid_batching_options():
    with pytest.raises(ValueError, match="encode_batch_size"):
        JinaTextEncoder(encode_batch_size=0)
    with pytest.raises(ValueError, match="max_length"):
        JinaTextEncoder(max_length=0)


def test_jina_encoder_returns_a_float32_vector():
    model = _FakeModel(_vector(4))
    encoder = JinaTextEncoder()
    encoder._model = model

    vector = encoder.encode_query("rivals to lovers at summer camp")

    assert vector.shape == (EMBEDDING_DIM,)
    assert vector.dtype == np.float32
    assert model.calls == [
        (["rivals to lovers at summer camp"], "retrieval", "query", None)
    ]


def test_jina_encoder_uses_the_document_prompt_for_chunks():
    model = _FakeModel(_vector(2))
    encoder = JinaTextEncoder()
    encoder._model = model

    matrix = encoder.encode_documents(["first chunk", "second chunk"])

    assert matrix.shape == (2, EMBEDDING_DIM)
    assert matrix.dtype == np.float32
    assert model.calls == [
        (["first chunk", "second chunk"], "retrieval", "document", None)
    ]


def test_jina_encoder_splits_documents_into_batches():
    model = _FakeModel(_vector(3))
    encoder = JinaTextEncoder(encode_batch_size=2)
    encoder._model = model

    matrix = encoder.encode_documents(["a", "b", "c"])

    assert matrix.shape == (3, EMBEDDING_DIM)
    assert [call[0] for call in model.calls] == [["a", "b"], ["c"]]
    assert [call[2] for call in model.calls] == ["document", "document"]


def test_jina_encoder_passes_max_length_to_the_model():
    model = _FakeModel(_vector(0))
    encoder = JinaTextEncoder(max_length=512)
    encoder._model = model

    encoder.encode_documents(["a long chunk"])

    assert model.calls[0][3] == 512


def test_jina_encoder_rejects_wrong_model_dimension():
    encoder = JinaTextEncoder()
    encoder._model = _FakeModel(np.zeros((1, 8), dtype=np.float32))

    with pytest.raises(ValueError, match="expected 1024"):
        encoder.encode_query("query")


def test_jina_encoder_rejects_empty_inputs():
    encoder = JinaTextEncoder()

    with pytest.raises(ValueError, match="non-empty"):
        encoder.encode_query("   ")
    with pytest.raises(ValueError, match="must not be empty"):
        encoder.encode_documents([])
    with pytest.raises(ValueError, match="non-empty strings"):
        encoder.encode_documents(["valid", " "])


def test_cli_reports_a_missing_embedding_directory(tmp_path, capsys):
    exit_code = main(["--parquet-dir", str(tmp_path / "missing"), "query"])

    assert exit_code == 1
    assert "does not exist" in capsys.readouterr().err


def test_search_facade_reexports_split_modules():
    from embedding import data_loading, search_engine, text_encoder, vector_index

    assert search_facade.EMBEDDING_DIM == data_loading.EMBEDDING_DIM
    assert search_facade.EmbeddingBatch is data_loading.EmbeddingBatch
    assert search_facade.ChunkTextBatch is data_loading.ChunkTextBatch
    assert search_facade.EmbeddingDataError is data_loading.EmbeddingDataError
    assert search_facade.iter_embedding_batches is data_loading.iter_embedding_batches
    assert search_facade.iter_sample_chunks is data_loading.iter_sample_chunks
    assert search_facade.ChunkVectorIndex is vector_index.ChunkVectorIndex
    assert search_facade.SearchHit is vector_index.SearchHit
    assert search_facade.JinaTextEncoder is text_encoder.JinaTextEncoder
    assert search_facade.DEFAULT_MODEL == text_encoder.DEFAULT_MODEL
    assert search_facade.TASKS == text_encoder.TASKS
    assert search_facade.ChunkSearchEngine is search_engine.ChunkSearchEngine
