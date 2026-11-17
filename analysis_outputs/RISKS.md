# Vector Search Risks and Follow-up Checks

These are source-grounded risks and validation gaps, not claims that a live search has failed. No full-corpus or model-inference run was performed.

## Confirmed discrepancy

### GPU-accelerated FAISS is claimed, but the search index is created as CPU `IndexFlatIP`

- **Evidence:** `embedding/vector_index.py` constructs `faiss.IndexFlatIP(dimension)` and adds vectors directly. The analyzed search path has no `index_cpu_to_gpu`, GPU resource setup, or other Faiss GPU conversion. `README.md` describes “GPU-accelerated vector search” / “FAISS Integration: GPU-accelerated vector search,” and `COMMENTS.md` describes GPU-accelerated FAISS indexes.
- **Impact:** Users may expect the index and ranking workload to use GPU acceleration, but this implementation keeps the Faiss index on the CPU. `--device` selects the Jina model device, not the Faiss index device.
- **Follow-up:** Align those claims with actual behavior, or add an explicit supported GPU index path and tests/benchmarks that demonstrate it. This review makes no performance claim about the installed Faiss build.

## Operational risks

### Every process builds a new full in-memory index

- **Evidence:** `ChunkVectorIndex` creates a fresh flat index and `from_parquet()` streams all selected shards into it. No persisted index load/save or reusable cache is present in the search path.
- **Impact:** Separate CLI invocations reread the export and rebuild the exact index. At the documented scale of about one million 1024-d float32 vectors, vectors alone occupy about 4 GB; the Jina model adds further memory (the docs estimate about 2.7 GB on CPU). Startup cost and memory requirements rise with corpus size.
- **Follow-up:** Measure build time and peak RSS on representative data; consider a versioned persisted index or a memory/capacity preflight if repeated interactive searches are expected.

### Vector compatibility relies on an external, undocumented-at-runtime identity contract

- **Evidence:** The reader checks structural shape, nulls, and finite values, while the search encoder selects a configurable model and task. The Parquet schema contains no model/task/version fingerprint, and no runtime check binds an export to the encoder configuration.
- **Impact:** If the producer's embedding model/task or Elasticsearch inference configuration changes independently of the query encoder, the code can still return ranked hits for incompatible vectors without a clear mismatch error. The docs state that the Jina v5 retrieval prompts match Elasticsearch defaults, but the schema does not enforce that assumption.
- **Follow-up:** Record producer model, task/prompt, and version metadata with each export and validate it at load time, or explicitly document and operationally control the required compatibility contract.

## Evaluation coverage gap

### Unit tests cover mechanics, not retrieval relevance or production scale

- **Evidence:** `tests/test_embedding_search.py` verifies cosine ranking using synthetic basis vectors, tests validation and prompt wiring with fake model objects, and checks the 200-row sample. It does not run a judged query set against production-like vectors or measure recall/latency/RSS.
- **Impact:** Passing tests support structural correctness and expected score math, but cannot establish that search results are useful, that exported vectors align with the chosen Jina model, or that a full build fits the deployment environment.
- **Follow-up:** Add a small versioned relevance set with expected story/chunk judgments, and a separate opt-in benchmark for representative build size, latency, device, and peak memory. Keep external corpus data out of the repository per `AGENTS.md`.

## Lower-priority interface note

`embedding/get_vectors.py` writes `data/vectors/` using a different schema and float16 embeddings; it is not a source for `embedding.search` (which expects `data/chunks/` with integer `id` and 1024-d fixed-size vectors). The distinction is stated in this report but the two exporters' names and output directories could still be confused. Treat this as a usability concern, not a confirmed defect, unless that alternate export is intended to feed this CLI.