"""Semantic embeddings and vector indexing for story retrieval and recommendation."""

from __future__ import annotations
import math
import re
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any


class PurePythonVectorizer:
    """
    Lightweight, deterministic TF-IDF and n-gram vectorizer.
    Requires zero external dependencies (no PyTorch, NumPy, or Scipy needed).
    Produces L2-normalized vector representations for cosine similarity.
    """

    def __init__(self, max_features: int = 512, min_df: int = 1):
        self.max_features = max_features
        self.min_df = min_df
        self.vocabulary: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.is_fitted = False

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into lowercase words and meaningful word bigrams."""
        words = re.findall(r"\b[a-z]{3,}\b", text.lower())
        tokens = list(words)
        # Add bigrams for capturing trope phrases (e.g. 'enemies to', 'slow burn')
        for i in range(len(words) - 1):
            tokens.append(f"{words[i]}_{words[i+1]}")
        return tokens

    def fit(self, documents: List[str]) -> "PurePythonVectorizer":
        """Build vocabulary and compute inverse document frequency (IDF)."""
        num_docs = len(documents)
        if num_docs == 0:
            return self

        doc_frequencies: Counter = Counter()
        for doc in documents:
            unique_tokens = set(self._tokenize(doc))
            for token in unique_tokens:
                doc_frequencies[token] += 1

        # Filter by min_df and select top max_features
        filtered_tokens = [
            token for token, count in doc_frequencies.items()
            if count >= self.min_df
        ]
        # Sort by frequency descending, then alphabetically
        filtered_tokens.sort(key=lambda t: (-doc_frequencies[t], t))
        selected_tokens = filtered_tokens[:self.max_features]

        self.vocabulary = {token: idx for idx, token in enumerate(selected_tokens)}
        # Compute smooth IDF: log((N + 1) / (df + 1)) + 1.0
        self.idf = {
            token: math.log((num_docs + 1.0) / (doc_frequencies[token] + 1.0)) + 1.0
            for token in self.vocabulary
        }
        self.is_fitted = True
        return self

    def transform(self, text: str) -> List[float]:
        """Convert a document into an L2-normalized vector."""
        if not self.is_fitted or not self.vocabulary:
            return []

        tokens = self._tokenize(text)
        token_counts = Counter(tokens)
        total_tokens = max(len(tokens), 1)

        dim = len(self.vocabulary)
        vector = [0.0] * dim

        # Calculate TF-IDF
        for token, count in token_counts.items():
            if token in self.vocabulary:
                idx = self.vocabulary[token]
                tf = count / total_tokens
                idf = self.idf[token]
                vector[idx] = tf * idf

        # L2 normalize vector
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0.0:
            vector = [round(v / norm, 6) for v in vector]

        return vector

    def fit_transform(self, documents: List[str]) -> List[List[float]]:
        self.fit(documents)
        return [self.transform(doc) for doc in documents]


class VectorIndex:
    """
    In-memory vector indexing and search engine for semantic story discovery.
    Provides k-nearest neighbors cosine search and story-to-story recommendations.
    """

    def __init__(self, vectorizer: Optional[PurePythonVectorizer] = None):
        self.vectorizer = vectorizer or PurePythonVectorizer()
        self.items: Dict[str, Dict[str, Any]] = {}  # id -> {id, vector, metadata}

    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two normalized vectors."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        return max(-1.0, min(1.0, dot))

    def build_from_stories(self, stories: List[Dict[str, Any]]) -> "VectorIndex":
        """Index a list of processed stories."""
        if not stories:
            return self

        # Fit vectorizer on story texts
        corpus = [f"{s.get('title', '')} {s.get('clean_text', '')}" for s in stories]
        self.vectorizer.fit(corpus)

        for s in stories:
            story_id = s.get("id")
            text = f"{s.get('title', '')} {s.get('clean_text', '')}"
            vec = self.vectorizer.transform(text)
            self.items[story_id] = {
                "id": story_id,
                "title": s.get("title", ""),
                "tropes": s.get("taxonomy", {}).get("primary_tropes", []),
                "quality_score": s.get("quality", {}).get("total_score", 0.0),
                "duration_min": s.get("tts", {}).get("estimated_duration_min", 0.0),
                "vector": vec,
            }
        return self

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Find the top-k most relevant stories matching the semantic query."""
        if not self.items or not self.vectorizer.is_fitted:
            return []

        query_vec = self.vectorizer.transform(query)
        if not any(query_vec):
            # Fallback keyword match if query terms outside vocabulary
            query_lower = query.lower()
            scored = []
            for item in self.items.values():
                title_sim = 1.0 if query_lower in item["title"].lower() else 0.0
                trope_sim = 1.0 if any(query_lower in t.lower() for t in item["tropes"]) else 0.0
                scored.append((max(title_sim, trope_sim), item))
        else:
            scored = [
                (self.cosine_similarity(query_vec, item["vector"]), item)
                for item in self.items.values()
            ]

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for sim, item in scored[:top_k]:
            results.append({
                "id": item["id"],
                "title": item["title"],
                "similarity": round(sim, 4),
                "tropes": item["tropes"],
                "quality_score": item["quality_score"],
                "duration_min": item["duration_min"],
            })
        return results

    def recommend_similar(self, story_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return top similar stories for recommendation, excluding the target story itself."""
        target = self.items.get(story_id)
        if not target:
            return []

        target_vec = target["vector"]
        scored = []
        for other_id, item in self.items.items():
            if other_id == story_id:
                continue
            sim = self.cosine_similarity(target_vec, item["vector"])
            scored.append((sim, item))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for sim, item in scored[:top_k]:
            results.append({
                "id": item["id"],
                "title": item["title"],
                "similarity": round(sim, 4),
                "tropes": item["tropes"],
                "quality_score": item["quality_score"],
                "duration_min": item["duration_min"],
            })
        return results

    def save(self, file_path: str) -> None:
        """Serialize vector index and vocabulary to JSON file."""
        data = {
            "vocabulary": self.vectorizer.vocabulary,
            "idf": self.vectorizer.idf,
            "items": self.items,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, file_path: str) -> "VectorIndex":
        """Load vector index from JSON file."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        vectorizer = PurePythonVectorizer()
        vectorizer.vocabulary = data.get("vocabulary", {})
        vectorizer.idf = data.get("idf", {})
        vectorizer.is_fitted = bool(vectorizer.vocabulary)

        index = cls(vectorizer=vectorizer)
        index.items = data.get("items", {})
        return index
