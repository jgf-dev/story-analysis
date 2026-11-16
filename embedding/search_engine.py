"""End-to-end chunk search engine combining a Faiss index and Jina encoder."""

from __future__ import annotations

from pathlib import Path

from embedding.data_loading import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_ENCODE_BATCH_SIZE,
    DEFAULT_SAMPLE_PATH,
)
from embedding.text_encoder import DEFAULT_MODEL, JinaTextEncoder
from embedding.vector_index import ChunkVectorIndex, SearchHit


class ChunkSearchEngine:
    """Plaintext query -> Jina query vector -> ranked Faiss chunk hits."""

    def __init__(self, index: ChunkVectorIndex, encoder: JinaTextEncoder) -> None:
        if index.dimension != encoder.dimension:
            raise ValueError(
                f"index dimension {index.dimension} does not match "
                f"encoder dimension {encoder.dimension}"
            )
        self.index = index
        self.encoder = encoder

    @classmethod
    def from_parquet(
        cls,
        parquet_dir: str | Path,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_vectors: int | None = None,
        encoder: JinaTextEncoder | None = None,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        task: str = "retrieval",
    ) -> ChunkSearchEngine:
        index = ChunkVectorIndex.from_parquet(
            parquet_dir, batch_size=batch_size, max_vectors=max_vectors
        )
        if encoder is None:
            encoder = JinaTextEncoder(
                model_name,
                device=device,
                task=task,
                dimension=index.dimension,
            )
        return cls(index, encoder)

    @classmethod
    def from_sample(
        cls,
        sample_path: str | Path = DEFAULT_SAMPLE_PATH,
        *,
        batch_size: int = DEFAULT_ENCODE_BATCH_SIZE,
        max_vectors: int | None = None,
        encoder: JinaTextEncoder | None = None,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        task: str = "retrieval",
        max_length: int | None = None,
    ) -> ChunkSearchEngine:
        """Build an index from a JSONL chunk sample by encoding its text."""
        if encoder is None:
            encoder = JinaTextEncoder(
                model_name,
                device=device,
                task=task,
                encode_batch_size=batch_size,
                max_length=max_length,
            )
        index = ChunkVectorIndex.from_sample(
            sample_path,
            encoder=encoder,
            batch_size=batch_size,
            max_vectors=max_vectors,
        )
        return cls(index, encoder)

    def search(self, query: str, top_k: int = 10) -> list[SearchHit]:
        return self.index.search(self.encoder.encode_query(query), top_k=top_k)
