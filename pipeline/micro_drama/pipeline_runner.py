"""
End-to-End Micro-Dramas Pipeline Runner.
Coordinates story-to-script adaptation, multi-voice neural TTS composition,
kinetic subtitle generation, vertical 9:16 video rendering, and batch manifest export
for user batch approval before social posting.
"""

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "story_id": self.story_id,
            "title": self.title,
            "trope": self.trope,
            "hook_headline": self.hook_headline,
            "script": self.script,
            "audio_path": self.audio_path,
            "ass_subtitle_path": self.ass_subtitle_path,
            "srt_subtitle_path": self.srt_subtitle_path,
            "video_path": self.video_path,
            "duration_sec": round(self.duration_sec, 2),
            "file_size_bytes": self.file_size_bytes,
            "social_copy": self.social_copy,
            "compliance_verified": self.compliance_verified,
        }


class MicroDramaPipeline:
    """
    Automated production engine for vertical micro-drama social acquisition videos.
    """

    def __init__(
        self,
        output_dir: str = "data/output/micro_dramas",
        handles: Optional[Dict[str, str]] = None,
    ):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.handles = {**DEFAULT_HANDLES, **(handles or {})}

        self.script_adapter = ScriptAdapter()
        self.caption_styler = CaptionStyler(safe_margin_v=460)

    def _generate_social_copy(self, script: MicroDramaScript) -> Dict[str, Any]:
        """
        Drafts platform-tailored post captions, hashtags, and CTA copy
        for Instagram, Bluesky, and X.
        """
        micro_ig = self.handles["micro_drama_ig"]
        micro_x = self.handles["micro_drama_x"]
        proj_a_ig = self.handles["project_a_ig"]
        proj_a_x = self.handles["project_a_x"]

        # Instagram & Bluesky caption format
        ig_caption = (
            f"\"{script.hook_first_line}\"\n\n"
            f"When tension breaks between rivals... {script.cliffhanger_line}\n\n"
            f"🎧 Listen to Chapter 1 uncut & uncensored on Project A.\n"
            f"🔗 Tap the link in our bio to claim VIP early access!\n\n"
            f"Follow @{micro_ig.lstrip('@')} for daily romantic micro-dramas.\n"
            f"Destination app: @{proj_a_ig.lstrip('@')}\n\n"
            f"#PinnedAndTackled #ProjectA #{script.trope.replace(' ', '').replace('•', ' #')} "
            f"#AudioDrama #RomanceTok #EnemiesToLovers #Storytime"
        )

        # X (Twitter) punchy short caption
        x_caption = (
            f"\"{script.hook_first_line}\"\n\n"
            f"{script.cliffhanger_line}\n\n"
            f"Listen to Chapter 1 UNCUT on Project A ({proj_a_x}).\n"
            f"Link in bio 🔗\n\n"
            f"#{script.trope.replace(' ', '').replace('•', ' #')} #AudioRomance"
        )

        return {
            "instagram_and_bluesky": ig_caption,
            "x_twitter": x_caption,
            "cta_link_text": "Listen to Chapter 1 Uncut (Link in Bio)",
            "hashtags": [
                "#PinnedAndTackled",
                "#ProjectA",
                "#AudioDrama",
                "#RomanceTok",
                "#EnemiesToLovers",
                "#BillionaireRomance",
            ],
            "target_handles": {
                "micro_drama_instagram": micro_ig,
                "micro_drama_bluesky": self.handles["micro_drama_bluesky"],
                "micro_drama_x": micro_x,
                "project_a_instagram": proj_a_ig,
                "project_a_x": proj_a_x,
            },
        }

    async def process_story(
        self,
        story_data: Dict[str, Any],
        sub_dir: Optional[str] = None,
    ) -> MicroDramaResult:
        """
        Executes adaptation, neural TTS generation, subtitle creation,
        and vertical video rendering for a story concept.
        """
        story_id = story_data.get("id", "custom_story")
        work_dir = os.path.join(self.output_dir, sub_dir or story_id)
        os.makedirs(work_dir, exist_ok=True)

        # 1. Adapt story concept to structured micro-drama script
        script = self.script_adapter.adapt_story(story_data)

        # 2. Synthesize multi-voice audio with Edge TTS + procedural ambient drone
        audio_engine = AudioEngine(work_dir=work_dir)
        audio_file_name = f"{story_id}_dialogue.wav"
        composed_audio = await audio_engine.compose_dialogue(
            script=script,
            output_filename=audio_file_name,
        )

        # 3. Generate ASS and SRT kinetic subtitles
        ass_path = os.path.join(work_dir, f"{story_id}_subtitles.ass")
        srt_path = os.path.join(work_dir, f"{story_id}_subtitles.srt")
        self.caption_styler.build_ass_subtitles(composed_audio.cues, ass_path)
        self.caption_styler.build_srt_subtitles(composed_audio.cues, srt_path)

        # 4. Compose 9:16 vertical video
        compositor = VideoCompositor(work_dir=work_dir)
        video_out_path = os.path.join(work_dir, f"{story_id}_micro_drama.mp4")
        compositor.compose_video(
            script=script,
            audio_path=composed_audio.full_audio_path,
            duration_sec=composed_audio.full_duration_sec,
            subtitle_path=ass_path,
            output_path=video_out_path,
            dialogue_duration_sec=composed_audio.dialogue_duration_sec,
            handles=self.handles,
        )

        file_size = os.path.getsize(video_out_path)
        social_copy = self._generate_social_copy(script)

        # Save script JSON alongside video
        script_json_path = os.path.join(work_dir, f"{story_id}_script.json")
        with open(script_json_path, "w", encoding="utf-8") as f:
            json.dump(script.to_dict(), f, indent=2)

        return MicroDramaResult(
            story_id=story_id,
            title=script.title,
            trope=script.trope,
            hook_headline=script.hook_headline,
            script=script.to_dict(),
            audio_path=composed_audio.full_audio_path,
            ass_subtitle_path=ass_path,
            srt_subtitle_path=srt_path,
            video_path=video_out_path,
            duration_sec=composed_audio.full_duration_sec,
            file_size_bytes=file_size,
            social_copy=social_copy,
            compliance_verified=script.compliance_verified,
        )

    async def process_batch(
        self,
        stories: List[Dict[str, Any]],
        batch_id: str = "batch_001",
    ) -> Dict[str, Any]:
        """
        Executes pipeline on multiple story concepts, outputting a batch manifest
        formatted for human batch review and approval.
        """
        results: List[MicroDramaResult] = []
        for story in stories:
            res = await self.process_story(story, sub_dir=f"{batch_id}/{story.get('id', 'story')}")
            results.append(res)

        manifest = {
            "batch_id": batch_id,
            "status": "ready_for_user_approval",
            "channels": {
                "micro_dramas_instagram": self.handles["micro_drama_ig"],
                "micro_dramas_bluesky": self.handles["micro_drama_bluesky"],
                "micro_dramas_x": self.handles["micro_drama_x"],
                "project_a_instagram": self.handles["project_a_ig"],
                "project_a_x": self.handles["project_a_x"],
            },
            "item_count": len(results),
            "items": [r.to_dict() for r in results],
        }

        manifest_path = os.path.join(self.output_dir, f"{batch_id}_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return manifest


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Micro-Dramas Content Pipeline CLI")
    parser.add_argument("--story-id", default="raw_story_007_micro_drama", help="Story ID to process")
    parser.add_argument("--output-dir", default="data/output/micro_dramas", help="Output directory")
    args = parser.parse_args()

    pipeline = MicroDramaPipeline(output_dir=args.output_dir)
    res = await pipeline.process_story({"id": args.story_id})
    print(f"Micro-drama video generated: {res.video_path}")
    print(f"Duration: {res.duration_sec}s | Size: {res.file_size_bytes} bytes")


if __name__ == "__main__":
    asyncio.run(main())
