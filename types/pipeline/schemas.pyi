from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any
import json


class SafetyVerdict(str, Enum):
    PASS = "PASS"
    FAIL_UNDERAGE_RISK = "FAIL_UNDERAGE_RISK"
    FAIL_EXTREME_VIOLENCE = "FAIL_EXTREME_VIOLENCE"
    FLAGGED_MANUAL_REVIEW = "FLAGGED_MANUAL_REVIEW"


class QualityTier(str, Enum):
    TIER_1_MASTER = "Tier 1: Master Candidate"
    TIER_2_SECONDARY = "Tier 2: Good Secondary"
    TIER_3_NEEDS_EDIT = "Tier 3: Needs Polishing"
    TIER_4_REJECT = "Tier 4: Reject / Low Quality"


class HeatLevel(int, Enum):
    SWEET_ROMANCE = 1
    MODERATE_SENSUAL = 2
    HIGH_HEAT = 3
    HARDCORE = 4


class AudioDurationTier(str, Enum):
    MICRO = "Micro (3-7 min)"
    SHORT = "Short Audio (8-15 min)"
    STANDARD = "Standard Audio (16-30 min)"
    FEATURE = "Feature Audio (31-60 min)"
    LONGFORM = "Longform (>60 min)"


@dataclass
class RawStory:
    id: str
    title: str
    author: Optional[str] = None
    text: str = ""
    tags: List[str]
    source_url: Optional[str] = None
    source_archive: Optional[str] = None
    created_date: Optional[str] = None
    raw_metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]: ...

    def __init__(self, id: str, title: str, author: str | None = ..., text: str = ..., tags: list[str] = ..., source_url: str | None = ..., source_archive: str | None = ..., created_date: str | None = ..., raw_metadata: dict[str, Any] = ...) -> None: ...


@dataclass
class SafetyAudit:
    verdict: SafetyVerdict
    reasons: List[str]
    flagged_terms: List[str]

    def __init__(self, verdict: SafetyVerdict, reasons: list[str] = ..., flagged_terms: list[str] = ...) -> None: ...


@dataclass
class QualityBreakdown:
    formatting_cleanliness: float
    structural_arc: float
    prose_richness: float
    dialogue_pacing: float
    tts_readability: float
    total_score: float
    tier: QualityTier
    penalties: List[str]

    def __init__(self, formatting_cleanliness: float, structural_arc: float, prose_richness: float, dialogue_pacing: float, tts_readability: float, total_score: float, tier: QualityTier, penalties: list[str] = ...) -> None: ...


@dataclass
class StoryTaxonomy:
    primary_tropes: List[str]
    relationship_dynamics: List[str]
    character_archetypes: List[str]
    heat_level: HeatLevel
    point_of_view: str = "Third Person"
    pacing: str = "Medium Pace"
    setting: List[str]
    duration_tier: AudioDurationTier

    def __init__(self, primary_tropes: list[str] = ..., relationship_dynamics: list[str] = ..., character_archetypes: list[str] = ..., heat_level: HeatLevel = ..., point_of_view: str = ..., pacing: str = ..., setting: list[str] = ..., duration_tier: AudioDurationTier = ...) -> None: ...


@dataclass
class TTSMetadata:
    estimated_duration_min: float
    recommended_reading_wpm: int = 150
    tts_suitability_score: float = 0.0
    dialogue_percentage: float = 0.0
    recommended_voice_profile: str = "Baritone / Intimate Warm"
    pacing_tag: str = "Balanced"
    segment_count: int = 1
    sample_excerpt: str = ""

    def __init__(self, estimated_duration_min: float, recommended_reading_wpm: int = ..., tts_suitability_score: float = ..., dialogue_percentage: float = ..., recommended_voice_profile: str = ..., pacing_tag: str = ..., segment_count: int = ..., sample_excerpt: str = ...) -> None: ...


@dataclass
class ProcessedStory:
    id: str
    original_id: str
    title: str
    author: str
    clean_text: str
    word_count: int
    char_count: int
    paragraph_count: int
    exact_hash: str
    cluster_id: Optional[str] = None
    is_canonical: bool = True
    duplicate_count: int = 0
    safety: SafetyAudit
    quality: QualityBreakdown
    taxonomy: StoryTaxonomy
    tts: TTSMetadata

    def to_dict(self) -> Dict[str, Any]: ...

    def __init__(self, id: str, original_id: str, title: str, author: str, clean_text: str, word_count: int, char_count: int, paragraph_count: int, exact_hash: str, cluster_id: str | None = ..., is_canonical: bool = ..., duplicate_count: int = ..., safety: SafetyAudit = ..., quality: QualityBreakdown = ..., taxonomy: StoryTaxonomy = ..., tts: TTSMetadata = ...) -> None: ...
