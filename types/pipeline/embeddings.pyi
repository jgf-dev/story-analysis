from _typeshed import Incomplete

from __future__ import annotations
import math
import re
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any


class PurePythonVectorizer:
    idf: dict[str, float]
    is_fitted: bool
    max_features: int
    min_df: int
    vocabulary: dict[str, int]

    def __init__(self, max_features: int = 1024, min_df: int = 1) -> Incomplete: ...

    def fit(self, documents: List[str]) -> "PurePythonVectorizer": ...

    def transform(self, text: str) -> List[float]: ...

    def fit_transform(self, documents: List[str]) -> List[List[float]]: ...


class VectorIndex:
    items: dict[str, dict[str, Any]]
    vectorizer: PurePythonVectorizer

    def __init__(self, vectorizer: Optional[PurePythonVectorizer] = None) -> Incomplete: ...

    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float: ...

    def build_from_stories(self, stories: List[Dict[str, Any]]) -> "VectorIndex": ...

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]: ...

    def recommend_similar(self, story_id: str, top_k: int = 5) -> List[Dict[str, Any]]: ...

    def save(self, file_path: str) -> None: ...

    @classmethod
    def load(cls, file_path: str) -> "VectorIndex": ...
