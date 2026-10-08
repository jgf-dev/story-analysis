"""JGF-12 Dataset Insight Platform — analysis layer over the 300K story corpus.

This package turns the deduplicated story catalog (built by insights.corpus_prep)
into an internal research tool for story authoring: topic clusters, trend
analysis, semantic search, NER combination search, stats dashboards and a
cheap local TTS audition mode.

Data handling rule: the source dataset is reference/analysis-only and stays
internal. Nothing in this package ships dataset content to users.
"""
