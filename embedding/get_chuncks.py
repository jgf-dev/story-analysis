import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import orjson
import pyarrow as pa
import pyarrow.parquet as pq
from elasticsearch import Elasticsearch, JsonSerializer, helpers

ES_URL = os.environ["ES_URL"]
ES_API_KEY = os.environ["ES_API_KEY"]
INDEX_NAME = "story_text_plain_v2"
OUTPUT_DIR = Path("data/chunks")

NUM_SLICES = 4  # 2 primary shards -> 4 slices
BATCH_DOCS = 150  # ~2,250 chunks per HTTP response
FLUSH_CHUNKS = 25_000  # ~115MB RAM buffer per worker before Parquet flush

SCHEMA = pa.schema([
    ("id", pa.int64()),
    ("chunk_index", pa.int16()),
    ("start_offset", pa.int32()),
    ("end_offset", pa.int32()),
    ("chunk_text", pa.string()),
    ("embedding", pa.list_(pa.float32(), 1024)),
])


class OrjsonSerializer(JsonSerializer):
    def loads(self, data: str | bytes) -> Any:
        return orjson.loads(data)


def extract_slice(slice_id: int) -> tuple[int, int]:
    es = Elasticsearch(
        ES_URL,
        api_key=ES_API_KEY,
        http_compress=True,
        serializer=OrjsonSerializer(),
        request_timeout=120,
        max_retries=5,
        retry_on_timeout=True,
    )

    query = {
        "slice": {"id": slice_id, "max": NUM_SLICES},
        "_source": {
            "exclude_vectors": False,
            "includes": ["_inference_fields"],
        },
        "fields": [
            {"field": "content", "format": "chunks"},
        ],
    }

    shard_path = OUTPUT_DIR / f"part-{slice_id:02d}.parquet"
    ids: list[int] = []
    chunk_indices: list[int] = []
    start_offsets: list[int] = []
    end_offsets: list[int] = []
    chunk_texts: list[str] = []
    embeddings: list[list[float]] = []

    total_docs = 0
    total_chunks = 0

    def flush(writer: pq.ParquetWriter) -> int:
        if not ids:
            return 0
        count = len(ids)
        flat_floats = pa.array(embeddings, type=pa.list_(pa.float32())).values
        table = pa.Table.from_arrays(
            [
                pa.array(ids, type=pa.int64()),
                pa.array(chunk_indices, type=pa.int16()),
                pa.array(start_offsets, type=pa.int32()),
                pa.array(end_offsets, type=pa.int32()),
                pa.array(chunk_texts, type=pa.string()),
                pa.FixedSizeListArray.from_arrays(flat_floats, 1024),
            ],
            schema=SCHEMA,
        )
        writer.write_table(table)
        ids.clear()
        chunk_indices.clear()
        start_offsets.clear()
        end_offsets.clear()
        chunk_texts.clear()
        embeddings.clear()
        return count

    with pq.ParquetWriter(shard_path, SCHEMA, compression="zstd") as writer:
        for hit in helpers.scan(
            client=es,
            index=INDEX_NAME,
            query=query,
            size=BATCH_DOCS,
            scroll="10m",
            preserve_order=False,
        ):
            doc_id = int(hit["_id"])
            texts: list[str] = hit.get("fields", {}).get("content", [])
            chunk_objs: list[dict[str, Any]] = (
                hit.get("_source", {}).get("_inference_fields", {}).get("content", {}).get("inference", {}).get("chunks", {}).get("content", [])
            )

            if len(texts) != len(chunk_objs):
                raise ValueError(f"Doc {doc_id} mismatch: {len(texts)} text chunks vs {len(chunk_objs)} vector objects")

            for idx, (text, obj) in enumerate(zip(texts, chunk_objs)):
                ids.append(doc_id)
                chunk_indices.append(idx)
                start_offsets.append(obj["start_offset"])
                end_offsets.append(obj["end_offset"])
                chunk_texts.append(text)
                embeddings.append(obj["embeddings"])

            total_docs += 1
            if len(ids) >= FLUSH_CHUNKS:
                total_chunks += flush(writer)

        total_chunks += flush(writer)

    return total_docs, total_chunks


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    grand_docs = 0
    grand_chunks = 0

    with ProcessPoolExecutor(max_workers=NUM_SLICES) as executor:
        futures = {executor.submit(extract_slice, s): s for s in range(NUM_SLICES)}
        for future in as_completed(futures):
            slice_id = futures[future]
            docs, chunks = future.result()
            grand_docs += docs
            grand_chunks += chunks
            print(f"Slice {slice_id:02d} complete: {docs:,} docs | {chunks:,} chunks")

    print(f"Export finished: {grand_docs:,} total docs, {grand_chunks:,} total chunks in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
