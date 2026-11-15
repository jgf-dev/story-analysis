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

``samples/faiss_embedding_chunks_sample.jsonl`` is a 200-chunk export that has
chunk text but no vectors. ``--sample`` reads it through
:func:`iter_sample_chunks` and encodes each chunk with the model's ``document``
prompt, which matches the ``semantic_text`` field defaults used to build the
live Elasticsearch index, before searching it the same way.

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
DEFAULT_SAMPLE_PATH = Path("samples/faiss_embedding_chunks_sample.jsonl")
DEFAULT_BATCH_SIZE = 8192
DEFAULT_ENCODE_BATCH_SIZE = 4
REQUIRED_COLUMNS = ("id", "chunk_index", "embedding")
SAMPLE_ID_COLUMN = "id"
SAMPLE_TEXT_COLUMN = "content"
TASKS = ("retrieval", "text-matching", "clustering", "classification")


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


class JinaTextEncoder:
    """Encode queries and documents with the Jina v5 retrieval adapter.

    ``AutoModel.from_pretrained`` downloads the model and its task adapters on
    first use and reuses the Hugging Face cache afterwards. Documents are
    encoded with the model's ``document`` prompt and queries with its ``query``
    prompt, which is how Elasticsearch's ``semantic_text`` field uses the model
    by default. The model L2-normalises its output, so both live in the same
    cosine space as the indexed chunk vectors.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        device: str | None = None,
        task: str = "retrieval",
        dimension: int = EMBEDDING_DIM,
        encode_batch_size: int = DEFAULT_ENCODE_BATCH_SIZE,
        max_length: int | None = None,
    ) -> None:
        if task not in TASKS:
            raise ValueError(f"task must be one of {TASKS}, got {task!r}")
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if encode_batch_size <= 0:
            raise ValueError("encode_batch_size must be positive")
        if max_length is not None and max_length <= 0:
            raise ValueError("max_length must be positive")
        self.model_name = model_name
        self.device = device
        self.task = task
        self.dimension = dimension
        self.encode_batch_size = encode_batch_size
        self.max_length = max_length
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

    def encode_query(self, query: str) -> np.ndarray:
        """Encode one plaintext query with the retrieval ``query`` prompt."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        return self._encode([query], prompt_name="query")[0]

    def encode_documents(self, documents: Sequence[str]) -> np.ndarray:
        """Encode chunk text with the retrieval ``document`` prompt."""
        texts = list(documents)
        if not texts:
            raise ValueError("documents must not be empty")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("documents must be non-empty strings")

        batches = [
            self._encode(
                texts[start : start + self.encode_batch_size],
                prompt_name="document",
            )
            for start in range(0, len(texts), self.encode_batch_size)
        ]
        return np.vstack(batches)

    def _encode(self, texts: list[str], *, prompt_name: str) -> np.ndarray:
        model = self._model if self._model is not None else self._load()
        kwargs: dict[str, Any] = {
            "texts": texts,
            "task": self.task,
            "prompt_name": prompt_name,
        }
        if self.max_length is not None:
            kwargs["max_length"] = self.max_length
        embeddings = model.encode(**kwargs)
        array = np.asarray(embeddings.detach().float().cpu().numpy(), dtype=np.float32)
        if array.ndim != 2 or array.shape[0] != len(texts):
            raise RuntimeError(
                f"{self.model_name} returned {array.shape} for {len(texts)} texts"
            )
        if array.shape[1] != self.dimension:
            raise ValueError(
                f"{self.model_name} returned {array.shape[1]} dimensions, "
                f"expected {self.dimension}"
            )
        return np.ascontiguousarray(array)


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
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--parquet-dir",
        type=Path,
        default=DEFAULT_PARQUET_DIR,
        help=f"directory of get_chuncks.py shards (default: {DEFAULT_PARQUET_DIR})",
    )
    source.add_argument(
        "--sample",
        action="store_true",
        help=(
            f"build from {DEFAULT_SAMPLE_PATH} and encode its chunk text "
            "locally with the document prompt"
        ),
    )
    parser.add_argument("--top-k", type=_positive_int, default=10)
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=DEFAULT_BATCH_SIZE,
        help="Parquet rows read per batch while building the index",
    )
    parser.add_argument(
        "--encode-batch-size",
        type=_positive_int,
        default=DEFAULT_ENCODE_BATCH_SIZE,
        help="sample chunks encoded per model call",
    )
    parser.add_argument(
        "--max-length",
        type=_positive_int,
        default=None,
        help="token limit for local sample encoding (default: model maximum)",
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
        if args.sample:
            engine = ChunkSearchEngine.from_sample(
                batch_size=args.encode_batch_size,
                max_vectors=args.max_vectors,
                model_name=args.model,
                device=args.device,
                task=args.task,
                max_length=args.max_length,
            )
            source_name = DEFAULT_SAMPLE_PATH
        else:
            engine = ChunkSearchEngine.from_parquet(
                args.parquet_dir,
                batch_size=args.batch_size,
                max_vectors=args.max_vectors,
                model_name=args.model,
                device=args.device,
                task=args.task,
            )
            source_name = args.parquet_dir
    except (FileNotFoundError, EmbeddingDataError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Indexed {engine.index.size:,} chunk vectors from {source_name}",
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
