# AGENTS.md

Instructions for AI coding agents working in this repository.

## Changelog is mandatory

**Every change you make must be recorded in [`CHANGELOG.md`](CHANGELOG.md).**

This is not optional and not a follow-up task. A change is not complete until
its changelog entry exists. Do this in the same session as the code change, not
in a later one.

### How to write the entry

1. Add your entry under the `## [Unreleased]` heading.
2. Put it under the correct Keep a Changelog type, creating the subsection if it
   is not already present:
   - `### Added` — new features, files, flags, fields, tests.
   - `### Changed` — changes in existing behaviour.
   - `### Fixed` — bug fixes.
   - `### Removed` — removed features or files.
   - `### Deprecated` — soon-to-be-removed functionality.
   - `### Security` — vulnerabilities or safety-relevant fixes.
3. Write for a reader who was not in the session. State **what changed and why
   it matters**, not which files you touched. A reader should be able to tell
   whether the change affects them.
4. Reference the affected module or path inline (for example
   `insights/corpus_prep.py`) so the entry is searchable.
5. If the change alters documented behaviour, update the relevant doc under
   `docs/` in the same session and mention it in the entry.

### Rules

- **Never** delete or rewrite existing entries. The changelog is append-only
  history. If a change supersedes an earlier one, add a new entry that says so.
- **Never** move an entry out of `[Unreleased]` unless you are cutting a
  release. Release promotion is a separate, deliberate act.
- Do not invent a version number. `pyproject.toml` currently pins
  `version = "0.0.0"`; leave versioning to the maintainer.
- Keep entries factual. Do not claim a fix works unless you verified it — see
  *Verification* below.
- One entry per logical change, not one per file edited.

### Example

```markdown
### Fixed

- **Silent ingest failures.** A malformed regex in `pipeline/profiler.py` raised
  once per row, was absorbed by `process_rows`, and the ingest finished
  reporting `processed: 0` with exit code 0. The run now fails loudly and names
  the cause.
```

## Verification

Before reporting a change as complete:

- Run the test suite: `python -m pytest tests/ -q`.
- Run the linter on the files you changed:
  `python -m ruff check <files>`.
- If you fixed a bug, reproduce the original symptom first, then confirm it is
  gone. A fix you did not reproduce is a guess.
- If you added a guard or invariant, add a test that fails without it. Verify
  the test actually fails by temporarily reverting the guard.

## Repository layout

| Path | Purpose |
| --- | --- |
| `pipeline/` | Per-story processing: cleaning, safety audit, metrics, quality scoring, taxonomy, dedup, TTS preparation. |
| `insights/` | Full-corpus platform: streaming ingestion, analysis, semantic search, NER, internal UI. |
| `parse/` | Document parsing via the `unstructured-transform-client` API. |
| `tests/` | Test suite (`pytest`). |
| `docs/` | Specifications and platform documentation. |
| `scripts/` | Operational wrapper scripts. |
| `types/` | Type stubs mirroring the source tree. |

## Conventions

- Python 3.12, `from __future__ import annotations` at the top of modules.
- Prefer PEP 585/604 annotations (`list[str]`, `int | None`) in new code.
- **Compile regexes at module scope.** A malformed pattern then fails at import.
  Compiled inside a function, the error is raised per row, absorbed by the
  worker's `except`, and the run reports success having processed nothing.
  `tests/test_insights.py` enforces this with an AST check.
- Long-running batch jobs must fail loudly. Never let a run exit 0 when work was
  skipped — see `insights/corpus_prep.py` for the pattern (non-zero exit,
  checkpoint held, distinct failure types reported).
- Do not commit dataset artifacts. `data/output/`, `data/raw/`, and `*.sqlite*`
  are gitignored; the corpus is internal and must not leave the machine.

## Notes

- `COMMENTS.md` holds dated, free-form notes from the maintainer. Read it for
  context on decisions; it is not a substitute for the changelog.
- `docs/INGESTION_SPECIFICATION.md` describes the original 300K-story pipeline
  design. Where it disagrees with the code, the code is authoritative — note the
  discrepancy in the changelog rather than silently following the spec.
