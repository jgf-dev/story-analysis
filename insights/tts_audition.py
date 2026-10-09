"""Cheap local TTS "audition" mode.

Purpose: let the founder *listen* to catalogue stories as authoring inspiration.
Low quality is explicitly acceptable here — no cloud APIs, no cost. Engine
priority is piper (if a local voice model is configured) then espeak-ng.

Audition only. This never produces production audio and never ships dataset
content anywhere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional

MAX_AUDITION_CHARS = 1800   # keep latency low for quick auditions
DEFAULT_WPM = 155


def detect_engine() -> Optional[str]:
    if shutil.which("piper") and _piper_voice():
        return "piper"
    if shutil.which("espeak-ng"):
        return "espeak-ng"
    if shutil.which("espeak"):
        return "espeak"
    return None


def _piper_voice() -> Optional[str]:
    voice = os.environ.get("PIPER_VOICE")
    if voice and os.path.exists(voice):
        return voice
    for candidate in ("models/en_US-ryan-high.onnx", "models/en_US-joe-medium.onnx"):
        if os.path.exists(candidate):
            return candidate
    return None


def synthesize(text: str, max_chars: int = MAX_AUDITION_CHARS) -> Optional[bytes]:
    """Return WAV bytes for a short excerpt, or None if no engine is available."""
    engine = detect_engine()
    if engine is None or not text.strip():
        return None
    excerpt = _clip_to_sentence(text, max_chars)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "audition.wav")
        if engine == "piper":
            voice = _piper_voice()
            cmd = ["piper", "--model", voice, "--output_file", out]
            proc = subprocess.run(cmd, input=excerpt.encode("utf-8"),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=120)
        else:
            bin_name = "espeak-ng" if engine == "espeak-ng" else "espeak"
            # m3 = male variant 3; slow-ish narrative pace
            cmd = [bin_name, "-v", "en-us+m3", "-s", str(DEFAULT_WPM), "-w", out, excerpt]
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=120)
        if proc.returncode != 0 or not os.path.exists(out):
            return None
        with open(out, "rb") as f:
            return f.read()


def _clip_to_sentence(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    # Prefer ending at the last sentence boundary for cleaner audio.
    for sep in (". ", "! ", "? "):
        idx = clipped.rfind(sep)
        if idx > max_chars * 0.5:
            return clipped[: idx + 1]
    return clipped


def engine_status() -> dict:
    engine = detect_engine()
    return {
        "engine": engine,
        "available": engine is not None,
        "note": ("Local TTS ready for auditions." if engine else
                 "No local TTS engine found. Install espeak-ng or piper to enable audition."),
    }
