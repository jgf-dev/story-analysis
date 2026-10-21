from __future__ import annotations
import re
from typing import List, Dict, Set, Any
from pipeline.schemas import (
    StoryTaxonomy,
    HeatLevel,
    AudioDurationTier,
)

TROPE_RULES: dict[str, list[Pattern[str]]]
ARCHETYPE_RULES: dict[str, list[Pattern[str]]]
SETTING_RULES: dict[str, list[Pattern[str]]]


class StoryTaxonomyTagger:
    @classmethod
    def tag_story(cls, text: str, title: str, raw_tags: List[str], metrics: Dict[str, Any]) -> StoryTaxonomy: ...
