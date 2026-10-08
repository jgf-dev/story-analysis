"""
Kinetic Caption Styler for Social Micro-Dramas.
Produces high-contrast, platform-compliant ASS and SRT subtitles styled
for mobile 9:16 vertical viewports within TikTok and Instagram Reels safe zones.
"""

import os
from typing import List
from pipeline.micro_drama.models import SubtitleCue


def format_ass_time(seconds: float) -> str:
    """
    Convert seconds float to ASS timestamp format: H:MM:SS.cs
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centisecs = int(round((seconds - int(seconds)) * 100))
    if centisecs >= 100:
        centisecs = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"


def format_srt_time(seconds: float) -> str:
    """
    Convert seconds float to SRT timestamp format: HH:MM:SS,mmm
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap_text_mobile(text: str, max_chars: int = 36) -> str:
    """
    Wraps text for 9:16 vertical phone screen reading.
    Breaks lines cleanly on word boundaries.
    """
    words = text.split()
    lines: List[str] = []
    current_line: List[str] = []
    current_len = 0

    for word in words:
        if current_len + len(word) + (1 if current_line else 0) <= max_chars:
            current_line.append(word)
            current_len += len(word) + (1 if len(current_line) > 1 else 0)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_len = len(word)

    if current_line:
        lines.append(" ".join(current_line))

    return "\\N".join(lines)


class CaptionStyler:
    """
    Builds ASS and SRT subtitle files with mobile safe zones and kinetic styling.
    """

    def __init__(self, safe_margin_v: int = 460):
        # 460px from bottom places captions right in the 55-65% vertical eye-line,
        # safely above TikTok comments/sound disc (bottom 350px) and below title cards.
        self.safe_margin_v = safe_margin_v

    def build_ass_subtitles(
        self,
        cues: List[SubtitleCue],
        output_path: str,
    ) -> str:
        """
        Creates ASS subtitle file with high-contrast mobile typography.
        """
        header = f"""[Script Info]
Title: Project A Micro-Drama Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Narrator,DejaVu Sans,48,&H00E0E0E0,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,100,100,{self.safe_margin_v},1
Style: DialogueWhite,DejaVu Sans,54,&H00FFFFFF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,5,3,2,90,90,{self.safe_margin_v},1
Style: DialogueYellow,DejaVu Sans,55,&H002BF5FF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,5,3,2,90,90,{self.safe_margin_v},1
Style: SpeakerTag,DejaVu Sans,34,&H007DF5FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,90,90,{self.safe_margin_v + 130},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events = []
        for cue in cues:
            start_str = format_ass_time(cue.start_sec)
            end_str = format_ass_time(cue.end_sec)
            wrapped_text = wrap_text_mobile(cue.text, max_chars=34)

            # Determine style based on speaker
            if cue.speaker == "NARRATOR":
                style = "Narrator"
                dialogue_text = f"<i>{wrapped_text}</i>"
            else:
                style = "DialogueYellow" if cue.index % 2 == 1 else "DialogueWhite"
                dialogue_text = f"\"{wrapped_text}\""

                # Add a speaker tag event just above the dialogue
                speaker_badge = cue.speaker.upper()
                events.append(
                    f"Dialogue: 1,{start_str},{end_str},SpeakerTag,,0,0,0,,{speaker_badge}"
                )

            events.append(
                f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{dialogue_text}"
            )

        full_content = header + "\n".join(events) + "\n"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_content)

        return output_path

    def build_srt_subtitles(
        self,
        cues: List[SubtitleCue],
        output_path: str,
    ) -> str:
        """
        Creates standard SRT subtitle file.
        """
        blocks = []
        for cue in cues:
            start_str = format_srt_time(cue.start_sec)
            end_str = format_srt_time(cue.end_sec)
            speaker_prefix = f"[{cue.speaker}] " if cue.speaker != "NARRATOR" else ""
            block = f"{cue.index}\n{start_str} --> {end_str}\n{speaker_prefix}{cue.text}\n"
            blocks.append(block)

        full_content = "\n".join(blocks)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_content)

        return output_path
