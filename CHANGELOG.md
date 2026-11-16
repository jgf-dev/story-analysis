# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries are grouped by the change types defined in Keep a Changelog:
`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

## [Unreleased]

### Added

- **Declare the chunk-export serializer dependency.** `embedding/get_chuncks.py`
  imports `orjson` directly, so `pyproject.toml` now declares it instead of
  relying on an undeclared or transitive installation; a fresh project sync can
  run the exporter without manual package installation.
- **Production Faiss chunk search.** `embedding/search.py` streams the 1024-d
  embeddings written by `embedding/get_chuncks.py` from `data/chunks/*.parquet`
  into an exact cosine index (`faiss.IndexFlatIP` over L2-normalised vectors),
  encodes plaintext queries with `jinaai/jina-embeddings-v5-text-small` and its
  retrieval query prompt, and returns ranked `(story id, chunk index)` hits.
  Peak build memory is one Parquet batch plus the ~4 GB index, so the ~1M-row
  export is never loaded whole. `python -m embedding.search "..."` runs the
  query path, and `--max-vectors` builds a partial index for smoke tests. The
  model needs `torch`, `peft` and `pyarrow`, which are now declared in
  `pyproject.toml` so a fresh `uv sync` can run the query path. Covered by
  `tests/test_embedding_search.py`: shard streaming, schema and dimension
  failures, cosine ranking, `max_vectors`, encoder validation, and the CLI's
  missing-directory error. See `docs/INSIGHT_PLATFORM.md` for usage.
- **Sample chunk search.** `embedding/search.py` can now build the same Faiss
  index from `samples/faiss_embedding_chunks_sample.jsonl` (200 rows) through
  `iter_sample_chunks` and `ChunkVectorIndex.from_sample`. The sample carries
  chunk text but no vectors, so `JinaTextEncoder` encodes it locally with
  `task="retrieval"` and the model's `document` prompt — the defaults used by
  Elasticsearch's `semantic_text` field — while queries use the matching
  `query` prompt. `python -m embedding.search --sample ...` runs the path, with
  `--encode-batch-size` and `--max-length` to bound CPU smoke tests. Covered by
  new tests for the committed sample, malformed JSONL rows, document-prompt
  encoding, batching, and `max_vectors`; `docs/INSIGHT_PLATFORM.md`, `README.md`
  and `embedding/AGENTS.md` now describe the sample accurately.
- `README.md` — comprehensive project documentation with repository structure,
  setup instructions, usage examples, and development guidelines. Provides a
  single entry point for understanding the project.
- `README.md` — comprehensive project documentation with repository structure,
  setup instructions, usage examples, and development guidelines. Provides a
  single entry point for understanding the project.
- `scripts/measure_safety.py` — samples the corpus and reports the safety
  verdict distribution plus the false-positive classes, so the effect of a rule
  change is measurable rather than asserted. Supports `--limit` and `--json`.
- Implementation plan for STO-1247 (safety filter false positives) under
  `docs/plans/STO-1247/`: `plan.md` with 6 phases and 29 tasks, `baseline.md`
  with the pre-change measurements, and `checkpoints/spec-to-plan.yaml` +
  `checkpoints/plan-to-tasks.yaml` for requirement traceability (8/8
  requirements mapped). The plan is documentation only — no code changed.
- `scripts/ingest.sh` — wrapper for full-corpus ingestion runs. Sets
  `set -Eeuo pipefail`, tees output to a timestamped log under `data/logs/`,
  and captures `${PIPESTATUS[0]}` so the pipeline reports Python's exit status
  rather than `tee`'s. It additionally fails when a run exits 0 having processed
  no rows.
- `pipeline.profiler.REGEX_PATTERNS` and `validate_patterns()`, called at import
  time. Validates every cleaning and safety pattern, including rejecting an
  empty rule list (which would silently disable a whole safety gate) and a
  non-pattern entry.
- `insights.corpus_prep.error_signature()` — normalises an error message to a
  stable signature by replacing digits with `#`, so messages differing only by
  row id or character offset group into one reported cause.
- `insights.corpus_prep.FullCorpusIngester._record_error()` — tallies failures
  under a bounded set of signatures (`MAX_ERROR_SIGNATURES`, default 100), with
  overflow folded into a single bucket so a varying error message cannot grow
  the report or the stored state without limit.
- `--allow-errors` flag on `insights.corpus_prep`, to keep exit code 0 when rows
  failed (for exploratory runs).
- New result fields in `<db>.ingest_result.json`: `total_errors`,
  `blocked_batches`, `error_types`, and `unprocessed_ids` (capped at
  `FAILED_ID_SAMPLE`, default 100).
- `AGENTS.md` — repository instructions for AI coding agents, including the
  requirement to record every change in this file.
- Regression tests in `tests/test_insights.py` covering error exit codes,
  checkpoint blocking, retry of failed rows, bounded error signatures, the
  regex guard, and an AST check that forbids `re.compile()` inside functions.

### Changed

- **Publish only complete embedding exports.** `embedding/get_chuncks.py` and
  `embedding/get_vectors.py` now write all slices into a staging directory and
  publish it only after every slice succeeds, preserving the previous complete
  export after a failed run; if interrupted during promotion, the previous
  export is restored on the next search or export. Staging remains private and
  writable until publication, then preserves the prior directory permissions or
  applies the normal directory mode under the current umask on a first export.
  Missing `ES_URL` or
  `ES_API_KEY` now produces a concise CLI error. `README.md` and
  `docs/INSIGHT_PLATFORM.md` document the required settings and publication
  behavior.
- **Split `embedding/search.py` into focused modules.** Extracted data
  streaming (`embedding/data_loading.py`), the Faiss cosine index
  (`embedding/vector_index.py`), the Jina v5 text encoder
  (`embedding/text_encoder.py`), and the search engine
  (`embedding/search_engine.py`) out of `embedding/search.py`.
  `embedding/search.py` remains the CLI entrypoint (`python -m embedding.search`)
  and re-export facade for backwards compatibility. Updated
  `tests/test_embedding_search.py`, `docs/INSIGHT_PLATFORM.md`, and
  `README.md` to match.
- `AGENTS.md` — updated repository layout to include new `embedding/`, `samples/`,
  and `big-query/` directories. Updated conventions to reflect Python 3.14+
  requirement and added notes about FAISS indexes and vector data storage.
- `COMMENTS.md` — added repository state update documenting the new embedding
  and vector search capabilities, including `embedding/` directory contents,
  sample data, BigQuery notebooks, and updated project configuration.
- `pipeline.cli.main()` now accepts an optional `argv: list[str] | None = None`
  parameter so the CLI entry point can be tested or invoked programmatically
  without modifying `sys.argv`.
- `pipeline.cli.export_tts_chunks(output_dir, tts_candidates)` — extracted as a
  dedicated helper from `main()` to handle exporting pre-segmented SSML audio
  chunks for top TTS candidates and pruning stale outputs from previous runs.
- **Safety verdicts are now three-tier.** `abuse`, `rape`, `murder`, `assault`
  and `suicide` moved out of `EXTREME_VIOLENCE_INDICATORS` into a new
  `MANUAL_REVIEW_INDICATORS` list, producing `FLAGGED_MANUAL_REVIEW` instead of
  `FAIL_EXTREME_VIOLENCE`. The verdict was already defined in
  `pipeline/schemas.py` but never produced. It is quarantined from every
  inspiration-facing view exactly like a FAIL, but distinguishable so a reviewer
  can triage ambiguous language rather than treat it as prohibited content.
  `FAIL_EXTREME_VIOLENCE` now covers only necrophilia, snuff, bestiality and
  zoophilia.
- **Measured effect on a 5,000-row corpus sample**: PASS rate **56.9% → 59.1%**;
  bare-numeral false positives **455 → 0**; `abuse`-only violence verdicts
  **109 → 0**; `FAIL_EXTREME_VIOLENCE` **350 → 9**. The remaining
  `FAIL_UNDERAGE_RISK` verdicts are genuine: tag-driven (574), real age phrases
  (437), age-verb constructions (403), and the retained fail-closed school-level
  and `boyhood` rules (264).
- Documentation: `docs/INSIGHT_PLATFORM.md` gained a *Safety screening* section
  describing the three verdicts and the context requirements.
- `insights.corpus_prep.main()` now exits **1** when
  `errors + write_errors + dedup_errors` is non-zero, after printing a summary.
  Previously a run in which every row failed exited 0.
- The final ingest summary always prints the total failure count and the number
  of **distinct** failure types. The inline per-row print remains capped at 20
  for volume.
- `meta.ingest_state` now also stores `error_types` for post-mortem inspection.
  These counters are per-run and are not read back, so a failed run's report is
  never mixed into the next run's.
- Documentation: `docs/INSIGHT_PLATFORM.md` gained *Failure handling and exit
  codes*, *Running it in a pipeline*, and *Regex configuration* sections.
- The corpus-audit findings in `COMMENTS.md` now carry their Linear issue
  references. Open findings are tracked in the *Nifty Corpus data analysis and
  NLP* project as STO-1245 (quality rubric), STO-1247 (safety false positives),
  STO-1248 (dedup metadata), STO-1249 (dialogue regex), STO-1250 (parse module
  and corpus-scale coverage) and STO-1251 (repeat artifacts).

### Fixed

- **Safety filter false positives quarantined 43% of the corpus.** Three
  independent defects in `pipeline/profiler.py` caused it, all now fixed:
  - The bare-numeral rule matched the words `thirteen|fourteen|fifteen` with no
    age context, failing clock times, prices, jersey numbers and durations —
    **455 false positives** in a 5,000-row sample. Replaced with an age-verb
    construction (`was fifteen`, `turned fourteen`) that excludes a following
    unit of time or measure. Removing the rule outright was not sufficient: it
    let **288 rows** containing genuine age assertions pass, so the age-verb
    rule replaces it rather than simply deleting the alternatives.
  - The `anon.penet.fi` remailer footer embeds the string `abuse@`, which
    matched the bare `abuse` alternative in the violence list and quarantined
    **109 of 350** violence verdicts. New `ANONYMISER_BOILERPLATE` patterns
    strip these footers in `clean_text` before screening.
  - Tag matching was substring-based, so `"youthful"` matched the `"youth"`
    keyword and failed an unrelated story. Now word-boundary based.
- **Silent ingest failures.** A malformed regex in `pipeline/profiler.py` raised
  once per row, was absorbed by `process_rows`, and the ingest finished
  reporting `processed: 0` with **exit code 0**. Two things made it invisible:
  the per-row `except` in the worker, and `$?` after a pipe reporting `tee`'s
  status rather than Python's. The run now fails loudly and names the cause.
- **Checkpoint advanced past failed rows.** `last_offset` is only ever seeked
  to, never replayed, so advancing it past a row that raised skipped that row
  permanently. The checkpoint is now held for the whole run once any batch has
  failed — including against a *later* successful batch, which would otherwise
  have advanced past the earlier failure. Failed rows are retried on the next
  run; rows that did commit are skipped cheaply via `_seen_ids`.
- Removed a leftover module-scope debug statement
  `print(EXPLICIT_PATTERN.groups)` in `pipeline/profiler.py` that executed on
  every import.
- `.gitignore` now covers `data/logs/` and `.pytest_cache/`. The new
  `scripts/ingest.sh` writes its run logs to `data/logs/`, which was not
  ignored and would have been committed.
- **Stale TTS chunk files accumulated across runs.** `pipeline/cli.py` wrote
  `tts_chunks/<id>_chunks.json` with `mkdir(exist_ok=True)` and never pruned, so
  a run over a different input left the previous run's chunks in place. The
  directory then no longer matched the candidate queue it represents — a
  directory of 1,414 files sat alongside a 1,302-entry queue, and the surplus
  was indistinguishable from current output. The export now deletes any
  `*_chunks.json` not belonging to the current candidate set before writing.
- **Broken fixture path after `data/samples/` moved to `samples/`.** The move
  left three stale references, one of which failed
  `tests/test_pipeline.py::TestTTSPrioritizer::test_filter_and_rank` with
  `FileNotFoundError`. Updated `tests/test_pipeline.py`, the `--input` default
  in `pipeline/cli.py`, and the example in `docs/INGESTION_SPECIFICATION.md`.

### Security

- The regex guard closes a class of failure in which a broken safety pattern
  would silently disable screening while the run reported success. An empty
  `UNDERAGE_INDICATORS` or `EXTREME_VIOLENCE_INDICATORS` list now raises at
  import instead of matching nothing.

## History

Backfilled from the commit log; entries predate the introduction of this file.

### 2026-10-21

- `refactor(parse)`: simplify client creation parameters. (`7c3e5ea`)
- `feat(insights)`: add parsing module, update embeddings and profiler, remove
  Databricks config, add new story and comments. (`1294b1c`)
- Add type stubs under `types/`. (`5626685`)

### 2026-10-09

- `feat(insights)`: strip site chrome before embedding to decontaminate
  clusters. (`f4b5aab`)
- `perf(insights)`: parallelize batch processing across workers; fix resume
  offset skip. (`f7995d1`)
- `feat(insights)`: internal UI, local TTS audition, tests, and platform docs;
  fix MinHash overflow bias. (`f2bc456`)
- `feat(insights)`: analysis, semantic search, NER combo engine; cap
  header/tag/density regex scans for full-corpus streaming. (`b40d2cc`)

### 2026-10-08

- `feat(insights)`: streaming full-corpus ingester with banded MinHash LSH dedup
  and checkpointed SQLite catalog. (`f06866b`)
- `feat(pipeline)`: implement 300K story ingestion, quality audit, and TTS
  prioritization pipeline. (`43a7205`)

### 2026-09-02

- `feat`: initialize project with Databricks bundle configuration and narrative
  story content. (`ff08e9c`)

[Unreleased]: https://github.com/jgf-dev/story-analysis/commits/main
