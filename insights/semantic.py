"""Semantic embeddings, topic clustering, and vector search (Tier-1 scope).

Zero-budget, deterministic, local-only embedding pipeline:

1. TfidfVectorizer (1-2 grams, sublinear TF) over title + story preview of
   canonical, safety-passing Tier 1/2 stories.
2. TruncatedSVD (LSA, fixed random_state) -> dense L2-normalized vectors.
3. MiniBatchKMeans topic clusters over the same vectors (fixed seed).
4. Cosine similarity search served from a saved .npz matrix.

Saved artifacts (insights_output/):
- vectors.npz     (ids + matrix + embedding config)
- clusters.json   (cluster sizes, top terms, exemplar stories)
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

SCOPE_SQL = ("is_canonical=1 AND safety_verdict='PASS' AND quality_tier IN "
             "('Tier 1: Master Candidate', 'Tier 2: Good Secondary')")
EMBED_TEXT_CHARS = 3000
N_COMPONENTS = 192
N_CLUSTERS = 40
SEED = 0


def load_scope_rows(db_path: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            f"SELECT id, title, category, publication_date, word_count, quality_total, "
            f"quality_tier, tropes, preview FROM stories WHERE {SCOPE_SQL}")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def fit_embeddings(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = [f"{r['title']} {r['preview'][:EMBED_TEXT_CHARS]}" for r in rows]
    vectorizer = TfidfVectorizer(max_features=60_000, min_df=3, max_df=0.5,
                                 sublinear_tf=True, stop_words="english",
                                 ngram_range=(1, 2), dtype=np.float32)
    tfidf = vectorizer.fit_transform(texts)
    n_comp = min(N_COMPONENTS, tfidf.shape[1] - 1, tfidf.shape[0] - 1)
    svd = TruncatedSVD(n_components=max(2, n_comp), random_state=SEED)
    vectors = svd.fit_transform(tfidf)
    vectors = normalize(vectors)
    return {"vectorizer": vectorizer, "svd": svd, "vectors": vectors}


def fit_clusters(vectors: np.ndarray, k: int = N_CLUSTERS) -> np.ndarray:
    km = MiniBatchKMeans(n_clusters=k, random_state=SEED, batch_size=4096,
                         n_init=5, max_iter=200)
    return km.fit_predict(vectors)


def cluster_report(rows: List[Dict[str, Any]], vectors: np.ndarray,
                   labels: np.ndarray, vectorizer, svd) -> List[Dict[str, Any]]:
    """Top terms + exemplars per cluster via nearest original-space direction."""
    feature_names = np.array(vectorizer.get_feature_names_out())
    report = []
    vocab_index = {t: i for i, t in enumerate(feature_names)}
    for c in sorted(set(labels.tolist())):
        mask = labels == c
        members = np.where(mask)[0]
        centroid = vectors[members].mean(axis=0)
        # Project centroid back into term space for interpretable top terms.
        terms = svd.inverse_transform(centroid.reshape(1, -1))[0]
        top_idx = np.argsort(terms)[::-1][:12]
        top_terms = [str(feature_names[i]) for i in top_idx if terms[i] > 0][:8]
        # Exemplars: members closest to centroid
        sims = vectors[members] @ centroid
        exemplar_pos = members[np.argsort(sims)[::-1][:5]]
        exemplars = []
        for pos in exemplar_pos:
            r = rows[int(pos)]
            exemplars.append({"id": r["id"], "title": r["title"],
                              "category": r["category"], "year": r["publication_date"][:4]})
        trope_counter: Dict[str, int] = {}
        for pos in members:
            for t in json.loads(rows[int(pos)]["tropes"] or "[]"):
                trope_counter[t] = trope_counter.get(t, 0) + 1
        top_tropes = sorted(trope_counter.items(), key=lambda kv: -kv[1])[:5]
        report.append({
            "cluster": int(c), "size": int(mask.sum()), "top_terms": top_terms,
            "top_tropes": top_tropes, "exemplars": exemplars,
        })
    report.sort(key=lambda x: -x["size"])
    return report


def save_vectors(out_dir: str, ids: List[int], vectors: np.ndarray,
                 vectorizer, svd) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "vectors.npz")
    np.savez_compressed(path, ids=np.array(ids, dtype=np.int64),
                        vectors=vectors.astype(np.float32))
    config = {
        "n_components": int(svd.n_components),
        "explained_variance_total": float(svd.explained_variance_ratio_.sum()),
        "vocab_size": len(vectorizer.vocabulary_),
        "idf_sample": [float(x) for x in vectorizer.idf_[:5]],
        "sklearn": "TfidfVectorizer(max_features=60000,min_df=3,max_df=0.5,"
                   "sublinear_tf,stop_words=english,1-2grams)+TruncatedSVD(seed=0)",
    }
    with open(os.path.join(out_dir, "vectors_config.json"), "w") as f:
        json.dump(config, f, indent=1)
    return path


def run_semantic(db_path: str, out_dir: str, max_rows: Optional[int] = None,
                 k: int = N_CLUSTERS) -> Dict[str, Any]:
    rows = load_scope_rows(db_path)
    if max_rows:
        rows = rows[:max_rows]
    if not rows:
        raise SystemExit("no in-scope stories found (run corpus_prep first)")
    emb = fit_embeddings(rows)
    labels = fit_clusters(emb["vectors"], k)
    report = cluster_report(rows, emb["vectors"], labels, emb["vectorizer"], emb["svd"])
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "clusters.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    save_vectors(out_dir, [r["id"] for r in rows], emb["vectors"], emb["vectorizer"], emb["svd"])
    return {"indexed": len(rows), "clusters": len(report),
            "dims": int(emb["vectors"].shape[1])}


class SemanticSearcher:
    """Query-side search over saved vectors.npz (lazy loads)."""

    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        data = np.load(os.path.join(self.out_dir, "vectors.npz"))
        self.ids = data["ids"]
        self.vectors = data["vectors"]
        config = json.load(open(os.path.join(self.out_dir, "vectors_config.json")))
        # Rebuild the exact transform pipeline from a fresh fit is not possible
        # post-hoc; store the fitted pipeline alongside instead.
        import pickle
        with open(os.path.join(self.out_dir, "pipeline.pkl"), "rb") as f:
            self.pipeline = pickle.load(f)
        self._loaded = True

    def search(self, query: str, top_k: int = 12) -> List[Dict[str, Any]]:
        self._load()
        q = self.pipeline.transform([query])
        q = normalize(q)
        sims = (self.vectors @ q[0])
        order = np.argsort(sims)[::-1][:top_k]
        results = []
        for pos in order:
            results.append({"id": int(self.ids[pos]),
                            "similarity": round(float(sims[pos]), 4)})
        return results


def save_pipeline(out_dir: str, vectorizer, svd) -> None:
    """Persist fitted vectorizer+SVD for query-time transforms."""
    import pickle
    os.makedirs(out_dir, exist_ok=True)
    from sklearn.pipeline import Pipeline
    pipe = Pipeline([("tfidf", vectorizer), ("svd", svd)])
    with open(os.path.join(out_dir, "pipeline.pkl"), "wb") as f:
        pickle.dump(pipe, f)


def main(argv: Optional[List[str]] = None) -> None:
    import argparse
    p = argparse.ArgumentParser(description="Embeddings + clusters (JGF-12)")
    p.add_argument("--db", required=True)
    p.add_argument("--out-dir", default="insights_output")
    p.add_argument("--max-rows", type=int, default=None)
    p.add_argument("--clusters", type=int, default=N_CLUSTERS)
    args = p.parse_args(argv)
    import sqlite3
    rows = load_scope_rows(args.db)
    if args.max_rows:
        rows = rows[:args.max_rows]
    emb = fit_embeddings(rows)
    labels = fit_clusters(emb["vectors"], args.clusters)
    report = cluster_report(rows, emb["vectors"], labels, emb["vectorizer"], emb["svd"])
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "clusters.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    save_vectors(args.out_dir, [r["id"] for r in rows], emb["vectors"],
                 emb["vectorizer"], emb["svd"])
    save_pipeline(args.out_dir, emb["vectorizer"], emb["svd"])
    print(json.dumps({"indexed": len(rows), "clusters": len(report),
                      "dims": int(emb["vectors"].shape[1])}, indent=1))


if __name__ == "__main__":
    main()
