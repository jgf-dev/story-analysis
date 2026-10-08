"""TTS Candidate Selection, Audio Script Chunking, and Voice Profiling."""

from __future__ import annotations
import re
from typing import List, Dict, Any, Tuple
from pipeline.schemas import (
    ProcessedStory,
    TTSMetadata,
    QualityTier,
    SafetyVerdict
)


class TTSPrioritizer:
    """Ranks and prepares candidate stories for studio-quality TTS generation."""

    @classmethod
    def generate_tts_metadata(
        cls,
        story_text: str,
        quality_score: float,
        dialogue_ratio: float,
        word_count: int,
        archetypes: List[str]
    ) -> TTSMetadata:
        # Estimated duration at 150 WPM (standard expressive erotic narrative pace)
        duration_min = round(word_count / 150.0, 1)

        # Suitability score calculation
        # Normalized from quality score with acoustic cadence bonus
        suitability = min(100.0, max(0.0, quality_score * 0.95 + (5.0 if 0.15 <= dialogue_ratio <= 0.40 else 0.0)))

        # Recommended voice profile matching archetypes
        arch_str = " ".join(archetypes).lower()
        if "uniform" in arch_str or "rugged" in arch_str:
            voice_profile = "Husky Baritone / Deep Resonance"
        elif "executive" in arch_str:
            voice_profile = "Crisp Mid-Atlantic / Smooth Baritone"
        elif "medical" in arch_str:
            voice_profile = "Warm Tenor / Calm Intimate"
        else:
            voice_profile = "Warm Baritone / Expressive Sensual"

        # Pacing tag
        if dialogue_ratio > 0.35:
            pacing_tag = "Dynamic Dialogue"
        elif dialogue_ratio < 0.12:
            pacing_tag = "Atmospheric Narration"
        else:
            pacing_tag = "Balanced Narrative"

        # Number of audio production segments (approx 350 words per chunk for stable TTS inference)
        segment_count = max(1, (word_count + 349) // 350)

        # First 200 characters as preview sample
        sample_excerpt = story_text[:250].strip() + "..." if len(story_text) > 250 else story_text

        return TTSMetadata(
            estimated_duration_min=duration_min,
            recommended_reading_wpm=150,
            tts_suitability_score=round(suitability, 1),
            dialogue_percentage=round(dialogue_ratio * 100.0, 1),
            recommended_voice_profile=voice_profile,
            pacing_tag=pacing_tag,
            segment_count=segment_count,
            sample_excerpt=sample_excerpt
        )

    @classmethod
    def chunk_story_for_tts(
        cls,
        clean_text: str,
        max_words_per_chunk: int = 350
    ) -> List[Dict[str, Any]]:
        """
        Partition story into inference-ready audio chunks.
        Inserts SSML paragraph pause tags and dialogue markers.
        """
        paragraphs = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
        chunks: List[Dict[str, Any]] = []

        current_chunk_paras: List[str] = []
        current_word_count = 0
        chunk_index = 1

        for para in paragraphs:
            para_words = len(re.findall(r"\b\w+\b", para))
            if current_word_count + para_words > max_words_per_chunk and current_chunk_paras:
                # Flush chunk
                chunk_text = "\n\n".join(current_chunk_paras)
                chunks.append({
                    "chunk_id": chunk_index,
                    "text": chunk_text,
                    "word_count": current_word_count,
                    "estimated_seconds": round(current_word_count / 150.0 * 60, 1),
                    "ssml_payload": cls._format_ssml_chunk(chunk_text)
                })
                chunk_index += 1
                current_chunk_paras = [para]
                current_word_count = para_words
            else:
                current_chunk_paras.append(para)
                current_word_count += para_words

        if current_chunk_paras:
            chunk_text = "\n\n".join(current_chunk_paras)
            chunks.append({
                "chunk_id": chunk_index,
                "text": chunk_text,
                "word_count": current_word_count,
                "estimated_seconds": round(current_word_count / 150.0 * 60, 1),
                "ssml_payload": cls._format_ssml_chunk(chunk_text)
            })

        return chunks

    @staticmethod
    def _format_ssml_chunk(text: str) -> str:
        """Add pause tags between paragraphs and clean quotes for TTS processors."""
        paragraphs = text.split("\n\n")
        escaped_paras = []
        for p in paragraphs:
            # Replace smart quotes with standard quotes
            p_clean = p.replace("“", '"').replace("”", '"').replace("’", "'")
            escaped_paras.append(f"<p>{p_clean}</p>")
        ssml_body = '<break time="650ms"/>'.join(escaped_paras)
        return f"<speak>{ssml_body}</speak>"

    @classmethod
    def filter_and_rank_candidates(
        cls,
        stories: List[ProcessedStory],
        min_quality_score: float = 75.0,
        target_limit: int = 50000
    ) -> List[ProcessedStory]:
        """
        Filters out safety violations, duplicates, and low-quality stories,
        then ranks candidates by TTS suitability and quality score.
        """
        valid_candidates = [
            s for s in stories
            if s.safety.verdict == SafetyVerdict.PASS
            and s.is_canonical
            and s.quality.tier in (QualityTier.TIER_1_MASTER, QualityTier.TIER_2_SECONDARY)
            and s.quality.total_score >= min_quality_score
        ]

        # Sort descending by quality total score, then by word count
        ranked = sorted(
            valid_candidates,
            key=lambda s: (s.quality.total_score, s.tts.tts_suitability_score),
            reverse=True
        )

        return ranked[:target_limit]
