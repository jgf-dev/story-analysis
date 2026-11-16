import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from elasticsearch import Elasticsearch, helpers

from embedding.export_utils import (
    discard_staging_directory,
    make_staging_directory,
    publish_directory,
    require_environment,
)

INDEX_NAME = "story_text_plain_v2"
OUTPUT_DIR = Path("data/vectors")
NUM_SLICES = 8  # Match to ES shard count or local CPU cores
BATCH_DOCS = 150  # ~2,250 chunks per HTTP request (~25MB uncompressed JSON)
FLUSH_CHUNKS = 25_000  # ~100MB RAM buffer per worker before Parquet flush

SCHEMA = pa.schema([
    ("doc_id", pa.string()),
    ("record_id", pa.int64()),
    ("chunk_index", pa.int16()),
    # ("chunk_text", pa.string()),
    ("embedding", pa.list_(pa.float16(), 1024)),
])


def extract_slice(
    slice_id: int, es_url: str, es_api_key: str, output_dir: Path
) -> int:
    es = Elasticsearch(
        es_url,
        api_key=es_api_key,
        http_compress=True,  # Critical: cuts 20GB JSON transfer by ~75%
        request_timeout=120,
        max_retries=5,
        retry_on_timeout=True,
    )

    query = {
        "slice": {"id": slice_id, "max": NUM_SLICES},
        "_source": False,
        "fields": [
            "id",
            {"field": "content", "format": "embeddings"},
        ],
    }

    shard_path = output_dir / f"part16-{slice_id:02d}.parquet"
    buffer = []
    total_chunks = 0

    with pq.ParquetWriter(shard_path, SCHEMA, compression="zstd") as writer:
        for hit in helpers.scan(
            client=es,
            index=INDEX_NAME,
            query=query,
            size=BATCH_DOCS,
            scroll="10m",
            preserve_order=False,
        ):
            fields = hit.get("fields", {})
            rec_id = fields.get("id", [None])[0]
            doc_id = hit["_id"]

            for idx, emb in enumerate(fields.get("content", [])):
                if len(emb):
                    buffer.append({
                        "doc_id": doc_id,
                        "record_id": rec_id,
                        "chunk_index": idx,
                        "embedding": emb,
                    })

            if len(buffer) >= FLUSH_CHUNKS:
                writer.write_table(pa.Table.from_pylist(buffer, schema=SCHEMA))
                total_chunks += len(buffer)
                buffer.clear()

        if buffer:
            writer.write_table(pa.Table.from_pylist(buffer, schema=SCHEMA))
            total_chunks += len(buffer)
            buffer.clear()

    return total_chunks


def main() -> int:
    try:
        es_url, es_api_key = require_environment("ES_URL", "ES_API_KEY")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    staging_dir = make_staging_directory(OUTPUT_DIR)
    total_exported = 0
    try:
        with ProcessPoolExecutor(max_workers=NUM_SLICES) as executor:
            futures = {
                executor.submit(extract_slice, s, es_url, es_api_key, staging_dir): s
                for s in range(NUM_SLICES)
            }
            for future in as_completed(futures):
                slice_id = futures[future]
                count = future.result()
                total_exported += count
                print(f"Slice {slice_id:02d} complete: {count:,} chunks written.")
        publish_directory(staging_dir, OUTPUT_DIR)
    finally:
        discard_staging_directory(staging_dir)

    print(f"Export complete. Total chunks: {total_exported:,} in {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
