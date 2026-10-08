"""End-to-end pipeline orchestrator for batch processing and auditing."""

from __future__ import annotations
import json
import logging
from typing import List, Dict, Any, Optional
from collections import Counter

from pipeline.schemas import (
    RawStory,
    ProcessedStory,
    SafetyVerdict,
    QualityTier,
    HeatLevel
)
from pipeline.profiler import StoryProfiler
from pipeline.dedup import StoryDeduplicator
from pipeline.quality import StoryQualityScorer
from pipeline.tagging import StoryTaxonomyTagger
from pipeline.tts_prioritizer import TTSPrioritizer
from pipeline.embeddings import VectorIndex


logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Manages the full lifecycle from raw archive ingestion to ranked TTS catalog."""

    def __init__(self, near_dup_threshold: float = 0.80):
        self.profiler = StoryProfiler()
        self.deduplicator = StoryDeduplicator(near_dup_threshold=near_dup_threshold)
        self.quality_scorer = StoryQualityScorer()
        self.tagger = StoryTaxonomyTagger()
        self.tts_prioritizer = TTSPrioritizer()

    def process_raw_story(self, raw: RawStory) -> ProcessedStory:
        """Run complete single-story transformation and auditing pipeline."""
        # 1. Clean and normalize text
        clean_text = self.profiler.clean_text(raw.text)

        # 2. Safety Audit
        safety = self.profiler.audit_safety(clean_text, raw.tags)

        # 3. Text Metrics
        metrics = self.profiler.calculate_text_metrics(clean_text)

        # 4. Quality Scoring
        quality = self.quality_scorer.evaluate(clean_text, metrics)

        # 5. Deduplication and Clustering
        is_canonical, cluster_id, sim = self.deduplicator.process_story(
            story_id=raw.id,
            text=clean_text,
            quality_score=quality.total_score
        )

        # 6. Taxonomy Tagging
        taxonomy = self.tagger.tag_story(
            text=clean_text,
            title=raw.title,
            raw_tags=raw.tags,
            metrics=metrics
        )

        # 7. TTS Preparation
        tts_meta = self.tts_prioritizer.generate_tts_metadata(
            story_text=clean_text,
            quality_score=quality.total_score,
            dialogue_ratio=metrics["dialogue_ratio"],
            word_count=metrics["word_count"],
            archetypes=taxonomy.character_archetypes
        )

        exact_hash = self.deduplicator.exact_hash_map.get(
            self.deduplicator.exact_hash_map.get(clean_text, ""),
            raw.id
        )

        return ProcessedStory(
            id=raw.id,
            original_id=raw.id,
            title=raw.title.strip(),
            author=raw.author.strip() if raw.author else "Unknown / Anonymous",
            clean_text=clean_text,
            word_count=metrics["word_count"],
            char_count=metrics["char_count"],
            paragraph_count=metrics["paragraph_count"],
            exact_hash=exact_hash,
            cluster_id=cluster_id,
            is_canonical=is_canonical,
            safety=safety,
            quality=quality,
            taxonomy=taxonomy,
            tts=tts_meta
        )

    def process_batch(self, raw_stories: List[RawStory]) -> List[ProcessedStory]:
        """Process a collection of raw stories through the full pipeline."""
        processed: List[ProcessedStory] = []
        for raw in raw_stories:
            story = self.process_raw_story(raw)
            processed.append(story)
        return processed

    def generate_audit_report(self, processed_stories: List[ProcessedStory]) -> Dict[str, Any]:
        """Generate high-level statistical audit metrics from processed batch."""
        total = len(processed_stories)
        if total == 0:
            return {"total_ingested": 0}

        safety_counts = Counter(s.safety.verdict.value for s in processed_stories)
        tier_counts = Counter(s.quality.tier.value for s in processed_stories)
        canonical_count = sum(1 for s in processed_stories if s.is_canonical)
        duplicate_count = total - canonical_count

        total_words = sum(s.word_count for s in processed_stories if s.is_canonical)
        total_audio_hours = sum(s.tts.estimated_duration_min for s in processed_stories if s.is_canonical) / 60.0

        tropes_counter = Counter()
        heat_counter = Counter()
        for s in processed_stories:
            if s.is_canonical and s.safety.verdict == SafetyVerdict.PASS:
                for t in s.taxonomy.primary_tropes:
                    tropes_counter[t] += 1
                heat_counter[f"Level {s.taxonomy.heat_level.value}"] += 1

        top_tts_candidates = [
            s for s in processed_stories
            if s.is_canonical
            and s.safety.verdict == SafetyVerdict.PASS
            and s.quality.tier == QualityTier.TIER_1_MASTER
        ]

        return {
            "total_ingested": total,
            "canonical_stories": canonical_count,
            "duplicate_stories": duplicate_count,
            "safety_summary": dict(safety_counts),
            "quality_tier_distribution": dict(tier_counts),
            "trope_distribution": dict(tropes_counter.most_common(10)),
            "heat_distribution": dict(heat_counter),
            "total_catalog_words": total_words,
            "total_catalog_audio_hours": round(total_audio_hours, 2),
            "tier_1_tts_candidates_count": len(top_tts_candidates),
        }
