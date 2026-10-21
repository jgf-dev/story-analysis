from _typeshed import Incomplete

from __future__ import annotations
import csv
import io
import json
import os
import sqlite3
import sys
import numpy as np
import pytest
from insights import analysis, corpus_prep, ner
from insights.corpus_prep import (
    BandedDeduper, FullCorpusIngester, minhash_signature, signature_similarity,
    normalized_hash, process_row, process_rows, process_batch,
)

BASE: str
BASE_LONG: str
VARIANT_LONG: str
DISTINCT: str


@pytest.fixture()
def catalog(tmp_path: Incomplete) -> Incomplete: ...


def test_minhash_identical_and_distinct() -> Incomplete: ...


def test_minhash_estimates_true_jaccard() -> Incomplete: ...


def test_near_duplicate_detected() -> Incomplete: ...


def test_exact_duplicate_detected() -> Incomplete: ...


def test_ingest_writes_catalog(catalog: Incomplete) -> Incomplete: ...


def test_resume_is_idempotent(tmp_path: Incomplete, catalog: Incomplete) -> Incomplete: ...


def test_resume_midfile_multiline_rows(tmp_path: Incomplete) -> Incomplete: ...


def test_process_row_extracts_metadata() -> Incomplete: ...


def test_process_batch_splits_across_workers_and_preserves_order() -> Incomplete: ...


def test_analysis_summary(catalog: Incomplete) -> Incomplete: ...


def test_ner_build_and_combo(catalog: Incomplete) -> Incomplete: ...


def test_entities_extraction() -> Incomplete: ...


def test_strip_boilerplate_removes_chrome_keeps_prose() -> Incomplete: ...


def test_ui_smoke(catalog: Incomplete, tmp_path: Incomplete) -> Incomplete: ...
