# Comments

## 10/20/2026

[INGESTION_SPECIFICATION.md](docs/INGESTION_SPECIFICATION.md) 

4.2 Databricks PySpark Distributed Execution (`jgf-dev/story-analysis`)

> Databricks will not be used.

## 10/21/2026

Silent-failure hardening for `insights/corpus_prep.py` (see
[INSIGHT_PLATFORM.md](docs/INSIGHT_PLATFORM.md#failure-handling-and-exit-codes)).

A malformed regex in `pipeline/profiler.py` raised once per row, was absorbed by
`process_rows`, and the ingest finished reporting `processed: 0` with **exit
code 0**. Two things made it invisible: the per-row `except` in the worker, and
`$?` after a pipe reporting `tee`'s status rather than Python's.

Changes:

1. `main` exits 1 when any row failed (`--allow-errors` opts out).
2. The byte-offset checkpoint is no longer advanced past a failed batch, so
   failed rows are retried instead of skipped forever.
3. The final summary always prints the total and the count of distinct failure
   types, capped so a varying message cannot grow the report without limit.
4. `pipeline/profiler.py` registers its patterns in `REGEX_PATTERNS` and
   validates them at import; a test forbids `re.compile()` inside functions.
5. `scripts/ingest.sh` wraps the run with `set -o pipefail` and fails if a run
   exits 0 having processed no rows.
 
