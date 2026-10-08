"""Deduplication and near-duplicate clustering engine for story archives."""

from __future__ import annotations
import hashlib
import re
from typing import Dict, List, Set, Tuple, Optional


def compute_exact_hash(text: str) -> str:
    """Compute normalized SHA-256 hash ignoring casing and whitespace variations."""
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_shingles(text: str, k: int = 4) -> Set[str]:
    """Generate word k-shingles from text for Jaccard / MinHash estimation."""
    words = re.findall(r"\b\w+\b", text.lower())
    if len(words) < k:
        return set([" ".join(words)]) if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Compute exact Jaccard similarity between two shingle sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return round(intersection / union, 4) if union > 0 else 0.0


NUM_PERMUTATIONS = 64
PRIME = 4294967311
COEFF_A = [(i * 10007 + 3) % PRIME for i in range(1, NUM_PERMUTATIONS + 1)]
COEFF_B = [(i * 20011 + 7) % PRIME for i in range(1, NUM_PERMUTATIONS + 1)]


class MinHashSignature:
    """Lightweight 64-bit MinHash signature generator for fast LSH clustering."""
    NUM_PERMUTATIONS = NUM_PERMUTATIONS
    PRIME = PRIME
    COEFF_A = COEFF_A
    COEFF_B = COEFF_B

    @classmethod
    def compute(cls, shingles: Set[str]) -> List[int]:
        if not shingles:
            return [0] * cls.NUM_PERMUTATIONS

        # Hash each shingle to a 32-bit uint
        shingle_hashes = [
            int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)
            for s in shingles
        ]

        sig = []
        for i in range(cls.NUM_PERMUTATIONS):
            a = cls.COEFF_A[i]
            b = cls.COEFF_B[i]
            min_val = min((a * h + b) % cls.PRIME for h in shingle_hashes)
            sig.append(min_val)
        return sig

    @classmethod
    def similarity(cls, sig_a: List[int], sig_b: List[int]) -> float:
        if len(sig_a) != len(sig_b) or not sig_a:
            return 0.0
        matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
        return round(matches / len(sig_a), 4)


class StoryDeduplicator:
    """Orchestrates exact deduplication and near-duplicate clustering."""

    def __init__(self, near_dup_threshold: float = 0.80):
        self.near_dup_threshold = near_dup_threshold
        self.exact_hash_map: Dict[str, str] = {}  # hash -> canonical_id
        self.cluster_signatures: Dict[str, Tuple[List[int], Set[str]]] = {}  # canonical_id -> (sig, shingles)
        self.clusters: Dict[str, List[str]] = {}  # canonical_id -> [member_ids]

    def process_story(
        self,
        story_id: str,
        text: str,
        quality_score: float = 0.0
    ) -> Tuple[bool, Optional[str], float]:
        """
        Evaluate story for deduplication.
        Returns: (is_canonical, cluster_id, similarity_score)
        """
        exact_h = compute_exact_hash(text)

        # 1. Exact duplicate check
        if exact_h in self.exact_hash_map:
            canonical_id = self.exact_hash_map[exact_h]
            self.clusters.setdefault(canonical_id, []).append(story_id)
            return False, canonical_id, 1.0

        # 2. Near-duplicate check using MinHash + Jaccard verification
        shingles = generate_shingles(text, k=4)
        sig = MinHashSignature.compute(shingles)

        for canonical_id, (can_sig, can_shingles) in self.cluster_signatures.items():
            est_sim = MinHashSignature.similarity(sig, can_sig)
            # If MinHash indicates potential match, verify with exact Jaccard
            if est_sim >= (self.near_dup_threshold - 0.10):
                exact_sim = jaccard_similarity(shingles, can_shingles)
                if exact_sim >= self.near_dup_threshold:
                    self.clusters.setdefault(canonical_id, []).append(story_id)
                    return False, canonical_id, exact_sim

        # 3. New unique cluster canonical
        self.exact_hash_map[exact_h] = story_id
        self.cluster_signatures[story_id] = (sig, shingles)
        self.clusters[story_id] = [story_id]
        return True, story_id, 0.0

    @staticmethod
    def extract_series_metadata(title: str) -> Dict[str, Any]:
        """Detect if story belongs to a serialized installment (e.g. 'Part 2', 'Chapter 3')."""
        part_match = re.search(r"\b(part|chapter|ch\.|pt\.)\s*(\d+)(?:\s*(?:of|/)\s*(\d+))?", title, re.IGNORECASE)
        if part_match:
            part_num = int(part_match.group(2))
            total_parts = int(part_match.group(3)) if part_match.group(3) else None
            # Normalized series base title
            series_name = re.sub(r"[\(\[\{]?(?:part|chapter|ch\.|pt\.)\s*\d+.*$", "", title, flags=re.IGNORECASE).strip(" -:[]()")
            return {
                "is_series": True,
                "series_name": series_name or title,
                "part_number": part_num,
                "total_parts": total_parts
            }
        return {"is_series": False, "series_name": title, "part_number": 1, "total_parts": None}
