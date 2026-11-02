"""
One-time, resumable reindex: story_text_v2 (base64+zlib full_text) -> story_text_plain (plaintext).

- Pages the source index with `search_after` on the numeric `id` field (no from/size cap).
- Decompresses each `full_text` with zlib (base64 -> zlib/deflate -> utf-8).
- Bulk-indexes into the destination with _id = source id (idempotent: re-runs overwrite, never duplicate).
- Writes a checkpoint (last processed id) after every batch. Re-run the same command to resume.

Requires: pip install elasticsearch
"""

import argparse
import base64
import json
import os
import sys
import zlib

from dotenv import load_dotenv

load_dotenv()

try:
    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import bulk
except ImportError:
    sys.exit("Missing dependency. Install it with:  pip install elasticsearch")

SOURCE_INDEX = "story_text_v2"
DEST_INDEX = "story_text_plain"
CHECKPOINT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reindex_checkpoint.json")


def log(msg):
    print(msg, flush=True)


def load_checkpoint():
    try:
        with open(CHECKPOINT_FILE) as f:
            return int(json.load(f).get("last_id", 0))
    except (FileNotFoundError, ValueError):
        return 0


def save_checkpoint(last_id):
    tmp = CHECKPOINT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"last_id": last_id}, f)
    os.replace(tmp, CHECKPOINT_FILE)  # atomic


def ensure_dest(es):
    if not es.indices.exists(index=DEST_INDEX):
        es.indices.create(
            index=DEST_INDEX,
            mappings={"properties": {"id": {"type": "long"}, "full_text_plain": {"type": "text"}}},
        )
        log(f"Created destination index '{DEST_INDEX}'.")


def fetch_batch(es, last_id, size):
    body = {
        "size": size,
        "track_total_hits": False,
        "sort": [{"id": "asc"}],
        "_source": ["id", "full_text"],
        "query": {"range": {"id": {"gt": last_id}}} if last_id else {"match_all": {}},
    }
    return es.search(index=SOURCE_INDEX, body=body)["hits"]["hits"]


def decode(value):
    return zlib.decompress(base64.b64decode(value)).decode("utf-8")


def main():
    p = argparse.ArgumentParser(description="Resumable reindex of base64+zlib full_text to plaintext.")
    p.add_argument("--host", default=os.getenv("ES_HOST"), required=False, help="Elasticsearch endpoint, e.g. https://<cluster>.es.io:443")
    p.add_argument("--api-key", default=os.getenv("ES_API_KEY"), required=False, help="Base64 API key (id:api_key, already base64-encoded)")
    p.add_argument("--batch-size", type=int, default=500, help="Docs per search/bulk batch (default 500)")
    p.add_argument("--max-docs", type=int, default=0, help="Stop after N docs this run (0 = no limit)")
    p.add_argument("--reset", action="store_true", help="Ignore checkpoint and start from the beginning")
    args = p.parse_args()

    es = Elasticsearch(args.host, api_key=args.api_key, request_timeout=120)
    info = es.info()
    log(f"Connected to Elasticsearch {info['version']['number']}")

    ensure_dest(es)

    start_id = 0 if args.reset else load_checkpoint()
    if start_id:
        log(f"Resuming after id {start_id} (checkpoint: {CHECKPOINT_FILE})")
    else:
        log("Starting from the beginning.")

    last_id = start_id
    processed = errors = 0

    while True:
        hits = fetch_batch(es, last_id, args.batch_size)
        if not hits:
            break

        actions = []
        for h in hits:
            src = h.get("_source", {})
            doc_id = src.get("id", h.get("_id"))
            raw = src.get("full_text")
            try:
                plain = decode(raw) if raw else ""
            except Exception as e:
                errors += 1
                log(f"  [warn] id={doc_id}: decode failed ({e}); storing empty text")
                plain = ""
            actions.append({"_index": DEST_INDEX, "_id": doc_id, "_source": {"id": doc_id, "full_text_plain": plain}})

        ok, bulk_errors = bulk(es, actions, raise_on_error=False, request_timeout=120)
        for item in bulk_errors:
            errors += 1
            log(f"  [warn] bulk item error: {item}")

        last_id = hits[-1]["_source"].get("id", hits[-1]["sort"][0])
        save_checkpoint(last_id)
        processed += len(hits)
        log(f"  batch ok={ok} | processed this run={processed} | last_id={last_id} | errors={errors}")

        if args.max_docs and processed >= args.max_docs:
            log(f"Reached --max-docs={args.max_docs}; stopping. Re-run to continue.")
            break

    log(f"Done. Processed {processed} docs this run, {errors} errors, last_id={last_id}.")
    log("Re-run the same command (without --reset) to resume; use --reset to start over.")


if __name__ == "__main__":
    main()
