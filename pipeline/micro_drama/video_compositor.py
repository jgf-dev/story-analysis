"""
9:16 Vertical Video Compositor for Social Micro-Dramas.
Composites atmospheric backgrounds, multi-voice audio waveforms,
channel branding, kinetic ASS subtitles, and high-converting funnel outro cards.
"""

import os
import subprocess
from typing import Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

from pipeline.micro_drama.models import MicroDramaScript

# Default brand handles per channel
DEFAULT_HANDLES = {
    "micro_drama_ig": "@pinnedandtackled",
    "micro_drama_bluesky": "@pinnedandtackled",
    "micro_drama_x": "@pinned_tackled",
    "project_a_ig": "@listenuplads",
    "project_a_x": "@listenuplads",
}

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


class VideoCompositor:
    """
    Assembles complete vertical 9:16 micro-drama videos formatted for
    TikTok, Instagram Reels, YouTube Shorts, X, and Bluesky.
    """

    def __init__(self, work_dir: str = "/tmp/micro_drama_video"):
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
        self.width = 1080
        self.height = 1920

    def generate_base_overlay(
        self,
        script: MicroDramaScript,
        output_path: str,
        handles: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Draws static top branding, hook headline badge, audio visualizer frame,
        and bottom channel anchor into an RGBA PNG.
        """
        hdls = {**DEFAULT_HANDLES, **(handles or {})}
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Load fonts
        f_brand = ImageFont.truetype(FONT_BOLD, 26)
        f_trope = ImageFont.truetype(FONT_BOLD, 28)
        f_hook = ImageFont.truetype(FONT_BOLD, 44)
        f_card_sub = ImageFont.truetype(FONT_REGULAR, 22)
        f_footer_main = ImageFont.truetype(FONT_BOLD, 26)
        f_footer_sub = ImageFont.truetype(FONT_REGULAR, 22)

        # 1. Top Brand Chip (Safe zone: y=150)
        draw.rounded_rectangle(
            [120, 150, 960, 212],
            radius=18,
            fill=(15, 23, 42, 220),
            outline=(56, 189, 248, 255),
            width=2,
        )
        brand_text = f"PINNED & TACKLED  •  {hdls['micro_drama_ig']}  |  {hdls['micro_drama_x']}"
        draw.text((540, 181), brand_text, font=f_brand, fill=(240, 249, 255), anchor="mm")

        # 2. Trope Pill (y=230)
        draw.rounded_rectangle(
            [160, 230, 920, 285],
            radius=16,
            fill=(225, 29, 72, 230),
            outline=(251, 113, 133, 200),
            width=1,
        )
        draw.text((540, 257), f"•  {script.trope.upper()}  •", font=f_trope, fill=(255, 255, 255), anchor="mm")

        # 3. Hook Headline Badge (y=305 to 450)
        draw.rounded_rectangle(
            [80, 305, 1000, 455],
            radius=24,
            fill=(10, 15, 29, 235),
            outline=(148, 163, 184, 120),
            width=2,
        )

        # Word wrap headline if long
        headline = script.hook_headline
        if len(headline) > 32:
            words = headline.split()
            mid = len(words) // 2
            line1 = " ".join(words[:mid])
            line2 = " ".join(words[mid:])
            draw.text((540, 355), line1, font=f_hook, fill=(255, 255, 255), anchor="mm")
            draw.text((540, 410), line2, font=f_hook, fill=(254, 240, 138), anchor="mm")
        else:
            draw.text((540, 380), headline, font=f_hook, fill=(255, 255, 255), anchor="mm")

        # 4. Audio Waveform Frame (y=560 to 920)
        draw.rounded_rectangle(
            [80, 560, 1000, 920],
            radius=24,
            fill=(15, 23, 42, 180),
            outline=(56, 189, 248, 140),
            width=2,
        )
        # Visualizer header & indicator
        draw.text(
            (540, 600),
            "STEREO IMMERSIVE AUDIO DRAMA",
            font=f_brand,
            fill=(56, 189, 248),
            anchor="mm",
        )
        draw.text(
            (540, 630),
            "🎧 Use headphones for full binaural tension",
            font=f_card_sub,
            fill=(148, 163, 184),
            anchor="mm",
        )

        # 5. Persistent Funnel Footer (y=1640 to 1740, safely above platform controls)
        draw.rounded_rectangle(
            [100, 1640, 980, 1735],
            radius=20,
            fill=(15, 23, 42, 225),
            outline=(244, 63, 94, 200),
            width=2,
        )
        draw.text(
            (540, 1672),
            f"UNCUT AUDIO ON PROJECT A  •  {hdls['project_a_ig']}",
            font=f_footer_main,
            fill=(255, 255, 255),
            anchor="mm",
        )
        draw.text(
            (540, 1707),
            "Tap Link in Bio for Full Chapter & Early Access",
            font=f_footer_sub,
            fill=(251, 113, 133),
            anchor="mm",
        )

        img.save(output_path)
        return output_path

    def generate_outro_card(
        self,
        script: MicroDramaScript,
        output_path: str,
        handles: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Draws the end-screen conversion card shown during the outro.
        Highlights the cliffhanger resolution and directs audience into Project A.
        """
        hdls = {**DEFAULT_HANDLES, **(handles or {})}
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Dark overlay backdrop
        draw.rectangle([0, 0, self.width, self.height], fill=(10, 12, 20, 245))

        f_badge = ImageFont.truetype(FONT_BOLD, 28)
        f_hero = ImageFont.truetype(FONT_BOLD, 52)
        f_cliff = ImageFont.truetype(FONT_REGULAR, 34)
        f_cta_main = ImageFont.truetype(FONT_BOLD, 36)
        f_dest = ImageFont.truetype(FONT_BOLD, 42)
        f_dest_sub = ImageFont.truetype(FONT_REGULAR, 26)
        f_handles = ImageFont.truetype(FONT_BOLD, 26)

        # Top tag
        draw.rounded_rectangle(
            [260, 280, 820, 340],
            radius=16,
            fill=(225, 29, 72, 240),
            outline=(255, 255, 255, 180),
            width=2,
        )
        draw.text((540, 310), "PROJECT A • EXCLUSIVE AUDIO", font=f_badge, fill=(255, 255, 255), anchor="mm")

        # Hero cliffhanger question
        draw.text((540, 440), "WHAT HAPPENS NEXT?", font=f_hero, fill=(254, 240, 138), anchor="mm")

        # Cliffhanger quote box
        draw.rounded_rectangle(
            [100, 520, 980, 680],
            radius=20,
            fill=(30, 41, 59, 200),
            outline=(148, 163, 184, 100),
            width=1,
        )
        cliff_line = f"\"{script.cliffhanger_line}\""
        if len(cliff_line) > 45:
            words = cliff_line.split()
            mid = len(words) // 2
            draw.text((540, 580), " ".join(words[:mid]), font=f_cliff, fill=(241, 245, 249), anchor="mm")
            draw.text((540, 625), " ".join(words[mid:]), font=f_cliff, fill=(241, 245, 249), anchor="mm")
        else:
            draw.text((540, 600), cliff_line, font=f_cliff, fill=(241, 245, 249), anchor="mm")

        # Primary Call to Action Card
        draw.rounded_rectangle(
            [80, 760, 1000, 1200],
            radius=28,
            fill=(15, 23, 42, 250),
            outline=(56, 189, 248, 220),
            width=3,
        )

        draw.text(
            (540, 830),
            "LISTEN TO CHAPTER 1 UNCUT",
            font=f_cta_main,
            fill=(255, 255, 255),
            anchor="mm",
        )
        draw.text(
            (540, 900),
            "Available Now on Project A",
            font=f_dest,
            fill=(56, 189, 248),
            anchor="mm",
        )

        # Destination channel
        draw.text(
            (540, 980),
            f"Official Destination: {hdls['project_a_ig']} (IG / X)",
            font=f_dest_sub,
            fill=(203, 213, 225),
            anchor="mm",
        )

        # Bio link button pill
        draw.rounded_rectangle(
            [160, 1050, 920, 1140],
            radius=22,
            fill=(225, 29, 72, 255),
            outline=(255, 255, 255, 220),
            width=2,
        )
        draw.text(
            (540, 1095),
            "👉 TAP LINK IN BIO TO LISTEN FREE",
            font=f_cta_main,
            fill=(255, 255, 255),
            anchor="mm",
        )

        # Micro-drama handle reference
        draw.text(
            (540, 1340),
            f"Series Produced by {hdls['micro_drama_ig']} | {hdls['micro_drama_x']}",
            font=f_handles,
            fill=(148, 163, 184),
            anchor="mm",
        )
        draw.text(
            (540, 1380),
            "New Micro-Dramas Released Daily",
            font=f_dest_sub,
            fill=(100, 116, 139),
            anchor="mm",
        )

        img.save(output_path)
        return output_path

    def compose_video(
        self,
        script: MicroDramaScript,
        audio_path: str,
        duration_sec: float,
        subtitle_path: str,
        output_path: str,
        dialogue_duration_sec: Optional[float] = None,
        handles: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Synthesizes the final high-definition 9:16 vertical video combining:
        1. Deep atmospheric background with subtle cinematic modulation.
        2. Real-time dynamic speech audio waveform.
        3. Persistent branded header and funnel cues.
        4. Mobile-safe kinetic ASS subtitles burned into video.
        5. Timed conversion outro card.
        """
        base_overlay_path = os.path.join(self.work_dir, "base_overlay.png")
        outro_overlay_path = os.path.join(self.work_dir, "outro_card.png")

        self.generate_base_overlay(script, base_overlay_path, handles)
        self.generate_outro_card(script, outro_overlay_path, handles)

        outro_start = dialogue_duration_sec if dialogue_duration_sec else max(duration_sec - 4.5, 0.0)

        # Procedural atmospheric background filter:
        # Dark slate gradient base modulated with subtle warm cinematic vignette
        bg_filter = (
            f"color=c=0x0a0c16:s={self.width}x{self.height}:d={duration_sec}:r=30[bg_base];"
            f"[bg_base]vignette=PI/3.5:aspect=9/16[bg]"
        )

        # Waveform filter:
        # Dimensions: 840x180, centered at y=680
        wave_filter = (
            f"[0:a]showwaves=s=840x180:mode=line:colors=0x38bdf8@0.95|0xf43f5e@0.85:scale=sqrt:r=30[wave]"
        )

        # Composite stack:
        # 1. Overlay base graphic onto background
        # 2. Overlay waveform in visualizer box
        # 3. Overlay outro card starting at outro_start
        # 4. Burn kinetic ASS subtitles
        # Note: Escape subtitle path for libass
        escaped_sub_path = subtitle_path.replace(":", "\\:").replace("'", "\\'")

        filter_complex = (
            f"{bg_filter};"
            f"{wave_filter};"
            f"[bg][1:v]overlay=0:0[v1];"
            f"[v1][wave]overlay=120:690[v2];"
            f"[v2][2:v]overlay=0:0:enable='gte(t,{outro_start:.2f})'[v3];"
            f"[v3]ass='{escaped_sub_path}'[vout]"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i", audio_path,
            "-i", base_overlay_path,
            "-i", outro_overlay_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-t", f"{duration_sec:.2f}",
            output_path,
        ]

        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"Failed to generate video at {output_path}")

        return output_path
