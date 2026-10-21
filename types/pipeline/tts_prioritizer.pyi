from __future__ import annotations
import re
from typing import List, Dict, Any, Tuple
from pipeline.schemas import (
    ProcessedStory,
    TTSMetadata,
    QualityTier,
    SafetyVerdict
)


class TTSPrioritizer:
    @classmethod
    def generate_tts_metadata(cls, story_text: str, quality_score: float, dialogue_ratio: float, word_count: int, archetypes: List[str]) -> TTSMetadata: ...

    @classmethod
    def chunk_story_for_tts(cls, clean_text: str, max_words_per_chunk: int = 350) -> List[Dict[str, Any]]: ...

    @classmethod
    def filter_and_rank_candidates(cls, stories: List[ProcessedStory], min_quality_score: float = 75.0, target_limit: int = 50000) -> List[ProcessedStory]: ...
