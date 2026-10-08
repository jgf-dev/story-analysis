"""
Data models for the micro-drama automated content pipeline.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class DialogueLine:
    speaker: str
    voice_role: str  # e.g., 'NARRATOR', 'CHARACTER_DOMINANT', 'CHARACTER_SUBTLE', 'CHARACTER_RIVAL'
    text: str
    emotion: str = "intense"
    pause_after_sec: float = 0.25


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
    tags: List[str] = field(default_factory=lambda: ["AudioDrama", "RomanceTok", "EnemiesToLovers", "ProjectA"])
    compliance_verified: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "story_id": self.story_id,
            "title": self.title,
            "trope": self.trope,
            "hook_headline": self.hook_headline,
            "hook_first_line": self.hook_first_line,
            "dialogue": [
                {
                    "speaker": line.speaker,
                    "voice_role": line.voice_role,
                    "text": line.text,
                    "emotion": line.emotion,
                    "pause_after_sec": line.pause_after_sec,
                }
                for line in self.dialogue
            ],
            "cliffhanger_line": self.cliffhanger_line,
            "cta_text": self.cta_text,
            "cta_subtext": self.cta_subtext,
            "target_duration_sec": self.target_duration_sec,
            "tags": self.tags,
            "compliance_verified": self.compliance_verified,
        }


@dataclass
class SubtitleCue:
    index: int
    start_sec: float
    end_sec: float
    speaker: str
    text: str


@dataclass
class AudioClip:
    file_path: str
    duration_sec: float
    speaker: str
    text: str
    start_time: float
    end_time: float


@dataclass
class ComposedAudio:
    full_audio_path: str
    full_duration_sec: float
    cues: List[SubtitleCue]
    dialogue_duration_sec: float
