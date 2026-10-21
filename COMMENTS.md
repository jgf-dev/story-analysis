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

### Status of the 8-finding corpus audit

Re-checked against the code and the current 100-row `data/output/` run.

| # | Finding | Status |
| - | - | - |
| 1 | `[3-22]` regex breaks the pipeline | **Fixed.** Now `(?:[3-9]\|[12]\d)\s?(?:in(?:ches)?\|cm\|centimeters)`, and the `[in\|cm\|...]` character-class bug is gone. Imports clean. |
| 2 | Safety false positives | **Open** — STO-1247 (Urgent). Still reproduces exactly: `"After fifteen minutes"`, `"his number was thirteen"`, `"the lamp only cost fourteen"` all still fail, as do the anon.penet.fi `abuse@` footer and `"his assault on the hard throbbing cock"`. |
| 3 | Duplication / repeat artifacts | **Open** — STO-1251. Moot on the current 100-row run (effective words 99.8%, ratio 1.0), but material at 5,000 rows where it doubled the audio-hours estimate. |
| 4 | Chunks written for safety failures | **Retracted — I was wrong.** The export *is* correctly gated: it iterates `tts_candidates`, which `filter_and_rank_candidates` restricts to `SafetyVerdict.PASS`. Verified on the fixture, which contains a real `FAIL_UNDERAGE_RISK` story: it produces no chunk file. The 109-file surplus was **stale files from an earlier run** left by the never-pruned directory. Fixed by pruning; see the changelog. |
| 5 | `duplicate_count` / `exact_hash` / canonical | **Open** — STO-1248. All 100 rows still carry `duplicate_count: 0` across 12 multi-member clusters, `exact_hash` is still the row id (0/100 are SHA-256), and canonical is still first-seen (11/12), not score-based as the spec requires. |
| 6 | `dialogue_percentage` > 100% | **Open** — STO-1249. The over-capture is reproducible via nested quotes (`["“][^"”]+["”]` permits `"` inside the match). |
| 7 | Quality calibration | **Open** — STO-1245. `structural_arc == 20` for 82/100; no row lands in Tier 4; `prose_richness` still floors at 6.0 (9 rows); 4 rows still carry the BBS-artifact formatting penalty; `Contemporary Romance` still ranks #2 as the fallback bucket. |
| 8 | Coverage gaps | **Partly addressed** — STO-1250. The stale `data/samples/` path is fixed. Still open: `parse/parse.py` is not wired into the pipeline, there is no test above fixture scale, and `data/stories_clean.csv` is a local-only symlink. |

Findings 2, 5, 6 and 7 are judgement calls about screening precision and the
quality rubric, not defects with one obvious fix — they change what the corpus
contains and what gets produced from it, so they are left for a deliberate
decision rather than changed unilaterally. All open findings are tracked in the
[**Nifty Corpus data analysis and NLP**](https://linear.app/jgfdev/project/nifty-corpus-data-analysis-and-nlp-fd2863838f42/overview)
project.

 
