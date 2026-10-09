"""Entity extraction and combination search (trope x setting x character-type).

Zero-budget, deterministic lexicon/regex NER tuned for gay male erotica.
Extraction runs over title + preview of canonical, safety-passing stories and
writes an `entity_mentions` table into the catalog DB, enabling combination
queries such as trope x setting x character-type with counts per facet.

This is research tagging of an internal reference dataset only; entity labels
are coarse storycraft dimensions (settings, roles, dynamics) used to find
inspiration patterns for new original stories.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

# --- Lexicons ---------------------------------------------------------------
# Each entry: label -> regex over lowercase text.

SETTING_PATTERNS = {
    "locker room / gym": r"\b(locker ?room|gym(nasium)?|weight ?room|bench press)\b",
    "bar / club": r"\b(bar|pub|nightclub|dance floor|club)\b",
    "sauna / bathhouse": r"\b(sauna|steam room|bathhouse|spa)\b",
    "beach": r"\b(beach|ocean|seaside|surf)\b",
    "office": r"\b(office|cubicle|boardroom|meeting room)\b",
    "hotel": r"\b(hotel|motel|room key|concierge)\b",
    "dorm / campus": r"\b(dorm(itory)?|campus|frat(ernity)? house|student union)\b",
    "cabin / woods": r"\b(cabin|woods|forest|mountain|lodge|camp(fire|site|ing)?)\b",
    "farm / rural": r"\b(farm|barn|field|tractor|countryside)\b",
    "truck stop / road": r"\b(truck stop|rest stop|highway|roadside|gas station)\b",
    "apartment": r"\b(apartment|flat|studio)\b",
    "shower": r"\b(shower|showerhead)\b",
    "military base": r"\b(base|barracks|ship|deployed|aircraft carrier)\b",
    "hospital": r"\b(hospital|clinic|ward)\b",
    "prison": r"\b(prison|jail|cell block|inmate)\b",
    "public restroom": r"\b(restroom|public toilet|stall)\b",
}

CHARACTER_PATTERNS = {
    "jock / athlete": r"\b(jock|athlete|football|basketball|swimmer|wrestler|coach)\b",
    "military / cop": r"\b(soldier|marine|cop|officer|detective|fireman|firefighter)\b",
    "student": r"\b(student|freshman|college boy|undergrad|roommate)\b",
    "office worker": r"\b(boss|manager|intern|colleague|secretary|coworker|executive)\b",
    "blue collar": r"\b(construction|mechanic|plumber|electrician|truck(er| driver)|laborer)\b",
    "straight / curious": r"\b(straight|bi-curious|curious|never (been|done) (with|this))\b",
    "married man": r"\b(married|wife|wedding ring)\b",
    "best friend": r"\b(best friend|buddy|best bud)\b",
    "brother's friend / friend's brother": r"\b(brother'?s friend|friend'?s brother)\b",
    "roommate": r"\b(roommate|flatmate)\b",
    "stranger": r"\b(stranger|unknown man)\b",
    "mentor / older man": r"\b(older man|mentor|dad'?s friend|uncle)\b",
}

DYNAMIC_PATTERNS = {
    "voyeur": r"\b(voyeur|watched|watching|peek(ing|ed)?|spied)\b",
    "exhibition": r"\b(exhibit|public|risk of being caught|out in the open)\b",
    "first time": r"\b(first time|virgin|never (been|done) (with|this) (a )?(guy|man|another))\b",
    "cheating": r"\b(cheat(ing|ed)?|affair|behind .* back)\b",
    "hookup": r"\b(hookup|one night|one-night|casual)\b",
    "reunion": r"\b(reunion|years later|ten years|back in town)\b",
    "slow burn": r"\b(months|weeks of|slow|gradually|tentative)\b",
}

CATEGORY_ALIASES = {  # nifty directory -> readable topic
    "athletics": "sports", "college": "college", "encounters": "casual encounters",
    "beginnings": "first time", "young-friends": "young friends", "adult-friends": "adult friends",
    "military": "military", "authoritarian": "authority", "gaymale": "general",
    "incest": "family taboo", "highschool": "school days", "rural": "rural",
    "camping": "outdoors", "celebrity": "celebrity", "urination": "watersports",
    "bisexual": "bisexual", "science-fiction": "sci-fi", "sf-fantasy": "sci-fi-fantasy",
    "historical": "historical", "masturbation": "solo", "administration": "authority",
}

ENTITY_TYPES = ("setting", "character", "dynamic")


def extract_entities(title: str, preview: str, category: str = "") -> Dict[str, List[str]]:
    text = f"{title}\n{preview}".lower()[:6000]
    out: Dict[str, List[str]] = {"setting": [], "character": [], "dynamic": []}
    for label, pattern in SETTING_PATTERNS.items():
        if re.search(pattern, text):
            out["setting"].append(label)
    for label, pattern in CHARACTER_PATTERNS.items():
        if re.search(pattern, text):
            out["character"].append(label)
    for label, pattern in DYNAMIC_PATTERNS.items():
        if re.search(pattern, text):
            out["dynamic"].append(label)
    if category:
        alias = CATEGORY_ALIASES.get(category.lower())
        if alias:
            out["topic"] = [alias]
    return out


def build_entities(db_path: str, batch_size: int = 5000) -> int:
    """Extract entities for all canonical safety-passing stories; idempotent."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS entity_mentions")
        conn.execute("""CREATE TABLE entity_mentions (
            story_id INTEGER NOT NULL,
            etype TEXT NOT NULL,
            label TEXT NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_label "
                     "ON entity_mentions(etype, label)")
        cur = conn.execute(
            "SELECT id, title, category, preview FROM stories "
            "WHERE is_canonical=1 AND safety_verdict='PASS'")
        batch: List[Tuple[int, str, str]] = []
        total = 0
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            batch = []
            for sid, title, category, preview in rows:
                ents = extract_entities(title or "", preview or "", category or "")
                for etype, labels in ents.items():
                    for label in labels:
                        batch.append((sid, etype, label))
            conn.executemany("INSERT INTO entity_mentions (story_id, etype, label) "
                             "VALUES (?,?,?)", batch)
            conn.commit()
            total += len(batch)
        return total
    finally:
        conn.close()


SCOPE_JOIN = ("JOIN stories s ON s.id = m.story_id AND s.is_canonical=1 "
              "AND s.safety_verdict='PASS'")


def facet_counts(db_path: str, etype: str, filters: Optional[Dict[str, List[str]]] = None,
                 limit: int = 40) -> List[Tuple[str, int]]:
    """Counts for one entity type, optionally constrained by other facets."""
    conn = sqlite3.connect(db_path)
    try:
        args: List[Any] = []
        where = ""
        for other_type, labels in (filters or {}).items():
            if not labels:
                continue
            for label in labels:
                where += (f" AND s.id IN (SELECT story_id FROM entity_mentions m2 "
                          f"WHERE m2.etype=? AND m2.label=?)")
                args.extend([other_type, label])
        rows = conn.execute(
            f"SELECT m.label, count(*) FROM entity_mentions m {SCOPE_JOIN} "
            f"WHERE m.etype=?{where} GROUP BY m.label ORDER BY count(*) DESC LIMIT ?",
            [etype, *args, limit]).fetchall()
        return rows
    finally:
        conn.close()


def combo_search(db_path: str, filters: Dict[str, List[str]], extra_where: str = "",
                 args: tuple = (), limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """Stories matching ALL selected facet labels + optional SQL conditions."""
    conn = sqlite3.connect(db_path)
    try:
        where_parts = ["s.is_canonical=1", "s.safety_verdict='PASS'"]
        params: List[Any] = list(args)
        for etype, labels in filters.items():
            for label in labels:
                where_parts.append(
                    "s.id IN (SELECT story_id FROM entity_mentions m "
                    "WHERE m.etype=? AND m.label=?)")
                params.extend([etype, label])
        if extra_where:
            where_parts.append(extra_where)
        sql = (f"SELECT s.id, s.title, s.author, s.category, s.publication_date, "
               f"s.word_count, s.quality_total, s.quality_tier, s.tropes, s.preview "
               f"FROM stories s WHERE {' AND '.join(where_parts)} "
               "ORDER BY s.quality_total DESC LIMIT ? OFFSET ?")
        rows = conn.execute(sql, [*params, limit, offset]).fetchall()
        cols = ["id", "title", "author", "category", "year", "words",
                "quality", "tier", "tropes", "preview"]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def combo_count(db_path: str, filters: Dict[str, List[str]],
                extra_where: str = "", args: tuple = ()) -> int:
    conn = sqlite3.connect(db_path)
    try:
        where_parts = ["s.is_canonical=1", "s.safety_verdict='PASS'"]
        params: List[Any] = list(args)
        for etype, labels in filters.items():
            for label in labels:
                where_parts.append(
                    "s.id IN (SELECT story_id FROM entity_mentions m "
                    "WHERE m.etype=? AND m.label=?)")
                params.extend([etype, label])
        if extra_where:
            where_parts.append(extra_where)
        return conn.execute(
            f"SELECT count(*) FROM stories s WHERE {' AND '.join(where_parts)}",
            params).fetchone()[0]
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> None:
    import argparse
    p = argparse.ArgumentParser(description="NER extraction (JGF-12)")
    p.add_argument("--db", required=True)
    args = p.parse_args(argv)
    total = build_entities(args.db)
    print(json.dumps({"entity_mentions": total}, indent=1))


if __name__ == "__main__":
    main()
