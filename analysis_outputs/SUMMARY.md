# Vector Search Project Analysis

**Scope:** `embedding/` vector-search subsystem, including the production Parquet path and the local JSONL sample path. This is a static architecture review; no model download, Elasticsearch query, full-corpus index build, or retrieval-quality experiment was run.

## Executive summary

`embedding/` provides inference-time dense chunk retrieval, not model training. It either reads precomputed 1024-dimensional vectors from the Elasticsearch export at `data/chunks/` or encodes the committed sample locally with Jina v5. It L2-normalizes vectors and uses Faiss `IndexFlatIP` for exact cosine ranking, returning `(story_id, chunk_index, score)` tuples. The flow is modular and has focused tests for data loading, validation, normalization/ranking, sample encoding, and CLI errors.

## Architecture and data flow

1. **Production export:** `embedding/get_chuncks.py` scans index `story_text_plain_v2` in four Elasticsearch slices and writes one Parquet shard per slice under `data/chunks/`. Its schema is `id`, `chunk_index`, offsets, text, and fixed-size 1024-d float32 embeddings. `embedding/export_utils.py` stages a generation, then publishes it as a directory replacement; a prior export is recoverable after interrupted promotion. The exporter requires `ES_URL` and `ES_API_KEY`.
2. **Alternative export:** `embedding/get_vectors.py` writes a distinct representation under `data/vectors/` (`doc_id`, `record_id`, `chunk_index`, float16 embeddings). That schema is not accepted by the production search reader, whose required columns are `id`, `chunk_index`, and `embedding`.
3. **Read/index:** `embedding/data_loading.py` streams sorted Parquet shards in batches, validates required columns, fixed-list dimension, and null embeddings, and yields IDs, chunk positions, and float32 vectors. `embedding/vector_index.py` adds normalized vectors to a newly created Faiss `IndexFlatIP` and keeps matching ID metadata in memory.
4. **Query/inference:** `embedding/search.py` is the CLI and compatibility re-export facade. `embedding/search_engine.py` encodes queries and invokes the index. `embedding/text_encoder.py` lazily loads `jinaai/jina-embeddings-v5-text-small` using the retrieval task and query prompt. Device selection applies to the model; no Faiss GPU index conversion appears in the path.
5. **Sample mode:** `--sample` reads `samples/faiss_embedding_chunks_sample.jsonl`, which has text but no vectors, and encodes chunks with the document prompt before indexing. The sample path shares the query encoder and Faiss ranker.

## Entry points and configuration

- Export chunks: `python -m embedding.get_chuncks` (Elasticsearch credentials required).
- Search the production export: `python -m embedding.search "..."`; default source is `data/chunks/`.
- Search the local sample: `python -m embedding.search --sample "..."`.
- CLI controls include `--top-k`, Parquet/sample batch sizes, `--max-vectors`, `--max-length`, `--model`, `--device`, `--task`, `--threads`, and JSON output.
- Runtime dependencies declared in `pyproject.toml` include Faiss, NumPy, PyArrow, PyTorch, Transformers, and PEFT. Model download/cache and memory are runtime concerns; the sample/production search path does not require Elasticsearch at query time.

## Testing evidence

`tests/test_embedding_search.py` uses small generated Parquet shards, fake encoders/models, and the committed JSONL sample. It exercises shard streaming, schema/dimension/null/non-finite validation, exact cosine ordering, top-k and `max_vectors`, repeated sample IDs, prompt selection, encoder shape/options, and the missing-directory CLI path. These tests validate local mechanics but do not establish semantic retrieval quality, index-build throughput, GPU execution, or full-corpus memory behavior.

## Boundaries and insertion points

There is no training entrypoint or locally fine-tuned model lifecycle in the analyzed package. For changing how stored vectors are read or indexed, the likely seam is `embedding/data_loading.py` / `embedding/vector_index.py`; for query and document encoding, `embedding/text_encoder.py`; for CLI/API orchestration, `embedding/search_engine.py` and `embedding/search.py`. Changes to the upstream embedding model or task must remain aligned with the vectors produced by the Elasticsearch export.

## Analysis limitations

The skill's referenced `references/analysis-policy.md`, shared `agent-operating-principles.md`, and `research-pitfall-checklist.md` were not present in the installed skill directories. Assessment therefore uses the active skill instructions, repository guidance, source, tests, and docs. No live export, model inference, or relevance benchmark was performed.