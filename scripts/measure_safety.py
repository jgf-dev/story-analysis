"""Safety-filter measurement harness for STO-1247.

Samples the full corpus and reports the verdict distribution plus the
false-positive classes described in the issue. Used to produce the before/after
numbers in docs/plans/STO-1247/baseline.md.

Usage:
    python scripts/measure_safety.py --csv data/stories_clean.csv --limit 5000
    python scripts/measure_safety.py --csv data/stories_clean.csv --limit 5000 --json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.profiler import StoryProfiler

csv.field_size_limit(64 * 1024 * 1024)

# --- classification helpers -------------------------------------------------
# These mirror the rule structure so a verdict can be attributed to a cause.
BARE_NUMERAL = re.compile(r"\b(?:thirteen|fourteen|fifteen)\b", re.IGNORECASE)
AGE_PHRASE = re.compile(
    r"\b(?:1[0-5]|thirteen|fourteen|fifteen)\s*(?:-| )*(?:years?|yrs?)(?:-| )*old\b",
    re.IGNORECASE,
)
AGED_PHRASE = re.compile(r"\bage[d]?\s*(?:1[0-5]|thirteen|fourteen|fifteen)\b", re.IGNORECASE)
UNDERAGE_TAGS = {"adult-youth", "youth", "underage", "prepubescent", "junior-high"}
ANONYMISER = re.compile(r"anon\.penet\.fi|report\s+inappropriate\s+use", re.IGNORECASE)


def read_rows(csv_path: str, limit: int | None):
    """Yield dict rows using an RFC-quote-balanced reader (multi-line records)."""
    with open(csv_path, "r", encoding="utf-8", errors="replace", newline="") as f:
        fieldnames = next(csv.reader(f))
        buf: list[str] = []
        quote_count = 0
        n = 0
        for line in f:
            buf.append(line)
            quote_count += line.count('"')
            if quote_count % 2:
                continue
            row = next(csv.reader(io.StringIO("".join(buf))))
            buf = []
            quote_count = 0
            yield {name: row[i] if i < len(row) else "" for i, name in enumerate(fieldnames)}
            n += 1
            if limit and n >= limit:
                return


def classify_underage(clean: str, tags: list[str], flagged: set[str]) -> str:
    if flagged & UNDERAGE_TAGS:
        return "tag-driven"
    if AGE_PHRASE.search(clean) or AGED_PHRASE.search(clean):
        return "real age phrase"
    if flagged <= {"thirteen", "fourteen", "fifteen"}:
        return "BARE NUMERAL ONLY (false positive)"
    return "other"


def classify_violence(flagged: set[str]) -> str:
    if flagged == {"abuse"}:
        return 'ONLY "abuse" (false positive)'
    return "other"


def main() -> None:
    p = argparse.ArgumentParser(description="Measure safety-filter verdicts over the corpus")
    p.add_argument("--csv", required=True)
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = p.parse_args()

    profiler = StoryProfiler()
    verdicts: Counter = Counter()
    underage_causes: Counter = Counter()
    violence_causes: Counter = Counter()
    words_by_verdict: dict[str, list[int]] = {}
    anon_footer = 0
    anon_footer_failed = 0
    n = 0

    for row in read_rows(args.csv, args.limit):
        content = row.get("content") or ""
        tags = [t for t in (row.get("orientation"), row.get("category")) if t]
        clean = profiler.clean_text(content, header_scan_chars=3000)
        audit = profiler.audit_safety(clean, tags)
        verdict = audit.verdict.value
        verdicts[verdict] += 1
        n += 1

        wc = len(re.findall(r"\b\w+\b", clean))
        words_by_verdict.setdefault(verdict, []).append(wc)

        flagged = {t.lower() for t in (audit.flagged_terms or [])}
        if verdict == "FAIL_UNDERAGE_RISK":
            underage_causes[classify_underage(clean, tags, flagged)] += 1
        elif verdict == "FAIL_EXTREME_VIOLENCE":
            violence_causes[classify_violence(flagged)] += 1

        if ANONYMISER.search(content):
            anon_footer += 1
            if verdict != "PASS":
                anon_footer_failed += 1

    def median(xs: list[int]) -> float:
        if not xs:
            return 0.0
        s = sorted(xs)
        return float(s[len(s) // 2])

    result = {
        "rows_sampled": n,
        "verdicts": dict(verdicts),
        "pass_rate_pct": round(100 * verdicts.get("PASS", 0) / max(n, 1), 1),
        "median_words_by_verdict": {k: median(v) for k, v in words_by_verdict.items()},
        "underage_causes": dict(underage_causes),
        "violence_causes": dict(violence_causes),
        "anon_footer_rows": anon_footer,
        "anon_footer_non_pass": anon_footer_failed,
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"rows sampled: {n}")
    print(f"PASS rate   : {result['pass_rate_pct']}%")
    print()
    print("verdicts:")
    for k, v in verdicts.most_common():
        print(f"  {k:24s} {v:6d}  ({100*v/max(n,1):5.1f}%)  median_words={median(words_by_verdict.get(k, [])):,.0f}")
    print()
    print("FAIL_UNDERAGE_RISK causes:")
    for k, v in underage_causes.most_common():
        print(f"  {k:40s} {v:6d}")
    print()
    print("FAIL_EXTREME_VIOLENCE causes:")
    for k, v in violence_causes.most_common():
        print(f"  {k:40s} {v:6d}")
    print()
    print(f"rows containing an anonymiser footer: {anon_footer}")
    print(f"  of those, non-PASS verdicts        : {anon_footer_failed}")


if __name__ == "__main__":
    main()
