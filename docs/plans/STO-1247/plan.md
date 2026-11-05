# Implementation Plan: STO-1247 — Safety filter false positives quarantine 43% of the corpus

**Date**: 2026-10-21 | **Spec**: [STO-1247](https://linear.app/jgfdev/issue/STO-1247/safety-filter-false-positives-quarantine-43percent-of-the-corpus) (issue body is the spec; no upstream `spec.md` exists in this repo)

## Summary

The safety filter in `pipeline/profiler.py` fails **43% of the corpus** (2,153 of 5,000 rows), and the majority of those verdicts are false positives. Three independent defects cause it:

1. A bare-numeral rule matches the words `thirteen|fourteen|fifteen` with no age context, so clock times, prices, jersey numbers and durations fail as CSAM risk.
2. The `anon.penet.fi` anonymiser footer contains the literal string `abuse@`, and `abuse` is a bare alternative in the extreme-violence list, so a privacy footer quarantines a story as prohibited content.
3. Genre-appropriate language (`assault`, `murder`, `rape`) sits in the same fail-closed list as genuinely prohibited content (`necrophilia`, `snuff`, `bestiality`), with no path to review.

The approach is to make each rule require real context, strip known boilerplate before screening, and split the violence verdict so that ambiguous-but-legal language routes to the already-defined-but-unused `FLAGGED_MANUAL_REVIEW` verdict instead of a hard fail. `FAIL_UNDERAGE_RISK` stays fail-closed.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = "==3.12.*"`), `from __future__ import annotations` at module top.
**Primary Dependencies**: stdlib only for this change (`re`, `html`, `unicodedata`). No new runtime dependency.
**Storage**: SQLite catalogue via `insights/corpus_prep.py`; `stories.safety_verdict` is a `TEXT` column with an index (`idx_stories_safety`). No schema change required — the new verdict is a new *value*, not a new column.
**Testing**: `pytest` (`python -m pytest tests/ -q`). Existing safety tests live in `tests/test_pipeline.py::TestStoryProfiler`.
**Target Platform**: Linux, local batch runs; also the streaming full-corpus ingester.
**Performance Goals**: No regression. `audit_safety` runs once per row over the full text; the added context checks must stay linear and must not introduce catastrophic backtracking. Regexes stay module-scope and pre-compiled.
**Constraints**:
- `AGENTS.md` is the governing document (no `constitution.md` exists). It requires: module-scope regex compilation, a changelog entry for every change, and reproducing a bug before claiming a fix.
- `FAIL_UNDERAGE_RISK` must remain fail-closed — a false negative here is a legal/compliance failure, which is strictly worse than a false positive.
- Downstream consumers gate on `== PASS`, so a new non-PASS verdict is excluded from TTS, embeddings, NER and UI inspiration views by default. This must be verified, not assumed.

## Constitution Check

*GATE: Must pass. Re-check after design review.*

No `constitution.md` exists in this repository. The governing constraints are `AGENTS.md` plus the safety posture implied by the issue. Evaluated against those:

| Principle | Source | Status |
| --- | --- | --- |
| Compile regexes at module scope | `AGENTS.md` | **PASS** — all new/changed patterns stay in the module-level `UNDERAGE_INDICATORS` / `EXTREME_VIOLENCE_INDICATORS` / new boilerplate lists, registered in `REGEX_PATTERNS` and validated by `validate_patterns()` at import. |
| Every change recorded in `CHANGELOG.md` | `AGENTS.md` | **PASS** — Phase 6 includes the changelog entry as a deliverable, not a follow-up. |
| Reproduce the bug before claiming a fix | `AGENTS.md` | **PASS** — Phase 1 builds the reproduction harness first; the 14-case probe already reproduces 9 false positives and 0 false negatives. |
| Fail-closed on underage/CSAM | Issue body | **PASS** — `FAIL_UNDERAGE_RISK` remains a hard fail; only its *trigger conditions* are narrowed to require real age context. |
| No silent behaviour change to consumers | Issue body | **PASS** — Phase 2 verifies the new verdict is quarantined everywhere; Phase 6 re-measures the PASS rate and records it. |
| Tests must fail without the guard | `AGENTS.md` | **PASS** — Phase 3-5 tasks each require a test verified to fail against the pre-change code. |

**No violations.** Complexity Tracking is therefore empty.

## Applied Guidelines

No matching guideline skill applies. The `guidelines` lookup targets framework-to-framework migration patterns (Struts→Spring, JSP→Thymeleaf, EJB→Spring Boot); this change is a context-precision fix to a rule-based classifier in a single Python module, with no framework migration involved. No guideline rules are integrated.

## Implementation Steps

### Step 1: [Cross-cutting] Baseline reproduction harness and fixtures

- **Group**: Cross-cutting
- **Requirements**: REQ-003, REQ-004
- **Design inputs**: Issue body evidence; `tests/test_pipeline.py::TestStoryProfiler`; `data/output/cleaned_catalog.jsonl`
- **Description**: Before changing any rule, capture the current behaviour so the fix is measurable and the tests are provably meaningful. Build a table-driven probe covering every false-positive class named in the issue plus every true-positive case that must survive, and record the baseline PASS rate. This step produces the evidence that later steps are judged against.

### Step 2: [Cross-cutting] Boilerplate stripping and verdict plumbing

- **Group**: Cross-cutting
- **Requirements**: REQ-006, REQ-007
- **Design inputs**: `pipeline/profiler.py:137-177` (`clean_text`), `pipeline/profiler.py:180-211` (`audit_safety`), `pipeline/schemas.py:10-14` (`SafetyVerdict`)
- **Description**: Two foundational changes that later steps depend on. First, strip known anonymiser/remailer boilerplate in `clean_text` so a privacy footer cannot reach the safety screen — verified that the `anon.penet.fi` footer currently survives cleaning. Second, add the `FLAGGED_MANUAL_REVIEW` routing path in `audit_safety` and confirm every consumer treats it as quarantined. `FLAGGED_MANUAL_REVIEW` already exists in the enum but is never produced or consumed.

### Step 3: [Cross-cutting] Eliminate bare-numeral false positives

- **Group**: Cross-cutting
- **Requirements**: REQ-001, REQ-002, REQ-005
- **Design inputs**: `pipeline/profiler.py:26-32` (`UNDERAGE_INDICATORS`), `pipeline/profiler.py:34` (`UNDERAGE_TAG_KEYWORDS`)
- **Description**: Remove the bare `fourteen|fifteen|thirteen` alternatives from rule 4 so the rule requires real age context, relying on rules 1-2 which already match `N years old` and `aged N`. Also tighten the substring-based tag match, which currently fails `"youthful"` because it contains `"youth"`. This is the single largest source of false positives: 10 of 19 `FAIL_UNDERAGE_RISK` verdicts in the 100-row catalogue are bare-numeral-only.

### Step 4: [Cross-cutting] Context-aware violence tiering

- **Group**: Cross-cutting
- **Requirements**: REQ-001, REQ-002, REQ-007
- **Design inputs**: `pipeline/profiler.py:36-38` (`EXTREME_VIOLENCE_INDICATORS`), `pipeline/schemas.py:10-14`
- **Description**: Split the violence list by severity. Keep genuinely prohibited content (`necrophilia`, `snuff`, `bestiality`, `zoophilia`) as `FAIL_EXTREME_VIOLENCE`. Route ambiguous-but-legal language (`abuse`, `rape`, `murder`, `assault`, `suicide`) to `FLAGGED_MANUAL_REVIEW`, and require `abuse`/`rape` to appear in a violence context rather than as a substring of an email address or URL. This addresses the 3-of-8 `abuse`-only verdicts in the 100-row catalogue and the 109-of-350 (31%) on the 5,000-row run.

### Step 5: [Cross-cutting] Negation awareness

- **Group**: Cross-cutting
- **Requirements**: REQ-008
- **Design inputs**: `pipeline/profiler.py:180-211`
- **Description**: Suppress a match when it is directly negated (`"he was not fifteen"`, `"she never mentioned being underage"`). Marked *if feasible* in the issue, so this step is lower priority and may be dropped without affecting REQ-001 through REQ-007. Must not weaken the fail-closed posture: a negation check that misfires would create a false negative, so it is scoped narrowly to an immediately-preceding negator.

### Step 6: [Cross-cutting] Re-measure, document, and record

- **Group**: Cross-cutting
- **Requirements**: REQ-003, REQ-004
- **Design inputs**: Phase 1 harness; `docs/INSIGHT_PLATFORM.md`; `CHANGELOG.md`; `COMMENTS.md`
- **Description**: Re-run the Phase 1 harness and the corpus measurement, record the before/after PASS rate, update the safety documentation, and add the mandatory `CHANGELOG.md` entry. Update the `COMMENTS.md` audit table to mark finding 2 resolved.

## Project Structure

```text
pipeline/
  profiler.py            # MODIFIED — safety rules, boilerplate stripping, verdict routing
  schemas.py             # unchanged (FLAGGED_MANUAL_REVIEW already defined)
insights/
  corpus_prep.py         # unchanged (gates on == PASS, so new verdict is quarantined)
tests/
  test_pipeline.py       # MODIFIED — false-positive and true-positive regression tests
  test_insights.py       # MODIFIED — corpus-level invariant test
docs/
  INSIGHT_PLATFORM.md    # MODIFIED — safety screening documentation
  plans/STO-1247/
    plan.md              # this file
    checkpoints/
      spec-to-plan.yaml
      plan-to-tasks.yaml
CHANGELOG.md             # MODIFIED — mandatory entry
COMMENTS.md              # MODIFIED — audit table status
```

## Testing Strategy

> Brownfield project; this section is mandatory.

- **appType**: Batch/CLI data pipeline (no HTTP surface for this change). The affected entry points are `python -m pipeline.cli` and `python -m insights.corpus_prep`.
- **Critical user journeys**:
  1. A clean adult story passes screening and reaches the TTS candidate queue.
  2. A story containing a bare numeral (`"fifteen minutes"`) passes screening.
  3. A story containing the `anon.penet.fi` footer passes screening.
  4. A story with genuine underage content (`"he was fifteen years old"`, `adult-youth` tag) still fails closed.
  5. A story with ambiguous violence language is quarantined as `FLAGGED_MANUAL_REVIEW` and excluded from the TTS queue.
- **primaryValidationStack**: `pytest` over `tests/` plus a direct `audit_safety` probe. No containers, browsers, or external services are required — the unit under test is a pure function over text.
- **fallbackMatrix**:
  - `infra-tier`: not applicable — no database or broker is needed to test `audit_safety`. The corpus-level measurement reads the existing `data/output/cleaned_catalog.jsonl` artefact. Prerequisite: none.
  - `browser-tier`: not applicable — no UI surface changes. Prerequisite: none.
- **Environment requirements**: Python 3.12 with the repo `.venv`. No Docker, no Node, no network.
- **knownGaps**: The full 18.8 GB `stories_clean.csv` is **not currently present** (`data/stories_clean.csv` symlink is gone), so the full-corpus PASS-rate re-measurement in REQ-003 cannot be completed in this environment. The 100-row `data/output/cleaned_catalog.jsonl` is available and is used as the measurable proxy; the full-corpus figure must be re-measured when the corpus is restored, and the plan records this as an explicit open item rather than claiming the number.
- **Test data strategy**: Table-driven cases inline in `tests/test_pipeline.py` (no external fixtures). Corpus-level assertions read the checked-in 100-row artefact. No seeding or cleanup needed — tests are pure and read-only.
- **Acceptance criteria**: All 14 probe cases in the Phase 1 harness produce their expected verdict; the existing 43 tests still pass; the bare-numeral-only false-positive count in the 100-row catalogue drops from 10 to 0; the `abuse`-only violence count drops from 3 to 0; no true-positive case regresses.
- **Validation review expectations**: A reviewer confirms (a) `FAIL_UNDERAGE_RISK` still fires on all genuine cases, (b) the new verdict is excluded from every `== PASS` gate, (c) each new test was verified to fail against the pre-change code, and (d) the changelog entry exists.

## Complexity Tracking

> No Constitution Check violations. This section is intentionally empty.

## Tasks

### Phase 1: Setup — baseline reproduction harness

**Purpose**: Capture current behaviour so the fix is measurable and the tests are provably meaningful.

- [ ] T001 [P] [Plan:1.1] Add a table-driven safety probe to `tests/test_pipeline.py` covering all 9 false-positive classes and 5 true-positive cases from the issue, asserting expected verdicts
- [ ] T002 [P] [Plan:1.1] Record the baseline: run the probe and the 100-row catalogue measurement, capturing PASS rate, bare-numeral-only count (10) and `abuse`-only count (3) in `docs/plans/STO-1247/baseline.md`
- [ ] T003 [Plan:1.1] Verify the probe fails against current `HEAD` (9 false positives expected) so the tests are known to be meaningful

**Checkpoint**: Baseline captured and the probe demonstrably fails on unmodified code.

---

### Phase 2: Foundational — boilerplate stripping and verdict plumbing

**Purpose**: Blocking prerequisites. Both later rule changes depend on these.

**⚠️ CRITICAL**: No rule change can be validated until the new verdict is correctly quarantined.

- [ ] T004 [P] [Plan:2.1] Add an `ANONYMISER_BOILERPLATE` pattern list to `pipeline/profiler.py` matching remailer footers (`anon.penet.fi`, `report inappropriate use to`, `help@anon.penet.fi`) and register it in `REGEX_PATTERNS`
- [ ] T005 [Plan:2.1] Apply the boilerplate patterns in `StoryProfiler.clean_text` at `pipeline/profiler.py:137` so the footer is removed before screening
- [ ] T006 [P] [Plan:2.2] Add a `FLAGGED_MANUAL_REVIEW` return path to `StoryProfiler.audit_safety` at `pipeline/profiler.py:180`, with a distinct reason string
- [ ] T007 [Plan:2.2] Verify every consumer treats `FLAGGED_MANUAL_REVIEW` as quarantined: `pipeline/tts_prioritizer.py:142`, `pipeline/orchestrator.py:123,131`, `insights/corpus_prep.py:537`, `insights/analysis.py`, `insights/ner.py`, `insights/semantic.py`, `insights/ui.py` — all gate on `== PASS`, so confirm by test rather than inspection
- [ ] T008 [Plan:2.2] Add a test asserting a `FLAGGED_MANUAL_REVIEW` story is absent from `TTSPrioritizer.filter_and_rank_candidates` output

**Checkpoint**: Boilerplate is stripped and the new verdict is provably quarantined.

---

### Phase 3: User Story 1 — eliminate bare-numeral false positives (Priority: P1) 🎯 MVP

**Goal**: A story that merely mentions a number no longer fails as CSAM risk, while genuine age references still fail closed.

**Independent Test**: The 5 bare-numeral probe cases return `PASS`; the 3 genuine underage cases still return `FAIL_UNDERAGE_RISK`.

- [ ] T009 [US1] [Plan:3.1] Remove the bare `fourteen|fifteen|thirteen` alternatives from rule 4 of `UNDERAGE_INDICATORS` at `pipeline/profiler.py:30`, keeping the `high school freshman` / `junior high boy` / `middle school boy` phrases
- [ ] T010 [US1] [Plan:3.1] Confirm rules 1-2 at `pipeline/profiler.py:27-28` still cover `N years old` and `aged N` after the removal, and that no genuine case depended solely on rule 4
- [ ] T011 [P] [US1] [Plan:3.2] Tighten the tag match at `pipeline/profiler.py:191` from substring (`k in tag_clean`) to exact/word-boundary matching so `"youthful"` no longer matches `"youth"`
- [ ] T012 [US1] [Plan:3.1,3.2] Add regression tests for each bare-numeral class (`"fifteen minutes"`, `"his number was thirteen"`, `"the lamp only cost fourteen"`, `"six-fifteen"`, `"thirteen penis-lengths tall"`) and for the `"youthful"` tag
- [ ] T013 [US1] [Plan:3.1] Verify each new test fails against the pre-change code by temporarily reverting the rule change
- [ ] T014 [US1] [Plan:3.1] Re-run the 100-row catalogue measurement and confirm bare-numeral-only false positives drop from 10 to 0

**Checkpoint**: US1 complete — the largest false-positive class is eliminated with no true-positive regression.

---

### Phase 4: User Story 2 — context-aware violence tiering (Priority: P1)

**Goal**: A privacy footer or erotic metaphor no longer quarantines a story as prohibited content, while genuinely prohibited content still fails.

**Independent Test**: The `anon.penet.fi` footer and the `assault`/`murder` metaphor cases return `FLAGGED_MANUAL_REVIEW`; `necrophilia`/`snuff`/`bestiality` still return `FAIL_EXTREME_VIOLENCE`.

- [ ] T015 [US2] [Plan:4.1] Split `EXTREME_VIOLENCE_INDICATORS` at `pipeline/profiler.py:36-38` into a hard-fail list (`necrophilia`, `snuff`, `bestiality`, `zoophilia`) and a review list (`abuse`, `rape`, `murder`, `assault`, `suicide`, `kill myself`)
- [ ] T016 [US2] [Plan:4.1] Route the review list to `FLAGGED_MANUAL_REVIEW` in `audit_safety`, preserving `FAIL_EXTREME_VIOLENCE` for the hard-fail list
- [ ] T017 [US2] [Plan:4.2] Require `abuse` and `rape` to appear in a violence context, excluding matches inside an email address or URL (e.g. `abuse@`, `rape` as a substring of a domain)
- [ ] T018 [P] [US2] [Plan:4.1,4.2] Add regression tests: footer case, `"his assault on the hard throbbing cock"`, `"screamed bloody murder into my gag"`, `"he would murder me"` → `FLAGGED_MANUAL_REVIEW`; `necrophilia`/`snuff`/`bestiality` → `FAIL_EXTREME_VIOLENCE`
- [ ] T019 [US2] [Plan:4.1] Verify each new test fails against the pre-change code
- [ ] T020 [US2] [Plan:4.1] Re-run the 100-row measurement and confirm `abuse`-only violence verdicts drop from 3 to 0

**Checkpoint**: US2 complete — ambiguous language is quarantined for review rather than hard-failed.

---

### Phase 5: User Story 3 — negation awareness (Priority: P3, optional)

**Goal**: A directly negated age reference does not fail the story.

**Independent Test**: `"he was not fifteen"` returns `PASS`; `"he was fifteen"` still returns `FAIL_UNDERAGE_RISK`.

- [ ] T021 [US3] [Plan:5.1] Add a narrow negator check (immediately-preceding `not`/`never`/`no longer`) to the underage match path in `audit_safety` at `pipeline/profiler.py:194`
- [ ] T022 [US3] [Plan:5.1] Add tests for the negated and non-negated forms, and assert the negator check cannot suppress a match when the negator is not adjacent
- [ ] T023 [US3] [Plan:5.1] Verify the negator check does not create a false negative on any of the 5 true-positive probe cases

**Checkpoint**: US3 complete, or explicitly dropped with the reason recorded in `plan.md`.

---

### Phase 6: Polish — re-measure, document, record

**Purpose**: Close out the issue's acceptance criteria and satisfy `AGENTS.md`.

- [ ] T024 [Plan:6.1] Re-run the full Phase 1 probe and record the final pass/false-positive/false-negative counts in `docs/plans/STO-1247/baseline.md`
- [ ] T025 [Plan:6.1] Re-measure the PASS rate on the 100-row catalogue and record before/after; note the full-corpus figure as an open item because `data/stories_clean.csv` is absent
- [ ] T026 [P] [Plan:6.2] Update the safety-screening section of `docs/INSIGHT_PLATFORM.md` to document the three verdicts and the review tier
- [ ] T027 [P] [Plan:6.3] Add the mandatory `CHANGELOG.md` entry under `## [Unreleased]` → `### Fixed` and `### Security`
- [ ] T028 [Plan:6.3] Update the finding-2 row of the audit table in `COMMENTS.md` to resolved, with the measured before/after
- [ ] T029 [Plan:6.1] Run `python -m pytest tests/ -q` and `python -m ruff check` on changed files; confirm no new lint findings versus baseline

**Checkpoint**: All acceptance criteria met and recorded.

---

## Requirement Mapping

| REQ ID | Description | Plan Items | Implementation Evidence |
|--------|-------------|------------|------------------------|
| REQ-001 | The five reproductions in the issue no longer return a FAIL verdict | 3.1, 3.2, 4.1, 4.2 | `pipeline/profiler.py` `UNDERAGE_INDICATORS` rule 4, `EXTREME_VIOLENCE_INDICATORS` split, boilerplate stripping; probe cases in `tests/test_pipeline.py` |
| REQ-002 | `FAIL_UNDERAGE_RISK` still catches genuine cases (`"he was fifteen years old"`, `adult-youth` tag, `"under 18"`) | 3.1, 3.2, 5.1 | Rules 1-3 retained at `pipeline/profiler.py:27-29`; tag match tightened not removed; true-positive probe cases |
| REQ-003 | PASS rate re-measured and recorded before/after | 1.1, 6.1 | `docs/plans/STO-1247/baseline.md`; 100-row catalogue measurement; full-corpus figure flagged as open |
| REQ-004 | Tests covering each false-positive class and each retained true-positive case | 1.1, 3.1, 3.2, 4.1, 4.2, 5.1 | Table-driven probe in `tests/test_pipeline.py`; each test verified to fail pre-change (T003, T013, T019) |
| REQ-005 | Bare-numeral rule requires real age context | 3.1 | `pipeline/profiler.py:30` rule 4 rewritten; rules 1-2 cover `N years old` / `aged N` |
| REQ-006 | Known boilerplate excluded before screening | 2.1 | `ANONYMISER_BOILERPLATE` in `pipeline/profiler.py`; applied in `clean_text` at `pipeline/profiler.py:137` |
| REQ-007 | `abuse`/`rape`/`murder`/`assault` routed to `FLAGGED_MANUAL_REVIEW` | 2.2, 4.1, 4.2 | `audit_safety` review path at `pipeline/profiler.py:180`; consumer quarantine verified by T007/T008 |
| REQ-008 | Negation awareness (if feasible) | 5.1 | Narrow negator check in `audit_safety`; may be dropped with reason recorded |

**Coverage**: 8 of 8 requirements mapped. No requirement is unmapped.
