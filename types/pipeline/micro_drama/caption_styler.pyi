from _typeshed import Incomplete

import os
from typing import List
from pipeline.micro_drama.models import SubtitleCue


def format_ass_time(seconds: float) -> str: ...


def format_srt_time(seconds: float) -> str: ...


def wrap_text_mobile(text: str, max_chars: int = 36) -> str: ...


class CaptionStyler:
    safe_margin_v: int

    def __init__(self, safe_margin_v: int = 460) -> Incomplete: ...

    def build_ass_subtitles(self, cues: List[SubtitleCue], output_path: str) -> str: ...

    def build_srt_subtitles(self, cues: List[SubtitleCue], output_path: str) -> str: ...
