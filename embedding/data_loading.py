"""Streaming readers for exported Parquet chunk shards and JSONL chunk samples.

``embedding/get_chuncks.py`` writes one Parquet shard per Elasticsearch slice
with the schema ``(id, chunk_index, start_offset, end_offset, chunk_text,
embedding: fixed_size_list<float32>[1024])``. :func:`iter_embedding_batches`
streams those shards in record batches so a ~1M-row export (~4 GB of vectors)
never needs to be loaded into memory all at once.

``samples/faiss_embedding_chunks_sample.jsonl`` is a 200-chunk export that has
chunk text but no vectors. :func:`iter_sample_chunks` streams it in batches so
it can be encoded locally before indexing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from embedding.export_utils import recover_published_directory

EMBEDDING_DIM = 1024
DEFAULT_PARQUET_DIR = Path("data/chunks")
DEFAULT_SAMPLE_PATH = Path("samples/faiss_embedding_chunks_sample.jsonl")
DEFAULT_BATCH_SIZE = 8192
DEFAULT_ENCODE_BATCH_SIZE = 4
REQUIRED_COLUMNS = ("id", "chunk_index", "embedding")
SAMPLE_ID_COLUMN = "id"
SAMPLE_TEXT_COLUMN = "content"


class EmbeddingDataError(ValueError):
    """Raised when a Parquet shard or JSONL sample does not match its schema."""


@dataclass(frozen=True)
class EmbeddingBatch:
    """One record batch of chunk ids, chunk positions, and float32 vectors."""

    ids: np.ndarray
    chunk_indices: np.ndarray
    vectors: np.ndarray


@dataclass(frozen=True)
class ChunkTextBatch:
    """One batch of story ids, chunk positions, and raw chunk text."""

    ids: np.ndarray
    chunk_indices: np.ndarray
    texts: list[str]


def _parquet_shards(parquet_dir: str | Path) -> list[Path]:
    directory = Path(parquet_dir)
    recover_published_directory(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"embedding directory does not exist: {directory}")
    shards = sorted(directory.glob("*.parquet"))
    if not shards:
        raise FileNotFoundError(f"no Parquet shards found in {directory}")
    return shards


def _batch_vectors(column: pa.Array, path: Path, dimension: int) -> np.ndarray:
    if not pa.types.is_fixed_size_list(column.type):
        raise EmbeddingDataError(
            f"{path}: 'embedding' must be a fixed_size_list, got {column.type}"
        )
    if column.type.list_size != dimension:
        raise EmbeddingDataError(
            f"{path}: 'embedding' has list size {column.type.list_size}, "
            f"expected {dimension}"
        )
    if column.null_count:
        raise EmbeddingDataError(
            f"{path}: 'embedding' contains {column.null_count} null rows"
        )

    values = column.flatten()
    if values.null_count:
        raise EmbeddingDataError(
            f"{path}: 'embedding' contains {values.null_count} null values"
        )
    array = values.to_numpy(zero_copy_only=False)
    return np.asarray(array, dtype=np.float32).reshape(-1, dimension)


def iter_embedding_batches(
    parquet_dir: str | Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dimension: int = EMBEDDING_DIM,
) -> Iterator[EmbeddingBatch]:
    """Stream the chunk embeddings from every shard in ``parquet_dir``.

    Shards are read in sorted filename order and yielded in record batches, so
    peak memory is one batch (~32 MB at the default size) rather than the full
    ~4 GB export.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if dimension <= 0:
        raise ValueError("dimension must be positive")

    for path in _parquet_shards(parquet_dir):
        parquet = pq.ParquetFile(path)
        missing = [
            name for name in REQUIRED_COLUMNS if name not in parquet.schema_arrow.names
        ]
        if missing:
            raise EmbeddingDataError(
                f"{path}: missing required column(s): {', '.join(missing)}"
            )

        for record_batch in parquet.iter_batches(
            batch_size=batch_size, columns=list(REQUIRED_COLUMNS)
        ):
            ids = np.asarray(
                record_batch.column(0).to_numpy(zero_copy_only=False), dtype=np.int64
            )
            chunk_indices = np.asarray(
                record_batch.column(1).to_numpy(zero_copy_only=False), dtype=np.int32
            )
            vectors = _batch_vectors(record_batch.column(2), path, dimension)
            if not (len(ids) == len(chunk_indices) == vectors.shape[0]):
                raise EmbeddingDataError(
                    f"{path}: id, chunk_index and embedding row counts differ"
                )
            yield EmbeddingBatch(ids=ids, chunk_indices=chunk_indices, vectors=vectors)


def iter_sample_chunks(
    path: str | Path = DEFAULT_SAMPLE_PATH,
    *,
    batch_size: int = DEFAULT_ENCODE_BATCH_SIZE,
) -> Iterator[ChunkTextBatch]:
    """Stream story chunks from a JSONL export such as the committed sample.

    Each line is one Elasticsearch hit: ``id`` is the story id and ``content``
    is the chunk text. The sample has one row per story, but a repeated id is
    numbered in file order so ``(id, chunk_index)`` stays unique.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    sample = Path(path)
    if not sample.is_file():
        raise FileNotFoundError(f"sample file does not exist: {sample}")

    ids: list[int] = []
    chunk_indices: list[int] = []
    texts: list[str] = []
    next_index: dict[int, int] = {}

    with sample.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EmbeddingDataError(
                    f"{sample}:{line_number}: invalid JSON: {exc.msg}"
                ) from exc
            if not isinstance(row, dict):
                raise EmbeddingDataError(
                    f"{sample}:{line_number}: expected a JSON object"
                )

            story_id = row.get(SAMPLE_ID_COLUMN)
            text = row.get(SAMPLE_TEXT_COLUMN)
            if not isinstance(story_id, int) or isinstance(story_id, bool):
                raise EmbeddingDataError(
                    f"{sample}:{line_number}: '{SAMPLE_ID_COLUMN}' must be an integer"
                )
            if not isinstance(text, str) or not text.strip():
                raise EmbeddingDataError(
                    f"{sample}:{line_number}: '{SAMPLE_TEXT_COLUMN}' must be a "
                    "non-empty string"
                )

            chunk_index = next_index.get(story_id, 0)
            next_index[story_id] = chunk_index + 1
            ids.append(story_id)
            chunk_indices.append(chunk_index)
            texts.append(text)

            if len(ids) >= batch_size:
                yield ChunkTextBatch(
                    ids=np.asarray(ids, dtype=np.int64),
                    chunk_indices=np.asarray(chunk_indices, dtype=np.int32),
                    texts=texts,
                )
                ids, chunk_indices, texts = [], [], []

    if ids:
        yield ChunkTextBatch(
            ids=np.asarray(ids, dtype=np.int64),
            chunk_indices=np.asarray(chunk_indices, dtype=np.int32),
            texts=texts,
        )
