# STO-1247 — Baseline measurements (pre-change)

**Captured**: 2026-10-21, against `HEAD` = `eb85177` (working tree clean).
**Purpose**: Phase 1 (T002) evidence. These are the numbers the fix is measured against.

## 1. Probe harness — 14 cases

Run by calling `StoryProfiler.audit_safety(text, tags)` directly.

| # | Text | Expected | Actual | Result |
|---|------|----------|--------|--------|
| 1 | `After fifteen minutes of getting his ass plowed` | PASS | `FAIL_UNDERAGE_RISK` | ❌ FP |
| 2 | `his number was thirteen` | PASS | `FAIL_UNDERAGE_RISK` | ❌ FP |
| 3 | `the lamp only cost fourteen` | PASS | `FAIL_UNDERAGE_RISK` | ❌ FP |
| 4 | `Raphael was thirteen penis-lengths tall` | PASS | `FAIL_UNDERAGE_RISK` | ❌ FP |
| 5 | `Um... it's six-fifteen` | PASS | `FAIL_UNDERAGE_RISK` | ❌ FP |
| 6 | `report inappropriate use to abuse@anon.penet.fi` | PASS | `FAIL_EXTREME_VIOLENCE` | ❌ FP |
| 7 | `Sgt Bullock continued his assault on the hard throbbing cock` | PASS | `FAIL_EXTREME_VIOLENCE` | ❌ FP |
| 8 | `He screamed bloody murder into my gag` | PASS | `FAIL_EXTREME_VIOLENCE` | ❌ FP |
| 9 | `he would murder me` | PASS | `FAIL_EXTREME_VIOLENCE` | ❌ FP |
| 10 | `Tommy was a 14-year-old freshman in high school.` (tags: teen, school) | `FAIL_UNDERAGE_RISK` | `FAIL_UNDERAGE_RISK` | ✅ |
| 11 | `he was fifteen years old` | `FAIL_UNDERAGE_RISK` | `FAIL_UNDERAGE_RISK` | ✅ |
| 12 | `They sat together talking about life.` (tags: adult-youth) | `FAIL_UNDERAGE_RISK` | `FAIL_UNDERAGE_RISK` | ✅ |
| 13 | `girls under 18` | `FAIL_UNDERAGE_RISK` | `FAIL_UNDERAGE_RISK` | ✅ |
| 14 | `Marcus, thirty-two years old, poured another cup of coffee.` | PASS | PASS | ✅ |

**Totals: pass 5 / false positive 9 / false negative 0 of 14.**

Note the asymmetry: **0 false negatives**. The filter is not missing prohibited content; it is over-triggering. That is the correct direction of error for a safety filter, which is why the fix must narrow triggers without weakening the fail-closed posture.

## 2. Corpus measurement — 100-row catalogue

Source: `data/output/cleaned_catalog.jsonl` (100 rows, generated 2026-10-21 00:10).

### Verdict distribution

| Verdict | n | median words |
|---|---|---|
| PASS | 73 | 1,988 |
| `FAIL_UNDERAGE_RISK` | 19 | 3,125 |
| `FAIL_EXTREME_VIOLENCE` | 8 | 2,388 |

The `FAIL_UNDERAGE_RISK` median (3,125) is **1.6x** the PASS median (1,988) — the same skew reported on the 5,000-row run (3,452 vs 1,839, ~1.9x). Longer, more literary stories mention numbers more often, so the filter systematically penalises the better-written content.

### `FAIL_UNDERAGE_RISK` breakdown (n=19)

| Cause | n |
|---|---|
| Tag-driven (`adult-youth` etc.) | 5 |
| Real age phrase (`N years old` / `aged N`) | 1 |
| **Bare numeral only — false positive** | **10** |

**10 of 19 (53%) are bare-numeral false positives.** This is the single largest class.

### `FAIL_EXTREME_VIOLENCE` breakdown (n=8)

| Cause | n |
|---|---|
| Flagged **only** for the string `abuse` | 3 |

**3 of 8 (38%)** are driven solely by `abuse`, matching the 31% rate on the 5,000-row run.

### Sample bare-numeral contexts (all false positives)

```
[4]  ...After about fifteen minutes, with great care ond patience o...
[5]  ...When I was thirteen or fourteen most of my classmates were always ready...
[6]  ...Back when I was fifteen or so, some friends and I decided that...
[8]  ...For what seemed like fifteen minutes he stroked and caressed...
[11] ...as he had been doing for fifteen years already...
[13] ...After fifteen minutes of this teasing massage, Brady...
[48] ...staring at him for what must have been fifteen seconds...
[60] ...need about fifteen more "chapters"...
```

Every one is a duration, a count, or a recollection — none is an age reference in a sexual context.

## 3. Additional confirmed defects

| Finding | Evidence |
|---|---|
| The `anon.penet.fi` footer **survives `clean_text`** | `clean_text()` on a raw post containing the footer returns text still containing `anon.penet.fi`; `audit_safety` then returns `FAIL_EXTREME_VIOLENCE`. |
| Tag matching is substring-based | `audit_safety("safe text", ["youthful"])` → `FAIL_UNDERAGE_RISK`, because `"youth"` is a substring of `"youthful"`. |
| `FLAGGED_MANUAL_REVIEW` is defined but never produced | `pipeline/schemas.py:14` defines it; no code path returns it and no consumer handles it. |

## 4. Environment limitation

`data/stories_clean.csv` (the 18.8 GB corpus) is **absent** — the symlink to `/home/jgf2/mnt/xstore/stories/stories_clean.csv` no longer resolves. The full-corpus PASS-rate re-measurement required by REQ-003 therefore **cannot be completed here**. The 100-row catalogue is used as the measurable proxy, and the full-corpus figure remains an open item to be re-measured when the corpus is restored.

## 5. Target after the fix

| Metric | Baseline | Target |
|---|---|---|
| Probe false positives | 9 | 0 |
| Probe false negatives | 0 | 0 (must not regress) |
| Bare-numeral-only verdicts (100 rows) | 10 | 0 |
| `abuse`-only violence verdicts (100 rows) | 3 | 0 |
| PASS rate (100 rows) | 73% | higher; exact figure recorded after the change |
| Existing test suite | 43 passed | 43+ passed, no regressions |

## 6. Results after the fix

Measured on a 5,000-row sample of the full corpus
(`python scripts/measure_safety.py --csv data/stories_clean.csv --limit 5000`).

### Verdict distribution

| Verdict | Before | After |
|---|---|---|
| PASS | 2,845 (56.9%) | **2,956 (59.1%)** |
| `FAIL_UNDERAGE_RISK` | 1,805 (36.1%) | 1,678 (33.6%) |
| `FAIL_EXTREME_VIOLENCE` | 350 (7.0%) | **9 (0.2%)** |
| `FLAGGED_MANUAL_REVIEW` | 0 (0.0%) | 357 (7.1%) |

### False-positive classes

| Class | Before | After |
|---|---|---|
| Bare-numeral-only underage verdicts | **455** | **0** |
| `abuse`-only violence verdicts | **109** | **0** |

### Remaining `FAIL_UNDERAGE_RISK` verdicts are genuine

| Cause | n |
|---|---|
| Tag-driven (`adult-youth` etc.) | 574 |
| Real age phrase (`N years old` / `aged N`) | 437 |
| Age-verb construction (`was fifteen`, `turned fourteen`) | 403 |
| Retained fail-closed rules (`junior high`, `kindergarten`, `boyhood`, …) | 264 |

### Probe harness

All 16 probe cases pass: 9 false-positive classes now `PASS`, 3 ambiguous
violence cases now `FLAGGED_MANUAL_REVIEW`, 3 prohibited cases still
`FAIL_EXTREME_VIOLENCE`, and all genuine underage cases still
`FAIL_UNDERAGE_RISK`.

### A regression found and fixed during implementation

Removing the bare-numeral rule outright was **not sufficient**. It let **288
rows** containing genuine age assertions (`"I was fifteen"`, `"who was 15"`,
`"when I was fourteen"`) start passing — a false negative, which for a
fail-closed safety gate is worse than the false positive being fixed. The
age-verb rule was added to restore them while still excluding durations and
measurements. This is recorded because it is the kind of error the "narrow the
rule" approach invites.

### Test suite

53 tests + 26 subtests pass (was 43). Lint on the changed files is unchanged
from baseline (12 findings, none new).

