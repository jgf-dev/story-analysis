from typing import ClassVar, Literal
from _typeshed import Incomplete

from __future__ import annotations
import hashlib
import re
from typing import Dict, List, Set, Tuple, Optional


def compute_exact_hash(text: str) -> str: ...


def generate_shingles(text: str, k: int = 4) -> Set[str]: ...


def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float: ...


NUM_PERMUTATIONS: Literal[64] = 64
PRIME: Literal[4294967311] = 4294967311
COEFF_A: list[int]
COEFF_B: list[int]


class MinHashSignature:
    NUM_PERMUTATIONS: ClassVar[Literal[64]]
    PRIME: ClassVar[Literal[4294967311]]
    COEFF_A: ClassVar[list[int]]
    COEFF_B: ClassVar[list[int]]

    @classmethod
    def compute(cls, shingles: Set[str]) -> List[int]: ...

    @classmethod
    def similarity(cls, sig_a: List[int], sig_b: List[int]) -> float: ...


class StoryDeduplicator:
    cluster_signatures: dict[str, tuple[list[int], set[str]]]
    clusters: dict[str, list[str]]
    exact_hash_map: dict[str, str]
    near_dup_threshold: float

    def __init__(self, near_dup_threshold: float = 0.80) -> Incomplete: ...

    def process_story(self, story_id: str, text: str, quality_score: float = 0.0) -> Tuple[bool, Optional[str], float]: ...

    @staticmethod
    def extract_series_metadata(title: str) -> Dict[str, Any]: ...
