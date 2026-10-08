"""Taxonomy classification, trope detection, and metadata tagging engine."""

from __future__ import annotations
import re
from typing import List, Dict, Set, Any
from pipeline.schemas import (
    StoryTaxonomy,
    HeatLevel,
    AudioDurationTier,
)

# Rule-based taxonomy classifiers based on keyword, bigram, and context patterns
TROPE_RULES = {
    "Enemies to Lovers": [
        re.compile(r"\b(rival|rivalry|hated|despised|argued|bickering|enemy|enemies|glaring across)\b", re.IGNORECASE)
    ],
    "Friends to Lovers": [
        re.compile(r"\b(best friend|years of friendship|known him since|childhood friend|always been friends)\b", re.IGNORECASE)
    ],
    "Forced Proximity": [
        re.compile(r"\b(snowed in|trapped|stuck|elevator|single bed|shared room|cabin fever|isolated)\b", re.IGNORECASE)
    ],
    "Boss / Employee": [
        re.compile(r"\b(boss|supervisor|assistant|client|promotion|boardroom|executive|senior partner)\b", re.IGNORECASE)
    ],
    "Strangers to Lovers": [
        re.compile(r"\b(stranger|just met|never seen him before|bar hookup|glance across the room)\b", re.IGNORECASE)
    ],
    "First Time": [
        re.compile(r"\b(never done this before|first time|inexperienced|never been with a guy|curious)\b", re.IGNORECASE)
    ],
}

ARCHETYPE_RULES = {
    "Uniform / Law Enforcement": [
        re.compile(r"\b(officer|cop|police|badge|patrol|tactical|detective|military)\b", re.IGNORECASE)
    ],
    "Medical / Healthcare": [
        re.compile(r"\b(doctor|physician|surgeon|nurse|hospital|clinic|stethoscope|scrubs|triage)\b", re.IGNORECASE)
    ],
    "Executive / Corporate": [
        re.compile(r"\b(suit|tailored|bespoke|ceo|partner|boardroom|firm|corporate)\b", re.IGNORECASE)
    ],
    "Athletic / Jock": [
        re.compile(r"\b(gym|locker room|weights|athlete|football|coach|workout|muscular build)\b", re.IGNORECASE)
    ],
    "Rugged / Outdoors": [
        re.compile(r"\b(flannel|timber|boots|mountain|cabin|bearded|woodland|rough hands)\b", re.IGNORECASE)
    ]
}

SETTING_RULES = {
    "Cabin / Wilderness": [re.compile(r"\b(cabin|woods|mountain|lake|pines|fireplace|snow|tahoe)\b", re.IGNORECASE)],
    "Hospital / Medical": [re.compile(r"\b(hospital|emergency room|on-call|ward|scrubs)\b", re.IGNORECASE)],
    "Office / High-Rise": [re.compile(r"\b(elevator|penthouse|office|conference room|desk)\b", re.IGNORECASE)],
    "Gym / Locker Room": [re.compile(r"\b(locker room|gym|shower|bench|sauna)\b", re.IGNORECASE)],
    "Domestic / Bedroom": [re.compile(r"\b(apartment|bedroom|kitchen counter|couch|sheets)\b", re.IGNORECASE)],
}


class StoryTaxonomyTagger:
    """Classifies stories into structured taxonomy dimensions."""

    @classmethod
    def tag_story(
        cls,
        text: str,
        title: str,
        raw_tags: List[str],
        metrics: Dict[str, Any]
    ) -> StoryTaxonomy:
        combined_text = f"{title} {' '.join(raw_tags)} {text}".lower()
        word_count = metrics.get("word_count", 0)
        explicit_density = metrics.get("explicit_density", 0.0)

        # 1. Detect Tropes
        detected_tropes: List[str] = []
        for trope, patterns in TROPE_RULES.items():
            if any(p.search(combined_text) for p in patterns):
                detected_tropes.append(trope)
        if not detected_tropes:
            detected_tropes.append("Contemporary Romance")

        # 2. Detect Archetypes
        detected_archetypes: List[str] = []
        for arch, patterns in ARCHETYPE_RULES.items():
            if any(p.search(combined_text) for p in patterns):
                detected_archetypes.append(arch)

        # 3. Detect Setting
        detected_settings: List[str] = []
        for setting, patterns in SETTING_RULES.items():
            if any(p.search(combined_text) for p in patterns):
                detected_settings.append(setting)

        # 4. Heat Level determination
        # Based on explicit term density:
        # <0.005 -> Sweet, 0.005 - 0.018 -> Moderate, 0.018 - 0.035 -> High Heat, >0.035 -> Hardcore
        if explicit_density < 0.005:
            heat = HeatLevel.SWEET_ROMANCE
        elif explicit_density < 0.018:
            heat = HeatLevel.MODERATE_SENSUAL
        elif explicit_density < 0.035:
            heat = HeatLevel.HIGH_HEAT
        else:
            heat = HeatLevel.HARDCORE

        # 5. Point of View (POV)
        words = re.findall(r"\b\w+\b", text.lower()[:3000])  # sample first 3000 tokens
        i_count = sum(1 for w in words if w in {"i", "me", "my", "mine", "we", "our"})
        you_count = sum(1 for w in words if w in {"you", "your", "yours"})
        he_count = sum(1 for w in words if w in {"he", "him", "his", "they", "them", "their"})

        if you_count > i_count and you_count > he_count:
            pov = "Second Person"
        elif i_count > (he_count * 0.8):
            pov = "First Person"
        else:
            pov = "Third Person"

        # 6. Pacing
        dialogue_ratio = metrics.get("dialogue_ratio", 0.0)
        avg_sentence_len = metrics.get("avg_sentence_len", 0.0)
        if dialogue_ratio > 0.35 and avg_sentence_len < 16:
            pacing = "Fast / Instant Passion"
        elif dialogue_ratio < 0.15 or avg_sentence_len > 24:
            pacing = "Slow Burn"
        else:
            pacing = "Medium Pace"

        # 7. Audio Duration Tier
        if word_count < 1150:
            duration_tier = AudioDurationTier.MICRO
        elif word_count < 2350:
            duration_tier = AudioDurationTier.SHORT
        elif word_count < 4550:
            duration_tier = AudioDurationTier.STANDARD
        elif word_count < 9050:
            duration_tier = AudioDurationTier.FEATURE
        else:
            duration_tier = AudioDurationTier.LONGFORM

        return StoryTaxonomy(
            primary_tropes=detected_tropes,
            relationship_dynamics=detected_tropes,  # aligned
            character_archetypes=detected_archetypes,
            heat_level=heat,
            point_of_view=pov,
            pacing=pacing,
            setting=detected_settings,
            duration_tier=duration_tier
        )
