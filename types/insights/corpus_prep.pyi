from typing import Literal
from _typeshed import Incomplete

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
from pipeline.profiler import StoryProfiler
from pipeline.quality import StoryQualityScorer
from pipeline.tagging import StoryTaxonomyTagger
from pipeline.tts_prioritizer import TTSPrioritizer
from pipeline.schemas import SafetyVerdict, QualityTier, HeatLevel

NUM_PERMUTATIONS: Literal[128] = 128
BAND_ROWS: Literal[4] = 4
BANDS: Literal[32]
MINHASH_SOURCE_CHARS: Literal[30000] = 30_000
SHINGLE_K: Literal[5] = 5
NEAR_DUP_THRESHOLD: float = 0.80
BATCH_ROWS: Literal[300] = 300
COMMIT_ROWS: Literal[5000] = 5_000
PREVIEW_CHARS: Literal[8000] = 8_000
KEEP_FULL_TEXT_MAX_CHARS: Literal[400000] = 400_000


def minhash_signature(text: str) -> np.ndarray: ...


def signature_similarity(sig_a: np.ndarray, sig_b: np.ndarray) -> float: ...


def band_keys(sig: np.ndarray) -> List[int]: ...


class BandedDeduper:
    buckets: list[dict[int, list[int]]]
    exact_map: dict[str, int]
    sigs: dict[int, ndarray]
    threshold: float

    def __init__(self, near_dup_threshold: float = ...) -> Incomplete: ...

    def add_exact(self, norm_hash: str, story_id: int) -> None: ...

    def register_canonical(self, story_id: int, sig: np.ndarray) -> None: ...

    def find_duplicate(self, norm_hash: str, sig: np.ndarray) -> Optional[int]: ...

    def state_size(self) -> int: ...


def normalized_hash(text: str) -> str: ...


def process_row(row: Dict[str, Any]) -> Dict[str, Any]: ...


def process_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]: ...


def process_batch(pool: Incomplete, raw_batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]: ...


SCHEMA: Literal['\nCREATE TABLE IF NOT EXISTS stories (\n  id INTEGER PRIMARY KEY,\n  title TEXT NOT NULL,\n  author TEXT,\n  category TEXT,\n  orientation TEXT,\n  path TEXT,\n  publication_date TEXT,\n  url TEXT,\n  raw_word_count INTEGER,\n  word_count INTEGER,\n  char_count INTEGER,\n  paragraph_count INTEGER,\n  avg_sentence_len REAL,\n  dialogue_ratio REAL,\n  ttr REAL,\n  sensory_density REAL,\n  explicit_density REAL,\n  safety_verdict TEXT,\n  safety_terms TEXT,\n  quality_formatting REAL, quality_structural REAL, quality_prose REAL,\n  quality_dialogue REAL, quality_tts REAL, quality_total REAL,\n  quality_tier TEXT, quality_penalties TEXT,\n  tropes TEXT, archetypes TEXT, settings TEXT,\n  heat_level INTEGER, pov TEXT, pacing TEXT, duration_tier TEXT,\n  tts_minutes REAL,\n  exact_hash TEXT,\n  sig BLOB,\n  is_canonical INTEGER DEFAULT 1,\n  dup_of INTEGER,\n  preview TEXT\n);\nCREATE INDEX IF NOT EXISTS idx_stories_tier ON stories(quality_tier);\nCREATE INDEX IF NOT EXISTS idx_stories_category ON stories(category);\nCREATE INDEX IF NOT EXISTS idx_stories_date ON stories(publication_date);\nCREATE INDEX IF NOT EXISTS idx_stories_safety ON stories(safety_verdict);\nCREATE TABLE IF NOT EXISTS story_text (\n  id INTEGER PRIMARY KEY,\n  full_text BLOB\n);\nCREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);\n'] = ("""
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
""")


def open_db(db_path: str) -> sqlite3.Connection: ...


INSERT_SQL: Literal['INSERT INTO stories (\n  id, title, author, category, orientation, path, publication_date, url,\n  raw_word_count, word_count, char_count, paragraph_count, avg_sentence_len,\n  dialogue_ratio, ttr, sensory_density, explicit_density,\n  safety_verdict, safety_terms,\n  quality_formatting, quality_structural, quality_prose, quality_dialogue,\n  quality_tts, quality_total, quality_tier, quality_penalties,\n  tropes, archetypes, settings, heat_level, pov, pacing, duration_tier,\n  tts_minutes, exact_hash, sig, is_canonical, dup_of, preview\n) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'] = ("""INSERT INTO stories (
  id, title, author, category, orientation, path, publication_date, url,
  raw_word_count, word_count, char_count, paragraph_count, avg_sentence_len,
  dialogue_ratio, ttr, sensory_density, explicit_density,
  safety_verdict, safety_terms,
  quality_formatting, quality_structural, quality_prose, quality_dialogue,
  quality_tts, quality_total, quality_tier, quality_penalties,
  tropes, archetypes, settings, heat_level, pov, pacing, duration_tier,
  tts_minutes, exact_hash, sig, is_canonical, dup_of, preview
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""")


def story_row(story: Dict[str, Any], is_canonical: bool, dup_of: Optional[int], sig: Optional[bytes], norm_hash: str) -> Tuple: ...


class FullCorpusIngester:
    conn: Connection
    db_path: str
    deduper: BandedDeduper
    last_offset: int
    rows_done: int
    state_path: str

    def __init__(self, db_path: str, state_path: str, near_dup_threshold: float = ...) -> Incomplete: ...

    def ingest(self, csv_path: str, limit: Optional[int] = None, progress_every: int = 20000, workers: int = 2) -> Dict[str, Any]: ...


def main(argv: Optional[List[str]] = None) -> None: ...
