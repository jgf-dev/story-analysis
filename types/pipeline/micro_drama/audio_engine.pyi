from _typeshed import Incomplete

import os
import asyncio
import subprocess
from typing import List, Dict, Optional, Tuple
import edge_tts
from pipeline.micro_drama.models import (
    MicroDramaScript,
    DialogueLine,
    SubtitleCue,
    AudioClip,
    ComposedAudio,
)

VOICE_PROFILES: Dict[str, Dict[str, str]]


class AudioEngine:
    work_dir: str

    def __init__(self, work_dir: str = "/tmp/micro_drama_audio") -> Incomplete: ...

    def get_audio_duration(self, audio_path: str) -> float: ...

    async def compose_dialogue(self, script: MicroDramaScript, output_filename: str = "composed_dialogue.wav") -> ComposedAudio: ...
