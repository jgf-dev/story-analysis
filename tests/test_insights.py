"""Tests for the JGF-12 insight platform (insights/*)."""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from insights import analysis, corpus_prep, ner
from insights.corpus_prep import (
    BandedDeduper, FullCorpusIngester, minhash_signature, signature_similarity,
    normalized_hash, process_row, process_rows, process_batch,
)


# ---------------------------------------------------------------------------
# Synthetic corpus
# ---------------------------------------------------------------------------

# High-cardinality synthetic stories so k-shingle Jaccard is well estimated.
_BASE_WORDS = " ".join(f"alpha{i:04d}" for i in range(420))
_VARIANT_WORDS = _BASE_WORDS + " " + " ".join(f"omega{i:04d}" for i in range(25))
_DISTINCT_WORDS = " ".join(f"beta{i:04d}" for i in range(420))
BASE = _BASE_WORDS + "."
BASE_LONG = _BASE_WORDS
VARIANT_LONG = _VARIANT_WORDS
DISTINCT = _DISTINCT_WORDS


def _write_csv(path, rows):
    cols = ["id", "path", "orientation", "category", "story_slug", "chapter_num",
            "title", "author_name", "author_email", "publication_date", "url",
            "char_count", "word_count", "content", "created_at", "date_source"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i, (title, content, category, date) in enumerate(rows, start=1):
            w.writerow([i, f"gay/{category}/s{i}.txt", "gay", category, f"s{i}", "",
                        title, "Unknown", "", date, f"https://nifty.org/x/{i}",
                        len(content), len(content.split()), content, date, "test"])


@pytest.fixture()
def catalog(tmp_path):
    rows = [
        ("Working on My Lunge", BASE_LONG, "athletics", "1992-05-01"),
        ("Working on My Lunge (repost)", VARIANT_LONG, "athletics", "1993-01-01"),
        ("The Professor's Lesson", DISTINCT, "college", "1998-03-04"),
        ("A Cabin Weekend", DISTINCT + " " + BASE_LONG, "rural", "2001-07-09"),
    ]
    csv_path = tmp_path / "input.csv"
    _write_csv(csv_path, rows)
    db = tmp_path / "cat.sqlite"
    ing = FullCorpusIngester(str(db), str(db) + ".state")
    ing.ingest(str(csv_path), workers=1)
    return str(db)


# ---------------------------------------------------------------------------
# MinHash / dedup
# ---------------------------------------------------------------------------

def test_minhash_identical_and_distinct():
    a = "the quick brown fox jumps over the lazy dog " * 20
    b = a
    c = "completely different words about sailing and astronomy " * 20
    sa, sb, sc = minhash_signature(a), minhash_signature(b), minhash_signature(c)
    assert signature_similarity(sa, sb) == 1.0
    assert signature_similarity(sa, sc) < 0.3


def test_minhash_estimates_true_jaccard():
    import re
    words_a = re.findall(r"\b\w+\b", BASE_LONG.lower())
    words_b = re.findall(r"\b\w+\b", VARIANT_LONG.lower())
    k = 5
    sh_a = {tuple(words_a[i:i + k]) for i in range(len(words_a) - k + 1)}
    sh_b = {tuple(words_b[i:i + k]) for i in range(len(words_b) - k + 1)}
    true_j = len(sh_a & sh_b) / len(sh_a | sh_b)
    est = signature_similarity(minhash_signature(BASE_LONG), minhash_signature(VARIANT_LONG))
    assert abs(est - true_j) < 0.12, (est, true_j)


def test_near_duplicate_detected():
    d = BandedDeduper(near_dup_threshold=0.7)
    sig_a = minhash_signature(BASE_LONG)
    d.add_exact(normalized_hash(BASE_LONG), 1)
    d.register_canonical(1, sig_a)
    sig_b = minhash_signature(VARIANT_LONG)
    assert d.find_duplicate(normalized_hash(VARIANT_LONG), sig_b) == 1


def test_exact_duplicate_detected():
    d = BandedDeduper()
    sig = minhash_signature(BASE)
    d.add_exact(normalized_hash(BASE), 7)
    d.register_canonical(7, sig)
    assert d.find_duplicate(normalized_hash(BASE), sig) == 7


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def test_ingest_writes_catalog(catalog):
    c = sqlite3.connect(catalog)
    total = c.execute("SELECT count(*) FROM stories").fetchone()[0]
    canonical = c.execute("SELECT count(*) FROM stories WHERE is_canonical=1").fetchone()[0]
    assert total == 4
    assert 1 <= canonical <= 4
    # repost of the same story should be marked duplicate
    dup = c.execute("SELECT count(*) FROM stories WHERE dup_of IS NOT NULL").fetchone()[0]
    assert dup >= 1
    c.close()


def test_resume_is_idempotent(tmp_path, catalog):
    # re-running over the same csv must not duplicate rows
    before = sqlite3.connect(catalog).execute("SELECT count(*) FROM stories").fetchone()[0]
    csv_path = tmp_path / "input.csv"
    db = catalog
    ing = FullCorpusIngester(db, db + ".state")
    ing.ingest(str(csv_path), workers=1)
    after = sqlite3.connect(db).execute("SELECT count(*) FROM stories").fetchone()[0]
    assert after == before


def test_resume_midfile_multiline_rows(tmp_path):
    # Regression: resume must seek to a record boundary without skipping the
    # first line of the next (possibly multi-line) CSV record.
    rows = [(f"Story {i}", "First paragraph line.\n\nSecond paragraph here.\n\nThird.",
             "college", "2000-01-01") for i in range(1, 7)]
    csv_path = tmp_path / "multi.csv"
    _write_csv(csv_path, rows)
    db = tmp_path / "multi.sqlite"
    FullCorpusIngester(str(db), str(db) + ".state").ingest(str(csv_path), workers=1, limit=2)
    assert sqlite3.connect(db).execute("SELECT count(*) FROM stories").fetchone()[0] == 2

    FullCorpusIngester(str(db), str(db) + ".state").ingest(str(csv_path), workers=1)
    c = sqlite3.connect(db)
    ids = [r[0] for r in c.execute("SELECT id FROM stories ORDER BY id")]
    titles = [r[0] for r in c.execute("SELECT title FROM stories ORDER BY id")]
    c.close()
    assert ids == [1, 2, 3, 4, 5, 6], ids
    assert titles == [f"Story {i}" for i in range(1, 7)], titles


def test_process_row_extracts_metadata():
    row = {"id": "1", "content": BASE * 2, "title": "Bar Story", "author_name": "",
           "category": "encounters", "orientation": "gay", "word_count": "100",
           "publication_date": "1995-01-01", "path": "gay/encounters/x", "url": "u",
           "story_slug": "bar-story", "char_count": "500"}
    s = process_row(row)
    assert s["title"] == "Bar Story"
    assert s["author"] == "Unknown / Anonymous"
    assert s["metrics"]["word_count"] > 0
    assert s["quality"]["tier"]
    assert isinstance(s["taxonomy"]["tropes"], list)


def test_process_batch_splits_across_workers_and_preserves_order():
    from multiprocessing import get_context
    rows = [{"id": str(i), "content": (BASE + " " + DISTINCT) * (i % 3 + 1),
             "title": f"T{i}", "author_name": "", "category": "college",
             "orientation": "gay", "word_count": "100", "publication_date": "2000-01-01",
             "path": "gay/college/x", "url": "u", "story_slug": f"t{i}", "char_count": "500"}
            for i in range(7)]
    seq = process_rows(rows)
    ctx = get_context("fork")
    pool = ctx.Pool(processes=2)
    try:
        par = process_batch(pool, rows)
    finally:
        pool.close()
        pool.join()
    assert [s["id"] for s in par] == [s["id"] for s in seq]
    assert [s["title"] for s in par] == [s["title"] for s in seq]
    assert [s["quality"]["tier"] for s in par] == [s["quality"]["tier"] for s in seq]


# ---------------------------------------------------------------------------
# Analysis / NER
# ---------------------------------------------------------------------------

def test_analysis_summary(catalog):
    out = analysis.run_analysis(catalog, os.path.join(os.path.dirname(catalog), "an"))
    s = out["summary"]
    assert s["total_rows"] == 4
    assert s["canonical_stories"] >= 1
    assert "category" in out["distributions"]


def test_ner_build_and_combo(catalog):
    total = ner.build_entities(catalog)
    assert total >= 0
    counts = ner.facet_counts(catalog, "setting")
    # combo query must not error and returns a list
    rows = ner.combo_search(catalog, {"character": ["stranger"]})
    assert isinstance(rows, list)


def test_entities_extraction():
    ents = ner.extract_entities("Locker Room Heat", "The jock entered the gym. A stranger watched.")
    assert "locker room / gym" in ents["setting"]
    assert "jock / athlete" in ents["character"]


# ---------------------------------------------------------------------------
# UI smoke
# ---------------------------------------------------------------------------

def test_ui_smoke(catalog, tmp_path):
    from insights.ui import create_app
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)
    app = create_app(catalog, out_dir)
    client = app.test_client()
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/combo").status_code == 200
    resp = client.get("/story/1")
    assert resp.status_code == 200
