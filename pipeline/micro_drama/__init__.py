"""
Micro-Dramas Content Pipeline for Project A.
Automated story-to-script adaptation, neural TTS synthesis, kinetic subtitle styling,
and 9:16 vertical video compositing.
"""

from pipeline.micro_drama.models import (
    DialogueLine,
    MicroDramaScript,
    AudioClip,
    ComposedAudio,
    SubtitleCue,
)
from pipeline.micro_drama.script_adapter import ScriptAdapter
from pipeline.micro_drama.audio_engine import AudioEngine
from pipeline.micro_drama.caption_styler import CaptionStyler
from pipeline.micro_drama.video_compositor import VideoCompositor
from pipeline.micro_drama.pipeline_runner import MicroDramaPipeline, MicroDramaResult

__all__ = [
    "DialogueLine",
    "MicroDramaScript",
    "AudioClip",
    "ComposedAudio",
    "SubtitleCue",
    "ScriptAdapter",
    "AudioEngine",
    "CaptionStyler",
    "VideoCompositor",
    "MicroDramaPipeline",
    "MicroDramaResult",
]
