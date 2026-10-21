from _typeshed import Incomplete

import os
import json
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pipeline.micro_drama.models import MicroDramaScript, ComposedAudio
from pipeline.micro_drama.script_adapter import ScriptAdapter
from pipeline.micro_drama.audio_engine import AudioEngine
from pipeline.micro_drama.caption_styler import CaptionStyler
from pipeline.micro_drama.video_compositor import VideoCompositor, DEFAULT_HANDLES


@dataclass
class MicroDramaResult:
    story_id: str
    title: str
    trope: str
    hook_headline: str
    script: Dict[str, Any]
    audio_path: str
    ass_subtitle_path: str
    srt_subtitle_path: str
    video_path: str
    duration_sec: float
    file_size_bytes: int
    social_copy: Dict[str, Any]
    compliance_verified: bool

    def to_dict(self) -> Dict[str, Any]: ...

    def __init__(self, story_id: str, title: str, trope: str, hook_headline: str, script: dict[str, Any], audio_path: str, ass_subtitle_path: str, srt_subtitle_path: str, video_path: str, duration_sec: float, file_size_bytes: int, social_copy: dict[str, Any], compliance_verified: bool) -> None: ...


class MicroDramaPipeline:
    caption_styler: CaptionStyler
    handles: dict[str, str]
    output_dir: str
    script_adapter: ScriptAdapter

    def __init__(self, output_dir: str = "data/output/micro_dramas", handles: Optional[Dict[str, str]] = None) -> Incomplete: ...

    async def process_story(self, story_data: Dict[str, Any], sub_dir: Optional[str] = None) -> MicroDramaResult: ...

    async def process_batch(self, stories: List[Dict[str, Any]], batch_id: str = "batch_001") -> Dict[str, Any]: ...


async def main() -> Incomplete: ...
