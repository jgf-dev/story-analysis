"""Production dense-vector search over the exported story chunk embeddings.

``embedding/get_chuncks.py`` writes one Parquet shard per Elasticsearch slice
with the schema ``(id, chunk_index, start_offset, end_offset, chunk_text,
embedding: fixed_size_list<float32>[1024])``. This module is the query path for
those shards:

1. stream every shard through :func:`iter_embedding_batches` (a 1M-row export is
   ~4 GB of vectors, so loading it all at once is not an option);
2. add the L2-normalised vectors to a Faiss inner-product index, so search
   scores are cosine similarities;
3. encode plaintext queries with ``jinaai/jina-embeddings-v5-text-small``
   through its retrieval adapter and query prompt;
4. search the resulting query vector and return ranked story/chunk ids.

Run it with::

    python -m embedding.search "a first time story at summer camp" --top-k 10

The first run downloads the Jina model into the Hugging Face cache. Chunk text
is deliberately not copied into the index; resolve it from the Parquet shard or
Elasticsearch using ``(story_id, chunk_index)``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

EMBEDDING_DIM = 1024
DEFAULT_MODEL = "jinaai/jina-embeddings-v5-text-small"
DEFAULT_PARQUET_DIR = Path("data/chunks")
DEFAULT_BATCH_SIZE = 8192
REQUIRED_COLUMNS = ("id", "chunk_index", "embedding")
TASKS = ("retrieval", "text-matching", "clustering", "classification")
PROMPT_NAMES = ("query", "document")


class EmbeddingDataError(ValueError):
    """Raised when a Parquet shard does not match the chunk-embedding schema."""


@dataclass(frozen=True)
class EmbeddingBatch:
    """One record batch of chunk ids, chunk positions, and float32 vectors."""

    ids: np.ndarray
    chunk_indices: np.ndarray
    vectors: np.ndarray


@dataclass(frozen=True)
class SearchHit:
    """A chunk vector that matched a query, scored by cosine similarity."""

    story_id: int
    chunk_index: int
    score: float


def _parquet_shards(parquet_dir: str | Path) -> list[Path]:
    directory = Path(parquet_dir)
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
            if max_vectors is not None:
                remaining = max_vectors - index.size
                if remaining <= 0:
                    break
                if len(batch.ids) > remaining:
                    index.add(
                        batch.ids[:remaining],
                        batch.chunk_indices[:remaining],
                        batch.vectors[:remaining],
                    )
                    break
            index.add(batch.ids, batch.chunk_indices, batch.vectors)
            if max_vectors is not None and index.size >= max_vectors:
                break

        if index.size == 0:
            raise EmbeddingDataError(f"no embeddings found in {Path(parquet_dir)}")
        return index

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


class JinaQueryEncoder:
    """Encode plaintext queries with the Jina v5 retrieval adapter.

    ``AutoModel.from_pretrained`` downloads the model and its task adapters on
    first use and reuses the Hugging Face cache afterwards. The model's
    ``encode`` prepends the query prompt and L2-normalises its output, so query
    vectors live in the same cosine space as the indexed chunk vectors.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        device: str | None = None,
        task: str = "retrieval",
        prompt_name: str = "query",
        dimension: int = EMBEDDING_DIM,
    ) -> None:
        if task not in TASKS:
            raise ValueError(f"task must be one of {TASKS}, got {task!r}")
        if prompt_name not in PROMPT_NAMES:
            raise ValueError(
                f"prompt_name must be one of {PROMPT_NAMES}, got {prompt_name!r}"
            )
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.model_name = model_name
        self.device = device
        self.task = task
        self.prompt_name = prompt_name
        self.dimension = dimension
        self._model: Any | None = None

    def _load(self) -> Any:
        import torch
        from transformers import AutoModel

        device = torch.device(
            self.device
            if self.device is not None
            else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        if device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(
                f"requested device {str(device)!r}, but CUDA is not available"
            )
        dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
        model = AutoModel.from_pretrained(
            self.model_name, trust_remote_code=True, dtype=dtype
        )
        self._model = model.to(device).eval()
        self.device = str(device)
        return self._model

    def encode(self, query: str) -> np.ndarray:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")

        model = self._model if self._model is not None else self._load()
        embeddings = model.encode(
            texts=[query], task=self.task, prompt_name=self.prompt_name
        )
        if len(embeddings) != 1:
            raise RuntimeError(
                f"{self.model_name} returned {len(embeddings)} embeddings for one query"
            )
        vector = np.asarray(
            embeddings[0].detach().float().cpu().numpy(), dtype=np.float32
        ).reshape(-1)
        if vector.shape[0] != self.dimension:
            raise ValueError(
                f"{self.model_name} returned {vector.shape[0]} dimensions, "
                f"expected {self.dimension}"
            )
        return np.ascontiguousarray(vector)


class ChunkSearchEngine:
    """Plaintext query -> Jina query vector -> ranked Faiss chunk hits."""

    def __init__(self, index: ChunkVectorIndex, encoder: JinaQueryEncoder) -> None:
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
        encoder: JinaQueryEncoder | None = None,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        task: str = "retrieval",
        prompt_name: str = "query",
    ) -> ChunkSearchEngine:
        index = ChunkVectorIndex.from_parquet(
            parquet_dir, batch_size=batch_size, max_vectors=max_vectors
        )
        if encoder is None:
            encoder = JinaQueryEncoder(
                model_name,
                device=device,
                task=task,
                prompt_name=prompt_name,
                dimension=index.dimension,
            )
        return cls(index, encoder)

    def search(self, query: str, top_k: int = 10) -> list[SearchHit]:
        return self.index.search(self.encoder.encode(query), top_k=top_k)


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search story chunk embeddings with Faiss and Jina v5."
    )
    parser.add_argument("queries", nargs="+", help="plaintext query string(s)")
    parser.add_argument(
        "--parquet-dir",
        type=Path,
        default=DEFAULT_PARQUET_DIR,
        help=f"directory of get_chuncks.py shards (default: {DEFAULT_PARQUET_DIR})",
    )
    parser.add_argument("--top-k", type=_positive_int, default=10)
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=DEFAULT_BATCH_SIZE,
        help="Parquet rows read per batch while building the index",
    )
    parser.add_argument(
        "--max-vectors",
        type=_positive_int,
        default=None,
        help="index only the first N vectors (for smoke tests)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--device", default=None, help="torch device (default: auto: cuda, else cpu)"
    )
    parser.add_argument("--task", choices=TASKS, default="retrieval")
    parser.add_argument("--prompt-name", choices=PROMPT_NAMES, default="query")
    parser.add_argument(
        "--threads", type=_positive_int, default=None, help="Faiss CPU thread count"
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="print JSON results"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.threads is not None:
        faiss.omp_set_num_threads(args.threads)

    try:
        engine = ChunkSearchEngine.from_parquet(
            args.parquet_dir,
            batch_size=args.batch_size,
            max_vectors=args.max_vectors,
            model_name=args.model,
            device=args.device,
            task=args.task,
            prompt_name=args.prompt_name,
        )
    except (FileNotFoundError, EmbeddingDataError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Indexed {engine.index.size:,} chunk vectors from {args.parquet_dir}",
        file=sys.stderr,
    )
    results = [
        {
            "query": query,
            "hits": [asdict(hit) for hit in engine.search(query, top_k=args.top_k)],
        }
        for query in args.queries
    ]

    if args.as_json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            print(f"\n{result['query']}")
            for rank, hit in enumerate(result["hits"], start=1):
                print(
                    f"{rank:>3}. score={hit['score']:.4f} "
                    f"story={hit['story_id']} chunk={hit['chunk_index']}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
