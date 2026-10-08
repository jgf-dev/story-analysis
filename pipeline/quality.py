"""Automated quality evaluation and multi-dimensional scoring rubric."""

from __future__ import annotations
import math
import re
from typing import Dict, List, Any
from pipeline.schemas import QualityBreakdown, QualityTier


class StoryQualityScorer:
    """Evaluates narrative structure, prose richness, pacing, formatting, and TTS suitability."""

    @classmethod
    def evaluate(cls, text: str, metrics: Dict[str, Any]) -> QualityBreakdown:
        word_count = metrics.get("word_count", 0)
        paragraph_count = metrics.get("paragraph_count", 0)
        avg_sentence_len = metrics.get("avg_sentence_len", 0.0)
        dialogue_ratio = metrics.get("dialogue_ratio", 0.0)
        sensory_density = metrics.get("sensory_density", 0.0)
        ttr = metrics.get("ttr", 0.0)

        penalties: List[str] = []

        # ----------------------------------------------------
        # 1. Formatting & Cleanliness (0 - 20 points)
        # ----------------------------------------------------
        formatting_score = 20.0

        if paragraph_count <= 1 and word_count > 100:
            formatting_score -= 10.0
            penalties.append("Wall of text: missing paragraph breaks.")
        elif paragraph_count < 3 and word_count > 300:
            formatting_score -= 5.0
            penalties.append("Insufficient paragraph structure.")

        # Check for unstripped HTML or weird artifacts
        if re.search(r"<[^>]+>|http[s]?://|[\*~=]{3,}", text):
            formatting_score -= 6.0
            penalties.append("Contains raw formatting artifacts or URLs.")

        # Check for missing capitalization or sentence punctuation
        if not any(c.isupper() for c in text):
            formatting_score -= 8.0
            penalties.append("Lacks standard capitalization / all-lowercase.")

        if not re.search(r"[.!?]", text):
            formatting_score -= 6.0
            penalties.append("Lacks sentence-ending punctuation.")

        # Check for all-caps screaming words
        caps_words = re.findall(r"\b[A-Z]{4,}\b", text)
        if len(caps_words) > 5:
            formatting_score -= 4.0
            penalties.append("Excessive all-caps words.")

        formatting_score = max(0.0, min(20.0, formatting_score))

        # ----------------------------------------------------
        # 2. Structural Arc & Story Length (0 - 20 points)
        # ----------------------------------------------------
        structural_score = 20.0

        if word_count < 150:
            structural_score = 2.0
            penalties.append("Story fragment / teaser (< 150 words).")
        elif word_count < 400:
            structural_score = 8.0
            penalties.append("Very short story (< 400 words).")
        elif 400 <= word_count < 800:
            structural_score = 15.0  # Acceptable micro-drama
        elif 800 <= word_count <= 6000:
            structural_score = 20.0  # Prime sweet spot for single-episode audio
        elif 6000 < word_count <= 15000:
            structural_score = 18.0  # Feature / two-parter
        else:
            structural_score = 14.0  # Very long novella, requires multi-part chunking

        # Paragraph balance
        if paragraph_count > 0:
            avg_words_per_para = word_count / paragraph_count
            if avg_words_per_para > 250:
                structural_score -= 4.0
                penalties.append("Dense paragraphs (> 250 words per paragraph).")

        structural_score = max(0.0, min(20.0, structural_score))

        # ----------------------------------------------------
        # 3. Prose Richness & Sensory Immersion (0 - 25 points)
        # ----------------------------------------------------
        prose_score = 10.0

        if word_count < 100:
            prose_score = 4.0
            penalties.append("Insufficient word count for prose analysis.")
        else:
            # Vocabulary diversity (TTR)
            if ttr >= 0.45:
                prose_score += 6.0
            elif ttr >= 0.35:
                prose_score += 4.0
            elif ttr < 0.25:
                prose_score -= 4.0
                penalties.append("Low vocabulary diversity / repetitive phrasing.")

        # Sensory density (touch, sound, smell, sight)
        # Expected density is ~0.015 - 0.04 (1.5% - 4% of words are sensory descriptors)
        if sensory_density >= 0.025:
            prose_score += 9.0
        elif sensory_density >= 0.015:
            prose_score += 6.0
        elif sensory_density >= 0.008:
            prose_score += 3.0
        else:
            penalties.append("Low sensory immersion (sparse tactile/auditory details).")

        prose_score = max(0.0, min(25.0, prose_score))

        # ----------------------------------------------------
        # 4. Dialogue & Pacing Balance (0 - 15 points)
        # ----------------------------------------------------
        # Sweet spot for audio erotica is 15% - 45% spoken dialogue
        dialogue_score = 15.0
        if 0.15 <= dialogue_ratio <= 0.45:
            dialogue_score = 15.0
        elif 0.08 <= dialogue_ratio < 0.15:
            dialogue_score = 12.0
        elif 0.45 < dialogue_ratio <= 0.65:
            dialogue_score = 11.0
        elif dialogue_ratio < 0.08:
            dialogue_score = 7.0
            penalties.append("Very low dialogue (< 8%); heavy exposition for audio.")
        else:
            dialogue_score = 6.0
            penalties.append("Overly dialogue-dominant (> 65%); lacks descriptive grounding.")

        # ----------------------------------------------------
        # 5. TTS Readability & Acoustic Cadence (0 - 20 points)
        # ----------------------------------------------------
        tts_score = 20.0

        # Penalize excessive run-on sentences (causes TTS breathless artifacts)
        if avg_sentence_len > 35:
            tts_score -= 8.0
            penalties.append("Excessive sentence length (avg > 35 words); adverse for TTS cadence.")
        elif avg_sentence_len > 25:
            tts_score -= 4.0
        elif avg_sentence_len < 7 and word_count > 300:
            tts_score -= 4.0
            penalties.append("Choppy, fragmented sentence cadence.")

        # Punctuation cleanliness check
        if not re.search(r"[.!?]", text):
            tts_score -= 8.0
            penalties.append("Missing sentence boundaries (causes TTS pausing failures).")

        weird_chars = len(re.findall(r"[\$#@&%_~^`|\\]", text))
        if weird_chars > 3:
            tts_score -= 5.0
            penalties.append("Contains non-standard symbols or unpronounceable characters.")

        # Repeated punctuation (e.g. ???? or !!!!)
        if re.search(r"(\!{2,}|\?{2,}|\.{4,})", text):
            tts_score -= 3.0
            penalties.append("Repeated exclamation/question marks.")

        tts_score = max(0.0, min(20.0, tts_score))

        # ----------------------------------------------------
        # Total Composite Calculation & Tier Classification
        # ----------------------------------------------------
        total_score = round(
            formatting_score + structural_score + prose_score + dialogue_score + tts_score,
            1
        )

        if total_score >= 78.0:
            tier = QualityTier.TIER_1_MASTER
        elif total_score >= 62.0:
            tier = QualityTier.TIER_2_SECONDARY
        elif total_score >= 45.0:
            tier = QualityTier.TIER_3_NEEDS_EDIT
        else:
            tier = QualityTier.TIER_4_REJECT

        return QualityBreakdown(
            formatting_cleanliness=round(formatting_score, 1),
            structural_arc=round(structural_score, 1),
            prose_richness=round(prose_score, 1),
            dialogue_pacing=round(dialogue_score, 1),
            tts_readability=round(tts_score, 1),
            total_score=total_score,
            tier=tier,
            penalties=penalties
        )
