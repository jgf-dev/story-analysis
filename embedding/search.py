"""Production dense-vector search over the exported story chunk embeddings.

``embedding/get_chuncks.py`` writes one Parquet shard per Elasticsearch slice
with the schema ``(id, chunk_index, start_offset, end_offset, chunk_text,
embedding: fixed_size_list<float32>[1024])``. This module is the CLI entrypoint
and re-export facade for that query path, backed by:

1. :mod:`embedding.data_loading` — stream every shard through
   :func:`iter_embedding_batches` (a 1M-row export is ~4 GB of vectors, so
   loading it all at once is not an option) or sample JSONL chunks through
   :func:`iter_sample_chunks`;
2. :mod:`embedding.vector_index` — add the L2-normalised vectors to a Faiss
   inner-product index (:class:`ChunkVectorIndex`), so search scores are cosine
   similarities;
3. :mod:`embedding.text_encoder` — encode plaintext queries and sample chunks
   with ``jinaai/jina-embeddings-v5-text-small`` (:class:`JinaTextEncoder`);
4. :mod:`embedding.search_engine` — combine index and encoder in
   :class:`ChunkSearchEngine` to return ranked story/chunk ids.

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
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import faiss

from embedding.data_loading import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_ENCODE_BATCH_SIZE,
    DEFAULT_PARQUET_DIR,
    DEFAULT_SAMPLE_PATH,
    EMBEDDING_DIM,
    REQUIRED_COLUMNS,
    SAMPLE_ID_COLUMN,
    SAMPLE_TEXT_COLUMN,
    ChunkTextBatch,
    EmbeddingBatch,
    EmbeddingDataError,
    _batch_vectors,  # noqa: F401
    _parquet_shards,  # noqa: F401
    iter_embedding_batches,
    iter_sample_chunks,
)
from embedding.search_engine import ChunkSearchEngine
from embedding.text_encoder import DEFAULT_MODEL, TASKS, JinaTextEncoder
from embedding.vector_index import ChunkVectorIndex, SearchHit

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_ENCODE_BATCH_SIZE",
    "DEFAULT_MODEL",
    "DEFAULT_PARQUET_DIR",
    "DEFAULT_SAMPLE_PATH",
    "EMBEDDING_DIM",
    "REQUIRED_COLUMNS",
    "SAMPLE_ID_COLUMN",
    "SAMPLE_TEXT_COLUMN",
    "TASKS",
    "ChunkSearchEngine",
    "ChunkTextBatch",
    "ChunkVectorIndex",
    "EmbeddingBatch",
    "EmbeddingDataError",
    "JinaTextEncoder",
    "SearchHit",
    "iter_embedding_batches",
    "iter_sample_chunks",
    "main",
]


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
