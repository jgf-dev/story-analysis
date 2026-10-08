"""Command-line interface for the 300K Story Ingestion and Audit Pipeline."""

from __future__ import annotations
import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from pipeline.schemas import RawStory
from pipeline.orchestrator import PipelineOrchestrator
from pipeline.tts_prioritizer import TTSPrioritizer
from pipeline.profiler import StoryProfiler
from pipeline.embeddings import VectorIndex


def load_raw_stories(input_path: str, limit: Optional[int] = None) -> List[RawStory]:
    """Load raw stories from JSON, JSONL, or CSV file."""
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    stories = []
    if path.suffix == ".jsonl":
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if limit and len(stories) >= limit:
                    break
                line = line.strip()
                if line:
                    data = json.loads(line)
                    stories.append(RawStory(**data))
    elif path.suffix == ".csv":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if limit and len(stories) >= limit:
                    break
                story_id = str(row.get("id", len(stories) + 1))
                content = row.get("content", "") or row.get("text", "")

                title = (row.get("title") or "").strip()
                if not title or title.lower() in ("unknown", "untitled story", "untitled"):
                    slug = (row.get("story_slug") or "").replace("-", " ").title()
                    title = slug if slug else "Untitled Story"

                author = (row.get("author_name") or row.get("author") or "").strip()
                if not author or author.lower() in ("unknown", "unknown / anonymous", "anonymous"):
                    author = "Unknown / Anonymous"

                # Check if text headers contain richer metadata
                header_title, header_author = StoryProfiler.extract_metadata_from_headers(
                    content, default_title=title, default_author=author
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

                stories.append(RawStory(
                    id=story_id,
                    title=title,
                    author=author,
                    text=content,
                    tags=tags,
                    source_url=row.get("url"),
                    source_archive="Nifty Archive",
                    created_date=row.get("publication_date") or row.get("created_at"),
                    raw_metadata={
                        "path": row.get("path"),
                        "category": row.get("category"),
                        "slug": row.get("story_slug"),
                        "chapter_num": row.get("chapter_num")
                    }
                ))
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if limit and len(stories) >= limit:
                        break
                    stories.append(RawStory(**item))
            elif isinstance(data, dict):
                stories.append(RawStory(**data))
    return stories


def main():
    parser = argparse.ArgumentParser(
        description="300K Gay Male Erotic Audio Story Dataset — Audit & Ingestion Pipeline"
    )
    parser.add_argument(
        "--input", "-i",
        default="data/samples/sample_stories.json",
        help="Path to input dataset file (JSON or JSONL)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="data/output",
        help="Directory to store processed catalog and audit reports"
    )
    parser.add_argument(
        "--near-dup-threshold",
        type=float,
        default=0.80,
        help="MinHash / Jaccard similarity threshold for near-duplicate clustering (default 0.80)"
    )
    parser.add_argument(
        "--min-tts-score",
        type=float,
        default=75.0,
        help="Minimum quality score threshold for TTS candidate queue"
    )
    parser.add_argument(
        "--export-tts-chunks",
        action="store_true",
        help="Export pre-segmented SSML audio chunks for top TTS candidates"
    )

    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Optional limit on number of stories to process"
    )
    parser.add_argument(
        "--build-vector-index",
        action="store_true",
        default=True,
        help="Build TF-IDF semantic vector index for fast search and recommendation"
    )
    parser.add_argument(
        "--no-vector-index",
        dest="build_vector_index",
        action="store_false",
        help="Skip vector index construction"
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=======================================================")
    print(f"  300K STORY DATASET — INGESTION & AUDIT PIPELINE")
    print(f"=======================================================")
    print(f"Loading stories from: {args.input}")

    raw_stories = load_raw_stories(args.input, limit=args.limit)
    print(f"Ingested {len(raw_stories)} raw records. Initializing pipeline...")

    orchestrator = PipelineOrchestrator(near_dup_threshold=args.near_dup_threshold)
    processed_stories = orchestrator.process_batch(raw_stories)

    # Generate high-level audit report
    audit_report = orchestrator.generate_audit_report(processed_stories)

    # Filter and rank top TTS candidates
    tts_candidates = TTSPrioritizer.filter_and_rank_candidates(
        stories=processed_stories,
        min_quality_score=args.min_tts_score
    )

    # Save output artifacts
    catalog_path = output_dir / "cleaned_catalog.jsonl"
    with open(catalog_path, "w", encoding="utf-8") as f:
        for s in processed_stories:
            f.write(json.dumps(s.to_dict()) + "\n")

    candidates_path = output_dir / "tts_priority_candidates.json"
    with open(candidates_path, "w", encoding="utf-8") as f:
        json.dump([s.to_dict() for s in tts_candidates], f, indent=2)

    report_path = output_dir / "audit_summary.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(audit_report, f, indent=2)

    vector_index_path = None
    if args.build_vector_index and processed_stories:
        print("Building vector index for search and recommendations...")
        vector_index = VectorIndex()
        vector_index.build_from_stories([s.to_dict() for s in processed_stories if s.is_canonical])
        vector_index_path = output_dir / "vector_index.json"
        vector_index.save(str(vector_index_path))
        print(f"Vector index built with {len(vector_index.items)} items and {len(vector_index.vectorizer.vocabulary)} vocabulary features.")

    if args.export_tts_chunks and tts_candidates:
        chunks_dir = output_dir / "tts_chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        for cand in tts_candidates:
            chunks = TTSPrioritizer.chunk_story_for_tts(cand.clean_text)
            chunk_file = chunks_dir / f"{cand.id}_chunks.json"
            with open(chunk_file, "w", encoding="utf-8") as f:
                json.dump(chunks, f, indent=2)

    # Print summary table
    print(f"\n--- AUDIT SUMMARY REPORT ---")
    print(f"Total Stories Ingested:        {audit_report.get('total_ingested')}")
    print(f"Canonical Stories:             {audit_report.get('canonical_stories')}")
    print(f"Duplicates Detected:           {audit_report.get('duplicate_stories')}")
    print(f"Total Audio Catalog (hrs):     {audit_report.get('total_catalog_audio_hours')} hrs")
    print(f"\nSafety Audit Breakdown:")
    for verdict, count in audit_report.get("safety_summary", {}).items():
        print(f"  - {verdict:28}: {count}")

    print(f"\nQuality Tier Distribution:")
    for tier, count in audit_report.get("quality_tier_distribution", {}).items():
        print(f"  - {tier:30}: {count}")

    print(f"\nTop Tropes:")
    for trope, count in audit_report.get("trope_distribution", {}).items():
        print(f"  - {trope:28}: {count}")

    print(f"\nTop TTS Studio Candidates (Score >= {args.min_tts_score}): {len(tts_candidates)}")
    print(f"\nOutputs written to:")
    print(f"  - Catalog (JSONL):            {catalog_path}")
    print(f"  - TTS Priority Queue (JSON):  {candidates_path}")
    print(f"  - Audit Summary (JSON):       {report_path}")
    if vector_index_path:
        print(f"  - Semantic Vector Index:      {vector_index_path}")
    print(f"=======================================================\n")


if __name__ == "__main__":
    main()
