from typing import Literal
from _typeshed import Incomplete

from __future__ import annotations
import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional
import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

SCOPE_SQL: Literal['is_canonical=1 AND safety_verdict=\'PASS\' AND quality_tier IN (\'Tier 1: Master Candidate\', \'Tier 2: Good Secondary\')'] = ("is_canonical=1 AND safety_verdict='PASS' AND quality_tier IN "
             "('Tier 1: Master Candidate', 'Tier 2: Good Secondary')")
EMBED_TEXT_CHARS: Literal[3000] = 3000
N_COMPONENTS: Literal[192] = 192
N_CLUSTERS: Literal[40] = 40
SEED: Literal[0] = 0


def load_scope_rows(db_path: str) -> List[Dict[str, Any]]: ...


def strip_boilerplate(text: str) -> str: ...


def fit_embeddings(rows: List[Dict[str, Any]]) -> Dict[str, Any]: ...


def fit_clusters(vectors: np.ndarray, k: int = ...) -> np.ndarray: ...


def cluster_report(rows: List[Dict[str, Any]], vectors: np.ndarray, labels: np.ndarray, vectorizer: Incomplete, svd: Incomplete) -> List[Dict[str, Any]]: ...


def save_vectors(out_dir: str, ids: List[int], vectors: np.ndarray, vectorizer: Incomplete, svd: Incomplete) -> str: ...


def run_semantic(db_path: str, out_dir: str, max_rows: Optional[int] = None, k: int = ...) -> Dict[str, Any]: ...


class SemanticSearcher:
    ids: Incomplete
    out_dir: str
    pipeline: Incomplete
    vectors: Incomplete

    def __init__(self, out_dir: str) -> Incomplete: ...

    def search(self, query: str, top_k: int = 12) -> List[Dict[str, Any]]: ...


def save_pipeline(out_dir: str, vectorizer: Incomplete, svd: Incomplete) -> None: ...


def main(argv: Optional[List[str]] = None) -> None: ...
