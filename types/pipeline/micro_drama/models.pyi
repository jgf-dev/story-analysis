from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class DialogueLine:
    speaker: str
    voice_role: str
    text: str
    emotion: str = "intense"
    pause_after_sec: float = 0.25

    def __init__(self, speaker: str, voice_role: str, text: str, emotion: str = ..., pause_after_sec: float = ...) -> None: ...


@dataclass
class MicroDramaScript:
    story_id: str
    title: str
    trope: str
    hook_headline: str
    hook_first_line: str
    dialogue: List[DialogueLine]
    cliffhanger_line: str
    cta_text: str = "Listen to the uncensored audio experience on Project A"
    cta_subtext: str = "Link in Bio • Join VIP Early Access"
    target_duration_sec: float = 35.0
    tags: List[str]
    compliance_verified: bool = True

    def to_dict(self) -> Dict[str, Any]: ...

    def __init__(self, story_id: str, title: str, trope: str, hook_headline: str, hook_first_line: str, dialogue: list[DialogueLine], cliffhanger_line: str, cta_text: str = ..., cta_subtext: str = ..., target_duration_sec: float = ..., tags: list[str] = ..., compliance_verified: bool = ...) -> None: ...


@dataclass
class SubtitleCue:
    index: int
    start_sec: float
    end_sec: float
    speaker: str
    text: str

    def __init__(self, index: int, start_sec: float, end_sec: float, speaker: str, text: str) -> None: ...


@dataclass
class AudioClip:
    file_path: str
    duration_sec: float
    speaker: str
    text: str
    start_time: float
    end_time: float

    def __init__(self, file_path: str, duration_sec: float, speaker: str, text: str, start_time: float, end_time: float) -> None: ...


@dataclass
class ComposedAudio:
    full_audio_path: str
    full_duration_sec: float
    cues: List[SubtitleCue]
    dialogue_duration_sec: float

    def __init__(self, full_audio_path: str, full_duration_sec: float, cues: list[SubtitleCue], dialogue_duration_sec: float) -> None: ...
