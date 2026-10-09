"""Text cleaning, normalization, profiling, and safety auditing for erotic stories."""

from __future__ import annotations
import re
import html
import unicodedata
from typing import Dict, List, Tuple, Any
from pipeline.schemas import RawStory, SafetyVerdict, SafetyAudit


# Common Usenet, forum, and bulletin board header regexes
HEADER_PATTERNS = [
    re.compile(r"^(archive|date|from|subject|newsgroups|path|message-id|organization):\s+.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^disclaimer:\s+.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(a/n|author'?s?\s*note):\s+.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^<!--[\s\S]*?-->", re.MULTILINE),
    re.compile(r"^(please\s+review|leave\s+feedback|feedback\s+to|send\s+comments\s+to|all\s+characters\s+are\s+over\s+18|all\s+characters\s+depicted).*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\[(reposted|part\s+\d+|end\s+of\s+part|to\s+be\s+continued).*?\]$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^[~*=\-_#]{4,}\s*$", re.MULTILINE),  # ASCII divider lines
]

# Underage / CSAM risk terms (Strict Zero-Tolerance Safety Filters)
UNDERAGE_INDICATORS = [
    re.compile(r"\b(?:1[0-5]|thirteen|fourteen|fifteen)\s*(?:-| )*(?:years?|yrs?)(?:-| )*old\b", re.IGNORECASE),
    re.compile(r"\bage[d]?\s*(?:1[0-5]|thirteen|fourteen|fifteen)\b", re.IGNORECASE),
    re.compile(r"\b(?:under\s*18|underage|prepubescent|pedophil\w*|hebephil\w*|kindergarten|elementary\s+school|middle\s+school|junior\s+high)\b", re.IGNORECASE),
    re.compile(r"\b(?:high\s+school\s+freshman|freshman\s+boy|junior\s+high\s+boy|middle\s+school\s+boy|fourteen|fifteen|thirteen)\b", re.IGNORECASE),
    re.compile(r"\b(?:boyhood|child\s+(?:abuse|victim|exploitation|porn|sex))\b", re.IGNORECASE),
]

UNDERAGE_TAG_KEYWORDS = {"adult-youth", "youth", "underage", "teen", "prepubescent", "junior-high", "highschool", "high-school"}

EXTREME_VIOLENCE_INDICATORS = [
    re.compile(r"\b(necrophilia|snuff|bestiality|zoophilia)\b", re.IGNORECASE),
]

# Sensory vocabulary lists for immersion and quality scoring
SENSORY_WORDS = {
    "tactile": {"touch", "skin", "warm", "warmth", "chill", "cold", "rough", "smooth", "shiver", "heat", "pulse", "brushed", "pressed", "grip", "clutched", "caress"},
    "auditory": {"whisper", "whispered", "groan", "groaned", "murmur", "murmured", "gasp", "gasped", "sigh", "sighed", "breath", "breathed", "raspy", "hummed", "echo"},
    "olfactory": {"scent", "smell", "cedarwood", "cologne", "musk", "rain", "coffee", "sweat", "sweet", "smoke"},
    "visual": {"gaze", "stared", "shadow", "flickered", "amber", "dim", "flushed", "dark", "gleam", "shimmer", "eyes"}
}

EXPLICIT_TERMS = {
    "cock", "dick", "shaft", "chest", "thighs", "hips", "lips", "mouth", "tongue", "erection",
    "hardness", "aching", "naked", "bare", "thrust", "hard", "arousal", "stroking", "groin",
    "nipples", "ass", "nakedness"
}


class StoryProfiler:
    """Profiles raw story text, cleans noise/headers, and evaluates hygiene & safety."""

    @staticmethod
    def clean_text(raw_text: str, header_scan_chars: int = None) -> str:
        """Strip HTML, Usenet headers, ASCII dividers, and normalize unicode.

        header_scan_chars: when set, the Usenet/author-note header patterns are
        only applied to the first N characters (headers live at the top of a
        post). Keeps full-corpus streaming fast without changing results for
        well-formed posts.
        """
        if not raw_text:
            return ""

        # 1. Unescape HTML entities (&nbsp;, &quot;, &#8217;)
        text = html.unescape(raw_text)

        # 2. Normalize unicode (smart quotes, em-dashes, accented characters)
        text = unicodedata.normalize("NFKC", text)

        # 3. Strip HTML tags like <p>, <br>, <div>, <hr>
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)

        # 4. Remove known header, author-note, and divider patterns
        if header_scan_chars and len(text) > header_scan_chars:
            head, tail = text[:header_scan_chars], text[header_scan_chars:]
            for pattern in HEADER_PATTERNS:
                head = pattern.sub("", head)
            text = head + tail
        else:
            for pattern in HEADER_PATTERNS:
                text = pattern.sub("", text)

        # 5. Fix common OCR / encoding mojibake glitches
        text = text.replace("â€™", "'").replace("â€œ", '"').replace("â€", '"').replace("â€”", "—")
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 6. Normalize paragraph breaks (max 2 consecutive newlines)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
        cleaned = "\n\n".join(paragraphs)

        return cleaned

    @staticmethod
    def audit_safety(text: str, tags: List[str] = None) -> SafetyAudit:
        """Evaluate text and tags against ethical, safety, and legal constraints."""
        tags_list = tags or []
        tags_str = " ".join(tags_list).lower()
        full_content = f"{tags_str} {text.lower()}"

        flagged_terms = []

        # Check tag-level indicators (e.g. category 'adult-youth', 'highschool', etc.)
        for tag in tags_list:
            tag_clean = tag.lower().strip()
            if any(k in tag_clean for k in UNDERAGE_TAG_KEYWORDS):
                flagged_terms.append(tag_clean)

        for pat in UNDERAGE_INDICATORS:
            matches = pat.findall(full_content)
            if matches:
                flagged_terms.extend(matches)

        if flagged_terms:
            return SafetyAudit(
                verdict=SafetyVerdict.FAIL_UNDERAGE_RISK,
                reasons=["Underage indicator or CSAM legal compliance risk detected."],
                flagged_terms=list(set(flagged_terms))
            )

        for pat in EXTREME_VIOLENCE_INDICATORS:
            matches = pat.findall(full_content)
            if matches:
                return SafetyAudit(
                    verdict=SafetyVerdict.FAIL_EXTREME_VIOLENCE,
                    reasons=["Non-consensual extreme violence / prohibited content detected."],
                    flagged_terms=list(set(matches))
                )

        return SafetyAudit(verdict=SafetyVerdict.PASS)

    @staticmethod
    def extract_metadata_from_headers(raw_text: str, default_title: str = "", default_author: str = "") -> Tuple[str, str]:
        """Extract title and author from Usenet headers, bylines, or dedications if present."""
        title = default_title or ""
        author = default_author or ""

        # Extract title from Subject: [STORY] Title
        subj_match = re.search(r"^subject:\s*(?:\[story\]|\(story\))?\s*(.*?)$", raw_text, re.IGNORECASE | re.MULTILINE)
        if subj_match and (not title or title.lower() in ("unknown", "untitled story", "untitled")):
            extracted = subj_match.group(1).strip()
            if extracted:
                title = extracted

        # Extract title from Title: ...
        title_match = re.search(r"^title:\s*(.*?)$", raw_text, re.IGNORECASE | re.MULTILINE)
        if title_match and (not title or title.lower() in ("unknown", "untitled story", "untitled")):
            extracted = title_match.group(1).strip()
            if extracted:
                title = extracted

        # Extract author from By: ... or Author: ...
        author_match = re.search(r"^(?:by|author):\s*(.*?)$", raw_text, re.IGNORECASE | re.MULTILINE)
        if author_match and (not author or author.lower() in ("unknown", "unknown / anonymous", "anonymous")):
            extracted = author_match.group(1).strip()
            if extracted:
                author = extracted

        # From: user@host (Author Name)
        from_match = re.search(r"^from:\s*(?:.*?<.*?>|\S+)\s*\((.*?)\)$", raw_text, re.IGNORECASE | re.MULTILINE)
        if from_match and (not author or author.lower() in ("unknown", "unknown / anonymous", "anonymous")):
            extracted = from_match.group(1).strip()
            if extracted:
                author = extracted

        # (c) YEAR "Author Name"
        copy_match = re.search(r"\(c\)\s*(?:\d{4})?\s*[\"']?([A-Za-z\s]+)[\"']?", raw_text, re.IGNORECASE)
        if copy_match and (not author or author.lower() in ("unknown", "unknown / anonymous", "anonymous")):
            extracted = copy_match.group(1).strip()
            if extracted and len(extracted) > 2:
                author = extracted

        return title, author

    @classmethod
    def calculate_text_metrics(cls, text: str, density_scan_chars: int = None) -> Dict[str, Any]:
        """Compute statistical and linguistic metrics for the story.

        density_scan_chars: when set, expensive density metrics (dialogue,
        TTR, sensory, explicit) are computed on the first N characters while
        word/char/paragraph/sentence counts stay computed on the full text.
        Density ratios are length-stable, so this keeps streaming fast.
        """
        if not text.strip():
            return {
                "word_count": 0,
                "char_count": 0,
                "sentence_count": 0,
                "paragraph_count": 0,
                "avg_sentence_len": 0.0,
                "dialogue_ratio": 0.0,
                "sensory_density": 0.0,
                "explicit_density": 0.0,
                "ttr": 0.0,
                "estimated_audio_min": 0.0,
            }

        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        paragraph_count = len(paragraphs)

        # Word tokens
        words = re.findall(r"\b\w+(?:'\w+)?\b", text.lower())
        word_count = len(words)
        char_count = len(text)

        # Sentences
        sentences = re.split(r"[.!?]+(?:\s+|$)", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        sentence_count = max(len(sentences), 1)

        avg_sentence_len = round(word_count / sentence_count, 1)

        if density_scan_chars and len(text) > density_scan_chars:
            density_text = text[:density_scan_chars]
        else:
            density_text = text

        # Dialogue extraction: words enclosed in standard quotes
        dialogue_matches = re.findall(r'["“][^"”]+["”]', density_text)
        dialogue_words = 0
        for d in dialogue_matches:
            dialogue_words += len(re.findall(r"\b\w+\b", d))
        dialogue_ratio = round(dialogue_words / max(word_count, 1), 3)

        # Vocabulary richness: Type-Token Ratio
        density_words = re.findall(r"\b\w+(?:'\w+)?\b", density_text.lower())
        unique_words = set(density_words)
        ttr = round(len(unique_words) / max(len(density_words), 1), 3)

        # Sensory word density
        all_sensory = set().union(*SENSORY_WORDS.values())
        sensory_count = sum(1 for w in density_words if w in all_sensory)
        sensory_density = round(sensory_count / max(len(density_words), 1), 4)

        # Explicit / intimacy density
        explicit_count = sum(1 for w in density_words if w in EXPLICIT_TERMS)
        explicit_density = round(explicit_count / max(len(density_words), 1), 4)

        # Audio duration estimation (150 words per minute is standard for narrative/erotic audio)
        estimated_audio_min = round(word_count / 150.0, 1)

        return {
            "word_count": word_count,
            "char_count": char_count,
            "sentence_count": sentence_count,
            "paragraph_count": paragraph_count,
            "avg_sentence_len": avg_sentence_len,
            "dialogue_ratio": dialogue_ratio,
            "sensory_density": sensory_density,
            "explicit_density": explicit_density,
            "ttr": ttr,
            "estimated_audio_min": estimated_audio_min,
        }
