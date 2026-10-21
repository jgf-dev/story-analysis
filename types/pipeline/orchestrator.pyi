from _typeshed import Incomplete

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

logger: Logger


class PipelineOrchestrator:
    deduplicator: StoryDeduplicator
    profiler: StoryProfiler
    quality_scorer: StoryQualityScorer
    tagger: StoryTaxonomyTagger
    tts_prioritizer: TTSPrioritizer

    def __init__(self, near_dup_threshold: float = 0.80) -> Incomplete: ...

    def process_raw_story(self, raw: RawStory) -> ProcessedStory: ...

    def process_batch(self, raw_stories: List[RawStory]) -> List[ProcessedStory]: ...

    def generate_audit_report(self, processed_stories: List[ProcessedStory]) -> Dict[str, Any]: ...
