"""Faiss exact cosine-similarity vector index over story chunk embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from embedding.data_loading import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_ENCODE_BATCH_SIZE,
    DEFAULT_SAMPLE_PATH,
    EMBEDDING_DIM,
    EmbeddingDataError,
    iter_embedding_batches,
    iter_sample_chunks,
)
from embedding.text_encoder import JinaTextEncoder


@dataclass(frozen=True)
class SearchHit:
    """A chunk vector that matched a query, scored by cosine similarity."""

    story_id: int
    chunk_index: int
    score: float


class ChunkVectorIndex:
    """Exact cosine-similarity index over chunk embeddings.

    Vectors are L2-normalised before insertion and Faiss uses inner product, so
    ``IndexFlatIP`` scores are cosine similarities in ``[-1, 1]``. At ~1M
    vectors of 1024 float32 values the index is ~4 GB; the id metadata adds
    ~12 MB. Flat search is used because 1M vectors is small enough for exact
    search and avoids an index-training step.
    """

    def __init__(self, dimension: int = EMBEDDING_DIM) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension
        self.index = faiss.IndexFlatIP(dimension)
        self._ids: list[np.ndarray] = []
        self._chunk_indices: list[np.ndarray] = []
        self._ids_flat: np.ndarray | None = None
        self._chunk_indices_flat: np.ndarray | None = None

    @property
    def size(self) -> int:
        return int(self.index.ntotal)

    @classmethod
    def from_parquet(
        cls,
        parquet_dir: str | Path,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dimension: int = EMBEDDING_DIM,
        max_vectors: int | None = None,
    ) -> ChunkVectorIndex:
        """Build the index from all chunk embeddings under ``parquet_dir``.

        ``max_vectors`` limits how many rows are read, which is useful for a
        smoke test against the real export without waiting for all shards.
        """
        if max_vectors is not None and max_vectors <= 0:
            raise ValueError("max_vectors must be positive")

        index = cls(dimension)
        for batch in iter_embedding_batches(
            parquet_dir, batch_size=batch_size, dimension=dimension
        ):
            if index._add_batch(
                batch.ids, batch.chunk_indices, batch.vectors, max_vectors
            ):
                break

        if index.size == 0:
            raise EmbeddingDataError(f"no embeddings found in {Path(parquet_dir)}")
        return index

    @classmethod
    def from_sample(
        cls,
        sample_path: str | Path = DEFAULT_SAMPLE_PATH,
        *,
        encoder: JinaTextEncoder,
        batch_size: int = DEFAULT_ENCODE_BATCH_SIZE,
        max_vectors: int | None = None,
    ) -> ChunkVectorIndex:
        """Build the index from a JSONL chunk sample, encoding its text locally.

        The sample rows carry chunk text but no vectors, so every chunk is
        encoded with the model's document prompt. ``max_vectors`` limits how
        many chunks are read and encoded, which keeps smoke tests fast.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_vectors is not None and max_vectors <= 0:
            raise ValueError("max_vectors must be positive")

        index = cls(encoder.dimension)
        for batch in iter_sample_chunks(sample_path, batch_size=batch_size):
            if max_vectors is not None and index.size >= max_vectors:
                break
            count = len(batch.ids)
            if max_vectors is not None:
                count = min(count, max_vectors - index.size)
            vectors = encoder.encode_documents(batch.texts[:count])
            index.add(batch.ids[:count], batch.chunk_indices[:count], vectors)
            if max_vectors is not None and index.size >= max_vectors:
                break

        if index.size == 0:
            raise EmbeddingDataError(f"no chunks found in {Path(sample_path)}")
        return index

    def _add_batch(
        self,
        ids: np.ndarray,
        chunk_indices: np.ndarray,
        vectors: np.ndarray,
        max_vectors: int | None,
    ) -> bool:
        """Add one batch, honouring ``max_vectors``; return True at the limit."""
        if max_vectors is not None:
            remaining = max_vectors - self.size
            if remaining <= 0:
                return True
            if len(ids) > remaining:
                self.add(
                    ids[:remaining],
                    chunk_indices[:remaining],
                    vectors[:remaining],
                )
                return True
        self.add(ids, chunk_indices, vectors)
        return max_vectors is not None and self.size >= max_vectors

    def add(
        self, ids: np.ndarray, chunk_indices: np.ndarray, vectors: np.ndarray
    ) -> None:
        """Normalise and add one batch of vectors plus their source ids."""
        vectors = np.array(vectors, dtype=np.float32, order="C", copy=True)
        if vectors.ndim != 2 or vectors.shape[1] != self.dimension:
            raise ValueError(
                f"expected vectors with shape (n, {self.dimension}), "
                f"got {vectors.shape}"
            )
        if len(ids) != vectors.shape[0] or len(chunk_indices) != vectors.shape[0]:
            raise ValueError("ids, chunk_indices and vectors must have equal length")
        if not np.isfinite(vectors).all():
            raise EmbeddingDataError("embeddings contain NaN or infinite values")

        faiss.normalize_L2(vectors)
        self.index.add(vectors)
        self._ids.append(np.array(ids, dtype=np.int64, copy=True))
        self._chunk_indices.append(np.array(chunk_indices, dtype=np.int32, copy=True))
        self._ids_flat = None
        self._chunk_indices_flat = None

    def _metadata(self) -> tuple[np.ndarray, np.ndarray]:
        if self._ids_flat is None or self._chunk_indices_flat is None:
            self._ids_flat = (
                np.concatenate(self._ids) if self._ids else np.empty(0, dtype=np.int64)
            )
            self._chunk_indices_flat = (
                np.concatenate(self._chunk_indices)
                if self._chunk_indices
                else np.empty(0, dtype=np.int32)
            )
            if len(self._ids_flat) != self.size:
                raise RuntimeError("index metadata is out of sync with Faiss")
        return self._ids_flat, self._chunk_indices_flat

    def search(self, query_vector: np.ndarray, top_k: int = 10) -> list[SearchHit]:
        """Return the ``top_k`` most cosine-similar chunks for one query vector."""
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.size == 0:
            raise RuntimeError("cannot search an empty index")

        query = np.asarray(query_vector, dtype=np.float32)
        if query.ndim == 2 and query.shape[0] == 1:
            query = query[0]
        if query.ndim != 1:
            raise ValueError(f"expected a 1-D query vector, got shape {query.shape}")
        if query.shape[0] != self.dimension:
            raise ValueError(
                f"query vector has {query.shape[0]} dimensions, "
                f"expected {self.dimension}"
            )
        query = np.ascontiguousarray(query).reshape(1, -1)
        faiss.normalize_L2(query)

        scores, positions = self.index.search(query, min(top_k, self.size))
        ids, chunk_indices = self._metadata()
        hits: list[SearchHit] = []
        for score, position in zip(scores[0], positions[0]):
            if position < 0:
                continue
            hits.append(
                SearchHit(
                    story_id=int(ids[position]),
                    chunk_index=int(chunk_indices[position]),
                    score=float(score),
                )
            )
        return hits
