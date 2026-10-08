"""
Zero-Cost Audio Assembly Engine using Microsoft Edge Neural TTS.
Generates multi-voice character dialogue, timing markers, and procedural ambient audio.
"""

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

# Character voice profile mapping
VOICE_PROFILES: Dict[str, Dict[str, str]] = {
    "NARRATOR": {
        "voice": "en-US-ChristopherNeural",
        "rate": "+0%",
        "pitch": "-2Hz",
    },
    "CHARACTER_DOMINANT": {
        "voice": "en-US-GuyNeural",
        "rate": "-3%",
        "pitch": "-3Hz",
    },
    "CHARACTER_SUBTLE": {
        "voice": "en-US-AndrewMultilingualNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
    },
    "CHARACTER_RIVAL": {
        "voice": "en-US-BrianMultilingualNeural",
        "rate": "+2%",
        "pitch": "+1Hz",
    },
}


class AudioEngine:
    """
    Synthesizes and composites character dialogue audio and procedural ambient beds.
    """

    def __init__(self, work_dir: str = "/tmp/micro_drama_audio"):
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)

    def get_audio_duration(self, audio_path: str) -> float:
        """
        Extract exact duration of an audio file using ffprobe.
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())

    async def _synthesize_line(
        self,
        line: DialogueLine,
        output_path: str,
    ) -> float:
        """
        Synthesizes a single dialogue line to WAV (44.1kHz stereo PCM) using edge-tts.
        Returns the duration of the audio clip in seconds.
        """
        profile = VOICE_PROFILES.get(line.voice_role, VOICE_PROFILES["NARRATOR"])
        voice = profile["voice"]
        rate = profile["rate"]
        pitch = profile["pitch"]

        temp_mp3 = output_path + ".tmp.mp3"
        comm = edge_tts.Communicate(
            text=line.text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )
        await comm.save(temp_mp3)

        # Standardize to 44.1kHz stereo WAV for seamless concat
        convert_cmd = [
            "ffmpeg",
            "-y",
            "-i", temp_mp3,
            "-ar", "44100",
            "-ac", "2",
            "-c:a", "pcm_s16le",
            output_path,
        ]
        subprocess.run(convert_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if os.path.exists(temp_mp3):
            os.remove(temp_mp3)

        return self.get_audio_duration(output_path)

    def _create_silence(self, duration_sec: float, output_path: str):
        """
        Generates a silent audio file of specified duration.
        """
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(max(duration_sec, 0.05)),
            "-c:a", "pcm_s16le",
            output_path,
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    def _generate_procedural_ambient(self, duration_sec: float, output_path: str):
        """
        Generates a low-cost, zero-copyright cinematic ambient tension drone.
        Subtle bass pulse + soft room tone bed.
        """
        # 55Hz & 110Hz warm cinematic drone with gentle slow modulation
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", f"aevalsrc=0.04*sin(2*PI*55*t)+0.02*sin(2*PI*110*t)+0.015*sin(2*PI*82.5*t):s=44100:d={duration_sec}",
            "-af", "afade=t=in:ss=0:d=1.5,afade=t=out:st={}:d=2".format(max(duration_sec - 2.0, 0)),
            "-c:a", "pcm_s16le",
            output_path,
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    async def compose_dialogue(
        self,
        script: MicroDramaScript,
        output_filename: str = "composed_dialogue.wav",
    ) -> ComposedAudio:
        """
        Synthesizes all dialogue lines, orders them with natural pauses,
        generates the timeline subtitle cues, mixes with procedural ambience,
        and outputs the final mastered audio track.
        """
        clip_files: List[Tuple[str, float]] = []
        cues: List[SubtitleCue] = []

        current_time = 0.5  # 0.5s introductory breathing room
        cue_idx = 1

        for i, line in enumerate(script.dialogue):
            line_file = os.path.join(self.work_dir, f"line_{i:02d}_{line.speaker.lower()}.wav")
            clip_dur = await self._synthesize_line(line, line_file)

            # Record subtitle cue
            start_time = current_time
            end_time = current_time + clip_dur
            cues.append(
                SubtitleCue(
                    index=cue_idx,
                    start_sec=start_time,
                    end_sec=end_time,
                    speaker=line.speaker,
                    text=line.text,
                )
            )
            cue_idx += 1

            clip_files.append((line_file, clip_dur))
            current_time = end_time

            # Add conversational pause
            pause_sec = line.pause_after_sec
            if pause_sec > 0:
                pause_file = os.path.join(self.work_dir, f"pause_{i:02d}.wav")
                self._create_silence(pause_sec, pause_file)
                clip_files.append((pause_file, pause_sec))
                current_time += pause_sec

        dialogue_duration = current_time

        # Add CTA outro pause (extra 4.5 seconds for visual CTA card & freeze)
        outro_sec = 4.5
        outro_pause = os.path.join(self.work_dir, "outro_silence.wav")
        self._create_silence(outro_sec, outro_pause)
        clip_files.append((outro_pause, outro_sec))
        total_duration = dialogue_duration + outro_sec

        # Concat dialogue clips using ffmpeg concat demuxer
        concat_list_file = os.path.join(self.work_dir, "concat_dialogue.txt")
        with open(concat_list_file, "w") as f:
            # First silence
            intro_silence = os.path.join(self.work_dir, "intro_silence.wav")
            self._create_silence(0.5, intro_silence)
            f.write(f"file '{os.path.abspath(intro_silence)}'\n")

            for file_path, _ in clip_files:
                f.write(f"file '{os.path.abspath(file_path)}'\n")

        raw_dialogue_wav = os.path.join(self.work_dir, "raw_dialogue.wav")
        concat_cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_file,
            "-c:a", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            raw_dialogue_wav,
        ]
        subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        raw_dur = self.get_audio_duration(raw_dialogue_wav)

        # Generate ambient drone
        ambient_wav = os.path.join(self.work_dir, "ambient_drone.wav")
        self._generate_procedural_ambient(raw_dur, ambient_wav)

        # Mix raw dialogue with ambient drone (dialogue at 1.0, ambient at 0.18 = -15dB)
        final_audio_path = os.path.join(self.work_dir, output_filename)
        mix_cmd = [
            "ffmpeg",
            "-y",
            "-i", raw_dialogue_wav,
            "-i", ambient_wav,
            "-filter_complex",
            "[0:a]volume=1.0[vocal];[1:a]volume=0.20[drone];[vocal][drone]amix=inputs=2:duration=first:dropout_transition=2[outa]",
            "-map", "[outa]",
            "-c:a", "pcm_s16le",
            final_audio_path,
        ]
        subprocess.run(mix_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        final_dur = self.get_audio_duration(final_audio_path)

        return ComposedAudio(
            full_audio_path=final_audio_path,
            full_duration_sec=final_dur,
            cues=cues,
            dialogue_duration_sec=dialogue_duration,
        )
