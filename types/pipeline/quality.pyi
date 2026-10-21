from __future__ import annotations
import math
import re
from typing import Dict, List, Any
from pipeline.schemas import QualityBreakdown, QualityTier


class StoryQualityScorer:
    @classmethod
    def evaluate(cls, text: str, metrics: Dict[str, Any]) -> QualityBreakdown: ...
