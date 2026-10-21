from __future__ import annotations
import html
import re
import unicodedata
from typing import Any
from pipeline.schemas import SafetyAudit, SafetyVerdict

HEADER_PATTERNS: list[Pattern[str]]
UNDERAGE_INDICATORS: list[Pattern[str]]
UNDERAGE_TAG_KEYWORDS: set[str]
EXTREME_VIOLENCE_INDICATORS: list[Pattern[str]]
SENSORY_WORDS: dict[str, set[str]]
EXPLICIT_PATTERN: Pattern[str]


class StoryProfiler:
    @staticmethod
    def clean_text(raw_text: str, header_scan_chars: int = None) -> str: ...

    @staticmethod
    def audit_safety(text: str, tags: list[str] = None) -> SafetyAudit: ...

    @staticmethod
    def extract_metadata_from_headers(raw_text: str, default_title: str = "", default_author: str = "") -> tuple[str, str]: ...

    @classmethod
    def calculate_text_metrics(cls, text: str, density_scan_chars: int = None) -> dict[str, Any]: ...
