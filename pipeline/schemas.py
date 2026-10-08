"""Data schemas and type definitions for the 300K Story Dataset Pipeline."""

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
    TIER_1_MASTER = "Tier 1: Master Candidate"       # Top 50,000 candidate for TTS
    TIER_2_SECONDARY = "Tier 2: Good Secondary"       # Quality catalogue backlog
    TIER_3_NEEDS_EDIT = "Tier 3: Needs Polishing"     # Requires cleanup / LLM edit
    TIER_4_REJECT = "Tier 4: Reject / Low Quality"    # Excluded from catalogue


class HeatLevel(int, Enum):
    SWEET_ROMANCE = 1      # Minimal explicit, emotional focus
    MODERATE_SENSUAL = 2   # Sensual, moderate explicit scenes
    HIGH_HEAT = 3          # Heavy erotic focus, detailed encounters
    HARDCORE = 4           # Maximum intensity explicit content


class AudioDurationTier(str, Enum):
    MICRO = "Micro (3-7 min)"               # ~500 - 1,100 words (Social/Funnel)
    SHORT = "Short Audio (8-15 min)"        # ~1,200 - 2,300 words
    STANDARD = "Standard Audio (16-30 min)" # ~2,400 - 4,500 words
    FEATURE = "Feature Audio (31-60 min)"   # ~4,600 - 9,000 words
    LONGFORM = "Longform (>60 min)"         # >9,000 words (Episodic)


@dataclass
class RawStory:
    """Raw crawled or imported story item."""
    id: str
    title: str
    author: Optional[str] = None
    text: str = ""
    tags: List[str] = field(default_factory=list)
    source_url: Optional[str] = None
    source_archive: Optional[str] = None
    created_date: Optional[str] = None
    raw_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SafetyAudit:
    verdict: SafetyVerdict
    reasons: List[str] = field(default_factory=list)
    flagged_terms: List[str] = field(default_factory=list)


@dataclass
class QualityBreakdown:
    formatting_cleanliness: float  # 0 - 20
    structural_arc: float          # 0 - 20
    prose_richness: float          # 0 - 25
    dialogue_pacing: float         # 0 - 15
    tts_readability: float         # 0 - 20
    total_score: float             # 0 - 100
    tier: QualityTier
    penalties: List[str] = field(default_factory=list)


@dataclass
class StoryTaxonomy:
    primary_tropes: List[str] = field(default_factory=list)
    relationship_dynamics: List[str] = field(default_factory=list)
    character_archetypes: List[str] = field(default_factory=list)
    heat_level: HeatLevel = HeatLevel.MODERATE_SENSUAL
    point_of_view: str = "Third Person"  # First Person, Second Person, Third Person
    pacing: str = "Medium Pace"          # Slow Burn, Medium Pace, Fast / Instant Passion
    setting: List[str] = field(default_factory=list)
    duration_tier: AudioDurationTier = AudioDurationTier.STANDARD


@dataclass
class TTSMetadata:
    estimated_duration_min: float
    recommended_reading_wpm: int = 150
    tts_suitability_score: float = 0.0  # 0 - 100
    dialogue_percentage: float = 0.0
    recommended_voice_profile: str = "Baritone / Intimate Warm"
    pacing_tag: str = "Balanced"
    segment_count: int = 1
    sample_excerpt: str = ""


@dataclass
class ProcessedStory:
    """Standardized, cleaned, audited, and tagged story."""
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
    safety: SafetyAudit = field(default_factory=lambda: SafetyAudit(SafetyVerdict.PASS))
    quality: QualityBreakdown = field(
        default_factory=lambda: QualityBreakdown(0, 0, 0, 0, 0, 0, QualityTier.TIER_4_REJECT)
    )
    taxonomy: StoryTaxonomy = field(default_factory=StoryTaxonomy)
    tts: TTSMetadata = field(
        default_factory=lambda: TTSMetadata(estimated_duration_min=0.0)
    )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["safety"]["verdict"] = self.safety.verdict.value
        d["quality"]["tier"] = self.quality.tier.value
        d["taxonomy"]["heat_level"] = self.taxonomy.heat_level.value
        d["taxonomy"]["duration_tier"] = self.taxonomy.duration_tier.value
        return d
