# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries are grouped by the change types defined in Keep a Changelog:
`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

## [Unreleased]

### Added

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
