"""Corpus-level analysis for the insight platform.

Reads the SQLite catalog produced by insights.corpus_prep and emits the
aggregate statistics the dashboards and findings report are built from:

- summary: corpus shape, dedup rate, safety, quality tiers
- distributions: tropes, heat, POV, pacing, settings, archetypes, duration,
  categories, top authors
- trends: per-year and per-decade volume + trope/category mix

All aggregates over *canonical, safety-passing* stories are the
"authoring inspiration" view; safety-failed rows are reported only as
compliance counts (never distributed, never rendered as content).
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

PASS = "PASS"


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> List[tuple]:
    return conn.execute(sql, args).fetchall()


def load_story_json(value: Optional[str], default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def compute_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    total, canonical, dups = conn.execute(
        "SELECT count(*), sum(is_canonical), sum(1-is_canonical) FROM stories").fetchone()
    safety = dict(_rows(conn,
                        "SELECT safety_verdict, count(*) FROM stories WHERE is_canonical=1 "
                        "GROUP BY safety_verdict"))
    tiers = dict(_rows(conn,
                       "SELECT quality_tier, count(*) FROM stories WHERE is_canonical=1 "
                       "GROUP BY quality_tier"))
    words, minutes, n_pass = conn.execute(
        "SELECT sum(word_count), sum(tts_minutes), count(*) FROM stories "
        "WHERE is_canonical=1 AND safety_verdict=?", (PASS,)).fetchone()
    q = conn.execute(
        "SELECT avg(quality_total), min(quality_total), max(quality_total) "
        "FROM stories WHERE is_canonical=1 AND safety_verdict=?", (PASS,)).fetchone()
    years = conn.execute(
        "SELECT min(publication_date), max(publication_date) FROM stories "
        "WHERE is_canonical=1 AND safety_verdict=? AND publication_date != ''",
        (PASS,)).fetchone()
    authors = conn.execute(
        "SELECT count(DISTINCT author) FROM stories "
        "WHERE is_canonical=1 AND safety_verdict=?", (PASS,)).fetchone()[0]
    categories = conn.execute(
        "SELECT count(DISTINCT category) FROM stories WHERE is_canonical=1").fetchone()[0]
    return {
        "total_rows": total or 0,
        "canonical_stories": canonical or 0,
        "duplicate_rows": dups or 0,
        "duplicate_rate_pct": round(100.0 * (dups or 0) / max(total or 1, 1), 1),
        "canonical_safety": safety,
        "canonical_tiers": tiers,
        "passing_stories": n_pass or 0,
        "passing_words": words or 0,
        "passing_audio_hours": round((minutes or 0) / 60.0, 1),
        "quality_avg": round(q[0] or 0, 1),
        "quality_min": q[1],
        "quality_max": q[2],
        "date_range": [years[0], years[1]],
        "distinct_authors": authors,
        "distinct_categories": categories,
    }


def compute_distributions(conn: sqlite3.Connection) -> Dict[str, Any]:
    scope = "is_canonical=1 AND safety_verdict='PASS'"
    out: Dict[str, Any] = {}
    for key, col, agg_json in [
        ("tropes", "tropes", True),
        ("archetypes", "archetypes", True),
        ("settings", "settings", True),
        ("heat", "heat_level", False),
        ("pov", "pov", False),
        ("pacing", "pacing", False),
        ("duration_tier", "duration_tier", False),
        ("category", "category", False),
    ]:
        counter: Counter = Counter()
        if agg_json:
            for (val,) in _rows(conn, f"SELECT {col} FROM stories WHERE {scope}"):
                for item in load_story_json(val, []):
                    counter[item] += 1
        else:
            counter.update({str(k): v for k, v in
                            _rows(conn, f"SELECT {col}, count(*) FROM stories WHERE {scope} GROUP BY {col}")})
        out[key] = counter.most_common(40)

    top_authors = _rows(conn,
                        f"SELECT author, count(*) n, sum(word_count) w FROM stories WHERE {scope} "
                        "GROUP BY author ORDER BY n DESC, w DESC LIMIT 25")
    out["top_authors"] = [
        {"author": a, "stories": n, "words": w or 0} for a, n, w in top_authors if a]
    out["author_attribution_pct"] = round(100.0 * conn.execute(
        f"SELECT count(*) FROM stories WHERE {scope} AND author != 'Unknown / Anonymous'"
    ).fetchone()[0] / max(conn.execute(
        f"SELECT count(*) FROM stories WHERE {scope}").fetchone()[0], 1), 1)

    buckets = _rows(conn, f"""
        SELECT CASE
                 WHEN word_count < 500 THEN '<500'
                 WHEN word_count < 1000 THEN '500-1K'
                 WHEN word_count < 2000 THEN '1K-2K'
                 WHEN word_count < 4000 THEN '2K-4K'
                 WHEN word_count < 8000 THEN '4K-8K'
                 WHEN word_count < 16000 THEN '8K-16K'
                 ELSE '16K+' END AS len_bucket,
               count(*)
        FROM stories WHERE {scope} GROUP BY len_bucket""")
    order = ['<500', '500-1K', '1K-2K', '2K-4K', '4K-8K', '8K-16K', '16K+']
    cmap = dict(buckets)
    out["length_buckets"] = [(b, cmap.get(b, 0)) for b in order]
    return out


def compute_trends(conn: sqlite3.Connection, top_n: int = 8) -> Dict[str, Any]:
    scope = "is_canonical=1 AND safety_verdict='PASS'"
    yearly = {}
    for (year,) in _rows(conn, f"""
            SELECT substr(publication_date, 1, 4) y FROM stories WHERE {scope}
            AND publication_date != '' GROUP BY y ORDER BY y"""):
        if year and year.isdigit() and 1970 <= int(year) <= 2026:
            yearly[year] = None
    years = sorted(yearly)
    trend_rows: List[Dict[str, Any]] = []
    for year in years:
        row = conn.execute(
            f"SELECT count(*), avg(word_count), avg(heat_level), "
            f"avg(quality_total) FROM stories WHERE {scope} "
            f"AND substr(publication_date,1,4)=?", (year,)).fetchone()
        trend_rows.append({
            "year": year, "stories": row[0] or 0,
            "avg_words": round(row[1] or 0), "avg_heat": round(row[2] or 0, 2),
            "avg_quality": round(row[3] or 0, 1),
        })
    # trope share by era (decades) — top tropes overall
    tropes_overall = Counter()
    for (val,) in _rows(conn, f"SELECT tropes FROM stories WHERE {scope}"):
        for t in load_story_json(val, []):
            tropes_overall[t] += 1
    top_tropes = [t for t, _ in tropes_overall.most_common(top_n)]
    era_counts: Dict[str, Counter] = defaultdict(Counter)
    for (decade, val) in _rows(conn, f"""
            SELECT substr(publication_date, 1, 3) || '0s' AS decade, tropes
            FROM stories WHERE {scope} AND length(publication_date) >= 4"""):
        for t in load_story_json(val, []):
            if t in top_tropes:
                era_counts[decade][t] += 1
    era_totals = {d: sum(c.values()) for d, c in era_counts.items()}
    trope_share = {
        d: [[t, round(100.0 * era_counts[d][t] / max(era_totals[d], 1), 1)] for t in top_tropes]
        for d in sorted(era_counts)
    }
    category_by_era: Dict[str, List] = {}
    cat_rows = _rows(conn, f"""
        SELECT substr(publication_date, 1, 3) || '0s' AS decade, category, count(*) n
        FROM stories WHERE {scope} AND length(publication_date) >= 4
        GROUP BY decade, category ORDER BY decade, n DESC""")
    cat_by_decade: Dict[str, List] = defaultdict(list)
    for decade, category, n in cat_rows:
        cat_by_decade[decade].append([category, n])
    return {
        "yearly": trend_rows,
        "top_tropes": top_tropes,
        "trope_share_by_decade": trope_share,
        "top_categories_by_decade": {d: v[:10] for d, v in sorted(cat_by_decade.items())},
    }


def quality_breakdown_by_dimension(conn: sqlite3.Connection) -> Dict[str, Any]:
    scope = "is_canonical=1 AND safety_verdict='PASS'"
    out = {}
    for dim in ("pacing", "pov", "duration_tier", "category"):
        rows = _rows(conn, f"""
            SELECT {dim}, count(*), avg(quality_total), avg(heat_level), avg(word_count)
            FROM stories WHERE {scope} GROUP BY {dim} ORDER BY count(*) DESC LIMIT 15""")
        out[dim] = [
            {"label": str(label), "stories": n, "avg_quality": round(q or 0, 1),
             "avg_heat": round(h or 0, 2), "avg_words": round(w or 0)}
            for label, n, q, h, w in rows]
    return out


def run_analysis(db_path: str, out_dir: str) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        result = {
            "summary": compute_summary(conn),
            "distributions": compute_distributions(conn),
            "trends": compute_trends(conn),
            "quality_by_dimension": quality_breakdown_by_dimension(conn),
        }
    finally:
        conn.close()
    path = os.path.join(out_dir, "analysis.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    return result


def main(argv: Optional[List[str]] = None) -> None:
    import argparse
    p = argparse.ArgumentParser(description="Corpus analysis (JGF-12)")
    p.add_argument("--db", required=True)
    p.add_argument("--out-dir", default="insights_output/analysis")
    args = p.parse_args(argv)
    result = run_analysis(args.db, args.out_dir)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
