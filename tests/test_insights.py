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


def test_strip_boilerplate_removes_chrome_keeps_prose():
    from insights.semantic import strip_boilerplate
    raw = ("From e0011@telly.on.ca\nCopyright 2004. All rights reserved.\n"
           "Please donate to nifty.org.\n\nHe walked into the bar and saw the jock.")
    out = strip_boilerplate(raw)
    assert "nifty.org" not in out and "Copyright" not in out and "@" not in out
    assert "walked into the bar" in out


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


# ---------------------------------------------------------------------------
# Failure handling: a broken row must fail the run, not silently vanish
# ---------------------------------------------------------------------------

def _failing_csv(tmp_path, n=3):
    rows = [(f"Story {i}", BASE_LONG, "college", "2000-01-01") for i in range(1, n + 1)]
    path = tmp_path / "fail.csv"
    _write_csv(path, rows)
    return str(path)


def _count(db, sql="SELECT count(*) FROM stories"):
    """Run a scalar query and close the connection (avoids ResourceWarning)."""
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def _ids(db):
    conn = sqlite3.connect(db)
    try:
        return {r[0] for r in conn.execute("SELECT id FROM stories")}
    finally:
        conn.close()


def test_error_signature_groups_by_cause():
    # Messages differing only by row id / offset must collapse to one signature,
    # otherwise the "distinct failure types" count is meaningless.
    a = corpus_prep.error_signature("bad character range 3-2 at position 1992")
    b = corpus_prep.error_signature("bad character range 3-2 at position 55")
    c = corpus_prep.error_signature("KeyError: 'content'")
    assert a == b
    assert a != c


def test_ingest_reports_errors_and_blocks_checkpoint(tmp_path, monkeypatch):
    """A row that raises must be counted, reported, and NOT skipped."""
    csv_path = _failing_csv(tmp_path)
    db = str(tmp_path / "fail.sqlite")

    def boom(row):
        raise ValueError("simulated per-row failure")

    monkeypatch.setattr(corpus_prep, "process_row", boom)
    ing = FullCorpusIngester(db, db + ".state")
    result = ing.ingest(csv_path, workers=1)

    assert result["total_errors"] == 3
    assert result["processed"] == 0
    assert result["blocked_batches"] >= 1
    # the distinct-cause summary must name the failure, not just count it
    assert any("simulated per-row failure" in k for k in result["error_types"])
    assert result["unprocessed_ids"] == ["1", "2", "3"]
    # checkpoint must not have advanced past the failed rows
    assert ing.last_offset == 0
    assert _count(db) == 0


def test_failed_rows_are_retried_not_skipped(tmp_path, monkeypatch):
    """The core regression: a transient failure must not lose rows forever."""
    csv_path = _failing_csv(tmp_path)
    db = str(tmp_path / "retry.sqlite")

    def boom(row):
        raise ValueError("transient failure")

    monkeypatch.setattr(corpus_prep, "process_row", boom)
    FullCorpusIngester(db, db + ".state").ingest(csv_path, workers=1)
    assert _count(db) == 0

    # Second run with the bug fixed must process every row, not skip them.
    monkeypatch.undo()
    result = FullCorpusIngester(db, db + ".state").ingest(csv_path, workers=1)
    assert result["total_errors"] == 0
    assert result["processed"] == 3
    assert _count(db) == 3


def test_main_exits_nonzero_on_errors(tmp_path, monkeypatch, capsys):
    csv_path = _failing_csv(tmp_path)
    db = str(tmp_path / "exit.sqlite")

    def boom(row):
        raise ValueError("simulated per-row failure")

    monkeypatch.setattr(corpus_prep, "process_row", boom)
    with pytest.raises(SystemExit) as exc:
        corpus_prep.main(["--csv", csv_path, "--db", db, "--workers", "1"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "distinct failure types" in out
    assert "simulated per-row failure" in out


def test_main_exits_zero_on_clean_run(tmp_path):
    csv_path = _failing_csv(tmp_path)
    db = str(tmp_path / "clean.sqlite")
    corpus_prep.main(["--csv", csv_path, "--db", db, "--workers", "1"])
    with open(db + ".ingest_result.json") as f:
        result = json.load(f)
    assert result["total_errors"] == 0
    assert result["processed"] == 3


def test_allow_errors_flag_keeps_exit_zero(tmp_path, monkeypatch):
    csv_path = _failing_csv(tmp_path)
    db = str(tmp_path / "allow.sqlite")

    def boom(row):
        raise ValueError("simulated per-row failure")

    monkeypatch.setattr(corpus_prep, "process_row", boom)
    corpus_prep.main(["--csv", csv_path, "--db", db, "--workers", "1",
                      "--allow-errors"])
    with open(db + ".ingest_result.json") as f:
        result = json.load(f)
    assert result["total_errors"] == 3


def test_first_batch_failure_blocks_later_successful_batches(tmp_path, monkeypatch):
    """Regression: one failed batch must hold the checkpoint for the whole run.

    A batch that fails *after* a batch that succeeded must not use the later
    success to advance last_offset past the failed rows.
    """
    rows = [(f"Story {i}", BASE_LONG, "college", "2000-01-01") for i in range(1, 5)]
    csv_path = tmp_path / "mixed.csv"
    _write_csv(csv_path, rows)
    db = str(tmp_path / "mixed.sqlite")

    # Patch the batch size down so each row is its own batch.
    monkeypatch.setattr(corpus_prep, "BATCH_ROWS", 1)

    real_process_row = corpus_prep.process_row
    calls = {"n": 0}

    def flaky(row):
        calls["n"] += 1
        if calls["n"] == 2:  # second row fails; rows 3 and 4 succeed
            raise ValueError("flaky row 2")
        return real_process_row(row)

    monkeypatch.setattr(corpus_prep, "process_row", flaky)
    ing = corpus_prep.FullCorpusIngester(db, db + ".state")
    result = ing.ingest(csv_path, workers=1)

    assert result["total_errors"] == 1
    assert result["processed"] == 3
    # The checkpoint may advance past rows that succeeded, but must never reach
    # the end of the file, which would skip the failed row on the next run.
    assert ing.last_offset < os.path.getsize(csv_path)
    # row 2 is the one that failed, so it must be absent after this run
    ids = _ids(db)
    assert 2 not in ids, ids

    # retry with the flake gone must recover the missing row
    monkeypatch.undo()
    result2 = corpus_prep.FullCorpusIngester(db, db + ".state").ingest(csv_path, workers=1)
    assert result2["total_errors"] == 0
    ids = _ids(db)
    assert ids == {1, 2, 3, 4}, ids


def test_error_signature_set_is_bounded(tmp_path, monkeypatch):
    """A varying error message must not grow the report without limit."""
    csv_path = _failing_csv(tmp_path, n=5)
    db = str(tmp_path / "bounded.sqlite")
    counter = {"n": 0}

    def boom(row):
        counter["n"] += 1
        raise ValueError(f"unique failure {counter['n']}")

    monkeypatch.setattr(corpus_prep, "process_row", boom)
    ing = FullCorpusIngester(db, db + ".state")
    result = ing.ingest(csv_path, workers=1)
    assert result["total_errors"] == 5
    # digits are normalised away, so all five collapse to a single signature
    assert len(result["error_types"]) == 1


# ---------------------------------------------------------------------------
# Regex configuration guard
# ---------------------------------------------------------------------------

def test_profiler_patterns_are_valid_at_import():
    from pipeline import profiler
    profiler.validate_patterns()  # must not raise


def test_profiler_guard_rejects_empty_rule_list(monkeypatch):
    from pipeline import profiler
    monkeypatch.setitem(profiler.REGEX_PATTERNS, "EMPTY", [])
    with pytest.raises(RuntimeError, match="EMPTY is empty"):
        profiler.validate_patterns()


def test_profiler_guard_rejects_non_pattern(monkeypatch):
    from pipeline import profiler
    monkeypatch.setitem(profiler.REGEX_PATTERNS, "BOGUS", ["not a pattern"])
    with pytest.raises(RuntimeError, match="not a compiled pattern"):
        profiler.validate_patterns()


def test_no_regex_is_compiled_inside_a_function():
    """Guard the property that makes a bad regex fail loudly.

    Patterns compiled inside a function raise per row, where ``process_rows``
    absorbs them; the run then reports success having processed nothing.
    """
    import ast
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for sub in ("pipeline", "insights", "parse"):
        for dirpath, _, filenames in os.walk(os.path.join(root, sub)):
            if "__pycache__" in dirpath:
                continue
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    for inner in ast.walk(node):
                        if (isinstance(inner, ast.Call)
                                and isinstance(inner.func, ast.Attribute)
                                and inner.func.attr == "compile"
                                and isinstance(inner.func.value, ast.Name)
                                and inner.func.value.id == "re"):
                            offenders.append(f"{path}:{inner.lineno} in {node.name}()")
    assert not offenders, (
        "re.compile() must stay at module scope so a bad pattern fails at "
        "import instead of being swallowed per row:\n  " + "\n  ".join(offenders))
