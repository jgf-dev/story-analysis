"""Streaming full-corpus ingestion for the insight platform.

Reads the 18.78 GB `stories_clean.csv` export with bounded memory, runs the
JGF-4 per-story pipeline (clean -> safety -> metrics -> quality -> tags ->
TTS metadata), then applies global exact + near-duplicate deduplication
(numpy-vectorized MinHash signatures with banded LSH) and writes a compact
SQLite catalog.

Design constraints (JGF-12):
- Memory bounded: story batches are processed and released; signatures are
  stored as uint32 arrays; full text is zlib-compressed blobs only for
  canonical, safety-passing Tier 1/2 stories.
- Resumable: `ingest_state.json` stores the CSV byte offset and row count;
  dedup state is rebuilt from the DB on resume.
- Deterministic: fixed hash coefficients, no RNG.

Never point this module at anything except the local copy of the internal
dataset; the download URL must not be committed or logged anywhere.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
import time
import zlib
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

csv.field_size_limit(64 * 1024 * 1024)  # story fields exceed the 128KB default

from pipeline.profiler import StoryProfiler
from pipeline.quality import StoryQualityScorer
from pipeline.tagging import StoryTaxonomyTagger
from pipeline.tts_prioritizer import TTSPrioritizer
from pipeline.schemas import SafetyVerdict, QualityTier, HeatLevel

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

NUM_PERMUTATIONS = 128          # MinHash permutations
BAND_ROWS = 4                   # rows per LSH band
BANDS = NUM_PERMUTATIONS // BAND_ROWS
MINHASH_SOURCE_CHARS = 30_000   # signature source: first N cleaned chars
SHINGLE_K = 5                   # word k-shingles
NEAR_DUP_THRESHOLD = 0.80       # signature similarity for near-duplicate
BATCH_ROWS = 300                # rows per work unit
COMMIT_ROWS = 5_000             # SQLite commit interval
PREVIEW_CHARS = 8_000           # stored preview length for all stories
KEEP_FULL_TEXT_MAX_CHARS = 400_000  # cap on stored full text (defensive)

# 32-bit Mersenne prime coefficients for MinHash (fixed for reproducibility).
# Coefficients and shingle hashes are kept <= 2^31 so a*b fits in uint64
# without overflow (an overflow here biases every permutation identically).
_PRIME31 = (1 << 31) - 1


def _coeff(seed: int) -> int:
    x = (seed * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9 & ((1 << 64) - 1)
    x = (x ^ (x >> 27)) * 0x94d049bb133111eb & ((1 << 64) - 1)
    x ^= x >> 31
    return (x % (_PRIME31 - 1)) + 1


_COEFF_A = np.array([_coeff(i * 2 + 1) for i in range(1, NUM_PERMUTATIONS + 1)], dtype=np.uint64)
_COEFF_B = np.array([_coeff(i * 2 + 2) for i in range(1, NUM_PERMUTATIONS + 1)], dtype=np.uint64)


def _mix64(x: np.ndarray) -> np.ndarray:
    x = x ^ (x >> np.uint64(30))
    x = x * np.uint64(0xbf58476d1ce4e5b9)
    x = x ^ (x >> np.uint64(27))
    x = x * np.uint64(0x94d049bb133111eb)
    x = x ^ (x >> np.uint64(31))
    return x


# ---------------------------------------------------------------------------
# MinHash + banded LSH
# ---------------------------------------------------------------------------

_WORD_CACHE: Dict[str, int] = {}


def _word_id(word: str) -> int:
    wid = _WORD_CACHE.get(word)
    if wid is None:
        wid = int.from_bytes(hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest(), "little")
        if len(_WORD_CACHE) < 3_000_000:
            _WORD_CACHE[word] = wid
    return wid


def _shingle_hashes(text: str) -> np.ndarray:
    """Word k-shingles hashed to well-distributed uint64 ids (deterministic)."""
    words = text.split()
    if len(words) < SHINGLE_K:
        if not words:
            return np.zeros(0, dtype=np.uint64)
        joined = " ".join(words).encode("utf-8")
        return np.array([int.from_bytes(hashlib.blake2b(joined, digest_size=8).digest(), "little")],
                        dtype=np.uint64)
    # Hash each word once (cached), then combine positionally (rolling shingle).
    word_hashes = np.array([_word_id(w) for w in words], dtype=np.uint64)
    base = np.uint64(1_000_003)
    rolling = np.zeros(len(words) - SHINGLE_K + 1, dtype=np.uint64)
    for off in range(SHINGLE_K):
        wh = word_hashes[off: off + len(rolling)]
        rolling = rolling * base + wh
    return _mix64(rolling)


def minhash_signature(text: str) -> np.ndarray:
    """128-dim MinHash signature of the first MINHASH_SOURCE_CHARS of text."""
    shingles = _shingle_hashes(text[:MINHASH_SOURCE_CHARS])
    if shingles.size == 0:
        return np.zeros(NUM_PERMUTATIONS, dtype=np.uint32)
    h = shingles % np.uint64(_PRIME31)
    # (A[:, None] * h[None, :] + B[:, None]) % PRIME31 -> min over shingles.
    # A, B, h < 2^31 so the product fits uint64 without overflow.
    vals = (np.multiply.outer(_COEFF_A, h) + _COEFF_B[:, None]) % np.uint64(_PRIME31)
    sig = vals.min(axis=1).astype(np.uint32)
    return sig


def signature_similarity(sig_a: np.ndarray, sig_b: np.ndarray) -> float:
    """Fraction of equal permutation slots — unbiased Jaccard estimate."""
    if sig_a is None or sig_b is None or sig_a.size == 0:
        return 0.0
    return float(np.mean(sig_a == sig_b))


def band_keys(sig: np.ndarray) -> List[int]:
    """Banded LSH keys: hash of each consecutive BAND_ROWS signature slots."""
    keys = []
    for b in range(BANDS):
        chunk = sig[b * BAND_ROWS:(b + 1) * BAND_ROWS]
        keys.append(int.from_bytes(chunk.tobytes(), "little") & ((1 << 62) - 1))
    return keys


class BandedDeduper:
    """Global exact + near-duplicate dedup with banded MinHash LSH."""

    def __init__(self, near_dup_threshold: float = NEAR_DUP_THRESHOLD):
        self.threshold = near_dup_threshold
        self.exact_map: Dict[str, int] = {}          # normalized sha256 -> story id
        self.sigs: Dict[int, np.ndarray] = {}        # canonical id -> signature
        self.buckets: List[Dict[int, List[int]]] = [{} for _ in range(BANDS)]

    def add_exact(self, norm_hash: str, story_id: int) -> None:
        self.exact_map[norm_hash] = story_id

    def register_canonical(self, story_id: int, sig: np.ndarray) -> None:
        self.sigs[story_id] = sig
        for band, key in enumerate(band_keys(sig)):
            self.buckets[band].setdefault(key, []).append(story_id)

    def find_duplicate(self, norm_hash: str, sig: np.ndarray) -> Optional[int]:
        """Return canonical story id this row duplicates, else None."""
        if norm_hash in self.exact_map:
            return self.exact_map[norm_hash]
        seen: set = set()
        for band, key in enumerate(band_keys(sig)):
            for cand in self.buckets[band].get(key, ()):
                if cand in seen:
                    continue
                seen.add(cand)
                if signature_similarity(sig, self.sigs[cand]) >= self.threshold:
                    return cand
        return None

    def state_size(self) -> int:
        return len(self.exact_map)


def normalized_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Per-row processing (worker payload)
# ---------------------------------------------------------------------------

_PROFILER = StoryProfiler()
_SCORER = StoryQualityScorer()
_TAGGER = StoryTaxonomyTagger()
_TTS = TTSPrioritizer()


def process_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Run the JGF-4 per-story pipeline on one CSV row (no dedup yet)."""
    content = row.get("content") or ""
    title = (row.get("title") or "").strip()
    if not title or title.lower() in ("unknown", "untitled story", "untitled"):
        slug = (row.get("story_slug") or "").replace("-", " ").title()
        title = slug if slug else "Untitled Story"
    author = (row.get("author_name") or "").strip()
    if not author or author.lower() in ("unknown", "unknown / anonymous", "anonymous"):
        author = "Unknown / Anonymous"

    header_title, header_author = StoryProfiler.extract_metadata_from_headers(
        content[:4000], default_title=title, default_author=author
    )
    if header_title:
        title = header_title
    if header_author and author == "Unknown / Anonymous":
        author = header_author

    tags = []
    if row.get("orientation"):
        tags.append(row["orientation"])
    if row.get("category"):
        tags.append(row["category"])

    clean = _PROFILER.clean_text(content, header_scan_chars=3000)
    safety = _PROFILER.audit_safety(clean, tags)
    metrics = _PROFILER.calculate_text_metrics(clean, density_scan_chars=15000)
    quality = _SCORER.evaluate(clean, metrics)
    taxonomy = _TAGGER.tag_story(clean[:8000], title, tags, metrics)
    tts_meta = _TTS.generate_tts_metadata(
        story_text=clean,
        quality_score=quality.total_score,
        dialogue_ratio=metrics["dialogue_ratio"],
        word_count=metrics["word_count"],
        archetypes=taxonomy.character_archetypes,
    )
    return {
        "id": int(row["id"]) if str(row.get("id", "")).strip().isdigit() else str(row.get("id")),
        "title": title,
        "author": author,
        "category": row.get("category") or "",
        "orientation": row.get("orientation") or "",
        "path": row.get("path") or "",
        "publication_date": row.get("publication_date") or "",
        "url": row.get("url") or "",
        "raw_word_count": int(row.get("word_count") or 0),
        "clean_text": clean,
        "metrics": metrics,
        "safety": safety.verdict.value,
        "safety_terms": list(safety.flagged_terms),
        "quality": {
            "formatting": quality.formatting_cleanliness,
            "structural": quality.structural_arc,
            "prose": quality.prose_richness,
            "dialogue": quality.dialogue_pacing,
            "tts": quality.tts_readability,
            "total": quality.total_score,
            "tier": quality.tier.value,
            "penalties": quality.penalties,
        },
        "taxonomy": {
            "tropes": taxonomy.primary_tropes,
            "archetypes": taxonomy.character_archetypes,
            "settings": taxonomy.setting,
            "heat": taxonomy.heat_level.value,
            "pov": taxonomy.point_of_view,
            "pacing": taxonomy.pacing,
            "duration_tier": taxonomy.duration_tier.value,
        },
        "tts_minutes": tts_meta.estimated_duration_min,
    }


def process_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Worker entry: run the per-story pipeline on a batch of CSV rows."""
    out = []
    for row in rows:
        try:
            out.append(process_row(row))
        except Exception as exc:  # surfaced by the writer for stats
            out.append({"__error__": f"{type(exc).__name__}: {exc}",
                        "id": row.get("id", "?")})
    return out


def process_batch(pool, raw_batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Process a batch, splitting it across workers for real parallelism.

    ``pool.map(func, (raw_batch,))`` submits the whole batch as a single task
    and therefore runs on one worker only (the rest idle). Split the batch into
    one contiguous chunk per process so every worker participates while
    preserving the original row order.
    """
    if pool is None:
        return process_rows(raw_batch)
    n_workers = max(1, getattr(pool, "_processes", 1) or 1)
    if n_workers == 1 or len(raw_batch) <= 1:
        return pool.map(process_rows, (raw_batch,))[0]
    chunk_size = (len(raw_batch) + n_workers - 1) // n_workers
    chunks = [raw_batch[i:i + chunk_size]
              for i in range(0, len(raw_batch), chunk_size)]
    out: List[Dict[str, Any]] = []
    for part in pool.map(process_rows, chunks):
        out.extend(part)
    return out


def _norm_text_for_hash(clean_text: str) -> str:
    return clean_text[:200_000]


# ---------------------------------------------------------------------------
# SQLite catalog
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT,
  category TEXT,
  orientation TEXT,
  path TEXT,
  publication_date TEXT,
  url TEXT,
  raw_word_count INTEGER,
  word_count INTEGER,
  char_count INTEGER,
  paragraph_count INTEGER,
  avg_sentence_len REAL,
  dialogue_ratio REAL,
  ttr REAL,
  sensory_density REAL,
  explicit_density REAL,
  safety_verdict TEXT,
  safety_terms TEXT,
  quality_formatting REAL, quality_structural REAL, quality_prose REAL,
  quality_dialogue REAL, quality_tts REAL, quality_total REAL,
  quality_tier TEXT, quality_penalties TEXT,
  tropes TEXT, archetypes TEXT, settings TEXT,
  heat_level INTEGER, pov TEXT, pacing TEXT, duration_tier TEXT,
  tts_minutes REAL,
  exact_hash TEXT,
  sig BLOB,
  is_canonical INTEGER DEFAULT 1,
  dup_of INTEGER,
  preview TEXT
);
CREATE INDEX IF NOT EXISTS idx_stories_tier ON stories(quality_tier);
CREATE INDEX IF NOT EXISTS idx_stories_category ON stories(category);
CREATE INDEX IF NOT EXISTS idx_stories_date ON stories(publication_date);
CREATE INDEX IF NOT EXISTS idx_stories_safety ON stories(safety_verdict);
CREATE TABLE IF NOT EXISTS story_text (
  id INTEGER PRIMARY KEY,
  full_text BLOB
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


INSERT_SQL = """INSERT INTO stories (
  id, title, author, category, orientation, path, publication_date, url,
  raw_word_count, word_count, char_count, paragraph_count, avg_sentence_len,
  dialogue_ratio, ttr, sensory_density, explicit_density,
  safety_verdict, safety_terms,
  quality_formatting, quality_structural, quality_prose, quality_dialogue,
  quality_tts, quality_total, quality_tier, quality_penalties,
  tropes, archetypes, settings, heat_level, pov, pacing, duration_tier,
  tts_minutes, exact_hash, sig, is_canonical, dup_of, preview
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def story_row(story: Dict[str, Any], is_canonical: bool, dup_of: Optional[int],
              sig: Optional[bytes], norm_hash: str) -> Tuple:
    m = story["metrics"]
    q = story["quality"]
    t = story["taxonomy"]
    text = story["clean_text"]
    return (
        story["id"], story["title"], story["author"], story["category"],
        story["orientation"], story["path"], story["publication_date"], story["url"],
        story["raw_word_count"], m["word_count"], m["char_count"], m["paragraph_count"],
        m["avg_sentence_len"], m["dialogue_ratio"], m["ttr"], m["sensory_density"],
        m["explicit_density"],
        story["safety"], json.dumps(story["safety_terms"]),
        q["formatting"], q["structural"], q["prose"], q["dialogue"], q["tts"],
        q["total"], q["tier"], json.dumps(q["penalties"]),
        json.dumps(t["tropes"]), json.dumps(t["archetypes"]), json.dumps(t["settings"]),
        t["heat"], t["pov"], t["pacing"], t["duration_tier"],
        story["tts_minutes"], norm_hash, sig, 1 if is_canonical else 0, dup_of,
        text[:PREVIEW_CHARS],
    )


# ---------------------------------------------------------------------------
# Main ingester
# ---------------------------------------------------------------------------

class FullCorpusIngester:
    def __init__(self, db_path: str, state_path: str,
                 near_dup_threshold: float = NEAR_DUP_THRESHOLD):
        self.db_path = db_path
        self.state_path = state_path
        self.conn = open_db(db_path)
        self.deduper = BandedDeduper(near_dup_threshold)
        self.rows_done = 0
        self.last_offset = 0
        self._cur_offset = 0
        self._seen_ids: set = set()
        self._dedup_loaded = False
        self._pending_since_commit = 0
        self._t_start = time.time()
        self._load_state()

    # -- state -------------------------------------------------------------
    def _load_state(self) -> None:
        cur = self.conn.execute("SELECT value FROM meta WHERE key='ingest_state'")
        row = cur.fetchone()
        if row:
            state = json.loads(row[0])
            self.rows_done = state["rows_done"]
            self.last_offset = state["last_offset"]

    def _save_state(self) -> None:
        state = {"rows_done": self.rows_done, "last_offset": self.last_offset}
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES ('ingest_state', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(state),))
        self.conn.commit()

    def _load_dedup_state(self) -> None:
        """Rebuild exact map + LSH buckets from committed canonical rows."""
        if self._dedup_loaded:
            return
        for norm_hash, sid, sig_blob in self.conn.execute(
                "SELECT exact_hash, id, sig FROM stories WHERE is_canonical=1 AND sig IS NOT NULL"):
            self.deduper.add_exact(norm_hash, sid)
            if sig_blob is not None:
                self.deduper.register_canonical(sid, np.frombuffer(sig_blob, dtype=np.uint32))
        self._dedup_loaded = True

    # -- dedup --------------------------------------------------------------
    def _decide(self, story: Dict[str, Any]) -> Tuple[bool, Optional[int], str]:
        text = story["clean_text"]
        if not text.strip():
            return False, None, ""
        norm_hash = normalized_hash(_norm_text_for_hash(text))
        sig = minhash_signature(text)
        dup_of = self.deduper.find_duplicate(norm_hash, sig)
        if dup_of is None:
            self.deduper.add_exact(norm_hash, story["id"])
            self.deduper.register_canonical(story["id"], sig)
            return True, None, norm_hash
        return False, dup_of, norm_hash

    # -- writer --------------------------------------------------------------
    def _write(self, story: Dict[str, Any], is_canonical: bool, dup_of: Optional[int],
               norm_hash: str) -> None:
        text = story["clean_text"]
        sig = self.deduper.sigs.get(story["id"])
        sig_bytes = sig.tobytes() if sig is not None else None
        self.conn.execute(INSERT_SQL, story_row(story, is_canonical, dup_of, sig_bytes, norm_hash))
        keep_full = (is_canonical
                     and story["safety"] == SafetyVerdict.PASS.value
                     and story["quality"]["tier"] in (QualityTier.TIER_1_MASTER.value,
                                                      QualityTier.TIER_2_SECONDARY.value)
                     and story["metrics"]["word_count"] >= 150)
        if keep_full and text:
            blob = zlib.compress(text[:KEEP_FULL_TEXT_MAX_CHARS].encode("utf-8"), level=1)
            self.conn.execute("INSERT OR REPLACE INTO story_text (id, full_text) VALUES (?,?)",
                              (story["id"], blob))

    # -- main loop -----------------------------------------------------------
    def ingest(self, csv_path: str, limit: Optional[int] = None,
               progress_every: int = 20000, workers: int = 2) -> Dict[str, Any]:
        from collections import Counter
        from multiprocessing import get_context
        stats = Counter()
        canonical_stats = Counter()
        self._load_dedup_state()
        self._load_seen_ids()
        fieldnames = self._fieldnames(csv_path)
        ctx = get_context("fork")

        def read_batches():
            """Yield raw row batches while tracking byte-offset checkpoints."""
            with open(csv_path, "r", encoding="utf-8", errors="replace", newline="") as f:
                if self.last_offset:
                    # last_offset is always a completed-record boundary (it is
                    # captured only after a full CSV record is parsed), so seek
                    # lands exactly at the start of the next record. Do NOT
                    # readline() here: that would discard the first line of the
                    # next record and misalign every following multi-line row.
                    f.seek(self.last_offset)
                else:
                    f.readline()  # skip CSV header
                buf: List[str] = []
                quote_count = 0
                batch: List[Dict[str, Any]] = []
                offset = self.last_offset
                while True:
                    line = f.readline()
                    if not line:
                        break
                    buf.append(line)
                    quote_count += line.count('"')
                    if quote_count % 2 == 0:
                        # Complete CSV record (quotes balanced): parse it.
                        row = next(csv.reader(io.StringIO("".join(buf))))
                        buf = []
                        quote_count = 0
                        batch.append({name: row[i] if i < len(row) else ""
                                      for i, name in enumerate(fieldnames)})
                        self._read_rows += 1
                        offset = f.tell()
                        if limit and self._read_rows >= limit:
                            yield batch, offset, True
                            return
                        if len(batch) >= BATCH_ROWS:
                            yield batch, offset, False
                            batch = []
                if batch:
                    yield batch, offset, True

        self._read_rows = self.rows_done
        pool = ctx.Pool(processes=max(1, workers)) if workers > 1 else None
        try:
            for raw_batch, offset, is_last in read_batches():
                stories = process_batch(pool, raw_batch)
                self._flush_batch(stories, offset, stats, canonical_stats)
                if self.rows_done % progress_every < BATCH_ROWS and self.rows_done:
                    self._log_progress(stats)
        finally:
            if pool is not None:
                pool.close()
                pool.join()
        self._save_state()
        return self._final_stats(stats, canonical_stats)

    def _fieldnames(self, csv_path: str) -> List[str]:
        with open(csv_path, "r", encoding="utf-8", errors="replace", newline="") as f:
            return next(csv.reader(f))

    def _load_seen_ids(self) -> None:
        """On resume, avoid re-inserting rows that were committed but not
        checkpointed when the previous run crashed."""
        self._seen_ids: set = set()
        if self.rows_done > 0:
            for (sid,) in self.conn.execute("SELECT id FROM stories"):
                self._seen_ids.add(sid)

    def _flush_batch(self, stories: List[Dict[str, Any]], offset: int, stats,
                     canonical_stats) -> None:
        for story in stories:
            if story.get("__error__"):
                stats["errors"] += 1
                if stats["errors"] <= 20:
                    print(f"[ingest] row {story.get('id')} error: {story['__error__']}",
                          flush=True)
                continue
            story_id = story["id"]
            if story_id in self._seen_ids:
                stats["reprocessed_skips"] += 1
                continue
            try:
                is_canonical, dup_of, norm_hash = self._decide(story)
            except Exception:
                stats["dedup_errors"] += 1
                is_canonical, dup_of, norm_hash = True, None, normalized_hash(
                    _norm_text_for_hash(story["clean_text"]))
            try:
                self._write(story, is_canonical, dup_of, norm_hash)
            except Exception as exc:
                # One malformed row must not abort a multi-hour full-corpus run.
                stats["write_errors"] += 1
                if stats["write_errors"] <= 20:
                    print(f"[ingest] row {story_id} write error: "
                          f"{type(exc).__name__}: {exc}", flush=True)
                self._seen_ids.add(story_id)
                continue
            self._seen_ids.add(story_id)
            stats["processed"] += 1
            if is_canonical:
                canonical_stats["canonical"] += 1
                canonical_stats[story["quality"]["tier"]] += 1
                canonical_stats["safety_" + story["safety"]] += 1
            else:
                canonical_stats["duplicates"] += 1
            self._pending_since_commit += 1
        self._cur_offset = offset
        self.rows_done = self._read_rows
        if self._pending_since_commit >= COMMIT_ROWS or offset >= 0:
            self.conn.commit()
            self.last_offset = self._cur_offset
            self._save_state()
            self._pending_since_commit = 0

    def _log_progress(self, stats) -> None:
        elapsed = max(time.time() - self._t_start, 0.001)
        print(f"[ingest] rows={self.rows_done} elapsed={elapsed/60:.1f}min "
              f"rate={self.rows_done/elapsed:.0f}rows/s errors={stats['errors']}",
              flush=True)
        if self._pending_since_commit:
            self.conn.commit()
            self.last_offset = self._cur_offset
            self._save_state()
            self._pending_since_commit = 0

    def _final_stats(self, stats, canonical_stats) -> Dict[str, Any]:
        return {
            "rows_done": self.rows_done,
            "processed": stats["processed"],
            "errors": stats["errors"],
            "write_errors": stats["write_errors"],
            "dedup_errors": stats["dedup_errors"],
            "reprocessed_skips": stats["reprocessed_skips"],
            "canonical": canonical_stats["canonical"],
            "duplicates": canonical_stats["duplicates"],
            "tiers": {k: v for k, v in canonical_stats.items() if k.startswith("Tier")},
            "safety": {k[7:]: v for k, v in canonical_stats.items() if k.startswith("safety_")},
        }


def main(argv: Optional[List[str]] = None) -> None:
    import argparse
    p = argparse.ArgumentParser(description="Full-corpus streaming ingestion (JGF-12)")
    p.add_argument("--csv", required=True, help="Path to local stories_clean.csv")
    p.add_argument("--db", required=True, help="Output SQLite catalog path")
    p.add_argument("--limit", type=int, default=None, help="Stop after N rows (testing)")
    p.add_argument("--workers", type=int, default=2, help="Row-processing workers")
    args = p.parse_args(argv)
    ingester = FullCorpusIngester(args.db, args.db + ".state.json")
    result = ingester.ingest(args.csv, limit=args.limit, workers=args.workers)
    print(json.dumps(result, indent=2))
    with open(args.db + ".ingest_result.json", "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
