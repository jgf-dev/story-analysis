"""Text cleaning, normalization, profiling, and safety auditing for erotic stories."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

from pipeline.schemas import SafetyAudit, SafetyVerdict

# Common Usenet, forum, and bulletin board header regexes
HEADER_PATTERNS = [
    re.compile(r"^(archive|date|from|subject|newsgroups|path|message-id|organization):\s+.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^disclaimer:\s+.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(a/n|author'?s?\s*note):\s+.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^<!--[\s\S]*?-->", re.MULTILINE),
    re.compile(
        r"^(please\s+review|leave\s+feedback|feedback\s+to|send\s+comments\s+to|all\s+characters\s+are\s+over\s+18|all\s+characters\s+depicted).*$", re.IGNORECASE | re.MULTILINE
    ),
    re.compile(r"^\[(reposted|part\s+\d+|end\s+of\s+part|to\s+be\s+continued).*?\]$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^[~*=\-_#]{4,}\s*$", re.MULTILINE),  # ASCII divider lines
]

# Remailer / anonymiser boilerplate. These footers are added by the archive
# software, not the author, and they contain strings that trip the safety
# screen — the anon.penet.fi footer embeds "abuse@anon.penet.fi", which matched
# the bare "abuse" alternative in EXTREME_VIOLENCE_INDICATORS and quarantined
# 109 of 350 violence verdicts on a 5,000-row sample. Stripped before screening.
ANONYMISER_BOILERPLATE = [
    re.compile(r"^.*\*?automatically\*?\s+anonymized.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*report\s+inappropriate\s+use\s+to.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*\bhelp@anon\.penet\.fi\b.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*\banon\.penet\.fi\b.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*\bfor\s+information\s+\(incl\.\s+non-anon\s+reply\).*$", re.IGNORECASE | re.MULTILINE),
]

# Underage / CSAM risk terms (Strict Zero-Tolerance Safety Filters)
#
# Every rule here requires real age context. Rule 4 previously ended with the
# bare alternatives `fourteen|fifteen|thirteen`, which matched any occurrence of
# those words — clock times, prices, jersey numbers, durations — and produced
# 455 false positives in a 5,000-row sample (10 of 19 underage verdicts in the
# 100-row catalogue).
#
# Removing it outright created the opposite problem: 288 rows containing a
# genuine age assertion ("I was fifteen", "who was 15", "when I was fourteen")
# started passing. Rule 4 below replaces the bare alternatives with an
# age-verb construction, which catches those cases while still excluding
# durations and measurements. A false negative here is a compliance failure, so
# this rule errs toward flagging.
UNDERAGE_INDICATORS = [
    re.compile(r"\b(?:1[0-5]|thirteen|fourteen|fifteen)\s*(?:-| )*(?:years?|yrs?)(?:-| )*old\b", re.IGNORECASE),
    re.compile(r"\bage[d]?\s*(?:1[0-5]|thirteen|fourteen|fifteen)\b", re.IGNORECASE),
    re.compile(r"\b(?:under\s*18|underage|prepubescent|pedo|pedophil\w*|hebephil\w*|kindergarten|elementary\s+school|middle\s+school|junior\s+high)\b", re.IGNORECASE),
    # Age-verb construction: "was fifteen", "who was 15", "turned fourteen".
    # Excludes a following unit of time or measure, which is what made the old
    # bare-numeral rule fire on "fifteen minutes" and "fifteen years ago", and
    # excludes a non-age subject ("his number was thirteen").
    re.compile(
        r"(?<!number\s)(?<!jersey\s)(?<!score\s)(?<!count\s)(?<!total\s)"
        r"(?<!page\s)(?<!chapter\s)(?<!room\s)(?<!floor\s)(?<!apartment\s)"
        r"(?<!unit\s)(?<!size\s)(?<!shoe\s)(?<!grade\s)(?<!route\s)(?<!exit\s)"
        r"\b(?:was|were|is|are|am|be|been|being|turned|turning|turns|aged|age)\s+"
        r"(?:1[0-5]|thirteen|fourteen|fifteen)\b"
        r"(?!\s*(?:minutes?|seconds?|hours?|days?|weeks?|months?|years?|percent|"
        r"feet|foot|inch(?:es)?|miles?|dollars?|bucks?|chapters?|pages?|yards?|"
        r"meters?|pounds?|degrees?|times?|ways?|stories|story|lines?|words?|"
        r"lengths?|penis-lengths?))",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:high\s+school\s+freshman|freshman\s+boy|junior\s+high\s+boy|middle\s+school\s+boy)\b", re.IGNORECASE),
    re.compile(r"\b(?:boyhood|(?:child|kid|toddler|infant|kiddy)\s+(?:abuse|rape|violence|victim|exploitation|porn|sex))\b", re.IGNORECASE),
]

UNDERAGE_TAG_KEYWORDS = {"adult-youth", "youth", "underage", "prepubescent", "junior-high"}

# Genuinely prohibited content. Fail-closed, no review path.
EXTREME_VIOLENCE_INDICATORS = [
    re.compile(r"\b(necrophilia|snuff|bestiality|zoophilia)\b", re.IGNORECASE),
]

# Ambiguous but legal language. These words appear constantly in erotic prose as
# metaphor ("his assault on the hard throbbing cock", "screamed bloody murder")
# and in archive boilerplate ("report inappropriate use to abuse@..."), so they
# are quarantined for review rather than treated as prohibited content.
#
# The email/URL guard matters: a bare \b(abuse|rape)\b matched the substring in
# "abuse@anon.penet.fi", which alone drove 109 of 350 violence verdicts on a
# 5,000-row sample.
MANUAL_REVIEW_INDICATORS = [
    re.compile(
        r"(?<![\w@.])"
        r"(?:abuse|rape|murder|assault|suicide|kill\s+myself)"
        r"(?![\w@]|\.[a-z]{2,})",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:stab|shoot)\s+(?:him|her|them)\b", re.IGNORECASE),
]

# Sensory vocabulary lists for immersion and quality scoring
SENSORY_WORDS = {
    "tactile": {"touch", "skin", "warm", "warmth", "chill", "cold", "rough", "smooth", "shiver", "heat", "pulse", "brushed", "pressed", "grip", "clutched", "caress"},
    "auditory": {"whisper", "whispered", "groan", "groaned", "murmur", "murmured", "gasp", "gasped", "sigh", "sighed", "breath", "breathed", "raspy", "hummed", "echo"},
    "olfactory": {"scent", "smell", "cedarwood", "cologne", "musk", "rain", "coffee", "sweat", "sweet", "smoke"},
    "visual": {"gaze", "stared", "shadow", "flickered", "amber", "dim", "flushed", "dark", "gleam", "shimmer", "eyes"},
}

EXPLICIT_PATTERN = re.compile(
    r"""\b(?:cock|dick|shaft|penis|boner|stiffy|erection|tenting|pubes|cake|
    (?:arm)?pits|balls|nuts?|sack|chest|pecs|abs|nipples|thighs|hips|groin|
    lips|mouth|tongue|butt|anus|bussy|(?:ass|man|boy|cum|fuck|slut|
    glory[\s-]?)?hole|(?:boy|man)[\s-]?pussy|man[\s-]?cunt|
    muscle(?:[\s-]?cunt)?|(?:power[\s-]?)?(?:top|bottom)|bottom[\s-]?out|
    vers(?:atile)?|side|bator|daddy|boy|pig(?:gy)?|cum(?:pig|[\s-]?(?:slut|
    dump|swap|soaked|load(?:ed|ing)?|shots?|shoot(?:ing)?|spurt(?:ed)?|
    and[\s-]?(?:go|leave)))?|load(?:pig|s|[\s-]?and[\s-]?leave)?|
    no[\s-]loads?[\s-]refused|slut|fuck(?:ed)?|face[\s-]?fuck|pound|wreck|
    rail|thrust|(?:(?:double|triple)[\s-]?)?penetration|triple[\s-]?p|dp|
    bre(?:ed(?:ing)?|d)|raw(?:dog)?|bare(?:back)?|bb|rim(?:ming)?|
    eat[\s-]?ass|(?:lick|suck|jerk|frott|fist|slap)(?:ing)?|suck[\s-]?off|
    (?:bulg|strok|edg|cruis)(?:e|ing)|goon(?:er|ing)?|blow[\s-]?jobs?|bj|
    fellatio|(?:deep[\s-]?)?throat|jizz|bust|ejaculate|pre(?:[\s-]?cum)?|
    spurt(?:ed|[\s-]?out)?|dogg(?:y|ie)|dog(?:gy)?[\s-]?style|spoon(?:ing|ed)?|
    missionary(?:[\s-]?style)?|(?:reverse[\s-]?)?cowboy|bukkaked?|(?:three|four|
    five|six|seven|eight|nine|ten)[\s-]?way|(?:three|four)some|orgy|(?:group|
    public)[\s-]?sex|family[\s-]?(?:sex|incest)|gang[\s-]?bang|
    ass(?:[\s-]?to[\s-]?mouth)?|atm|anal(?:[\s-]?(?:sex|play))?|
    shag(?:g(?:ing|ed)|[\s-]?(?:me|them|him))?|spank(?:ing|
    ed|[\s-]?(?:me|them|him))?|deprav(?:ed|ity)|perver(?:t(?:ed)?|s(?:e|ion))|
    incest(?:uous)?|step[\s-]?(?:mom|dad|sister)|(?:step[\s-]?)?brother|
    dilf|tw[iu]nk|(?:[3-9]|[12]\d)\s?(?:in(?:ches)?|cm|centimeters)|
    lub(?:ed?|ricant|ricated)|humiliat(?:ed?|ing|ion)|degrad(?:ed?|ing|ation)|
    used|serve|obey|order|snowball|milk|spit|piss(?:[\s-]?(?:play|soaked))?|
    urine|watersports|ws|golden[\s-]?shower|wet(?:ness)?|moisture|sweat|
    dripping|leaking|sloppy|flooded|messy|arousal|turned[\s-]?on|
    hard(?:on|ness)?|aching|unprotected|naked(?:ness)?|nude|(?:un)?cut|
    kinky?|fetish(?:y|is[mt]|istic)?|bdsm|bondage|discipline|
    dom(?:in(?:ance|ation))?|sub(?:mission)?|switch|exhib(?:ition(?:is[mt])?)?|
    show[\s-]?off|voyeur(?:ism|istic)?|public(?:ly|[\s-]?(?:play|display))|
    puppy[\s-]?play|poppers|pnp|chemsex|jock(?:[\s-]?strap)?|gear|leather|
    chastity|cage|locked|deni(?:al|ed)[\s-]?orgasm|(?:orgasm[\s-]?)?denial|
    cuck(?:old(?:ing|ry)?)?|otter|bear|cub|masc4masc|size[\s-]?(?:queen|kink)|
    teen(?:age(?:r|d(?:[\s-]?boy)?)?)?|69|sixty[\s-]?(?:nine|9)|bathhouse|sauna|
    dark[\s-]?room|anon(?:ymous)?|dl|down[\s-]?low|discreet|nsa|trade|hung)\b""",
    re.IGNORECASE | re.VERBOSE,
)

# Negators that, when immediately preceding an age indicator, mean the text is
# asserting the opposite ("he was not fifteen"). Deliberately narrow: only a
# negator within a few words before the match counts, so a negation elsewhere in
# the sentence cannot suppress a genuine reference.
NEGATOR_PATTERN = re.compile(
    r"\b(?:not|never|no\s+longer|wasn'?t|isn'?t|aren'?t|weren'?t|didn'?t|doesn'?t|don'?t)\b"
    r"(?:\s+\w+){0,3}\s*$",
    re.IGNORECASE,
)


def _is_negated(text: str, match: str) -> bool:
    """True if the first occurrence of ``match`` is directly negated.

    ``match`` comes from ``re.findall``, so it may be a group rather than the
    whole match; search for it and inspect the preceding window.
    """
    if not match:
        return False
    idx = text.find(match.lower())
    if idx <= 0:
        return False
    window = text[max(0, idx - 40):idx]
    return bool(NEGATOR_PATTERN.search(window))


# Every pattern that participates in cleaning or safety screening. They live at
# module scope on purpose: a malformed regex then raises ImportError here, at
# import time. Compiled inside a function instead, the same regex error would be
# raised per row, absorbed by ``process_rows``, and the ingest would finish
# reporting "0 rows processed" with a success exit code.
REGEX_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "HEADER_PATTERNS": HEADER_PATTERNS,
    "ANONYMISER_BOILERPLATE": ANONYMISER_BOILERPLATE,
    "UNDERAGE_INDICATORS": UNDERAGE_INDICATORS,
    "EXTREME_VIOLENCE_INDICATORS": EXTREME_VIOLENCE_INDICATORS,
    "MANUAL_REVIEW_INDICATORS": MANUAL_REVIEW_INDICATORS,
    "EXPLICIT_PATTERN": [EXPLICIT_PATTERN],
}


def validate_patterns() -> None:
    """Raise RuntimeError if any registered pattern is unusable.

    Called at import. A compile error already surfaces here because the patterns
    are module scope; this additionally catches a pattern that compiles but
    cannot be executed, and an empty rule list (which would silently disable
    a whole safety gate).
    """
    problems: list[str] = []
    for name, patterns in REGEX_PATTERNS.items():
        if not patterns:
            problems.append(f"{name} is empty; this rule list would match nothing")
            continue
        for index, pattern in enumerate(patterns):
            if not isinstance(pattern, re.Pattern):
                problems.append(
                    f"{name}[{index}] is {type(pattern).__name__}, not a compiled pattern")
                continue
            try:
                pattern.search("")
                pattern.search("the quick brown fox jumped over 3 lazy dogs")
            except re.error as exc:
                problems.append(f"{name}[{index}]: {exc}")
    if problems:
        raise RuntimeError(
            "invalid regex configuration in pipeline.profiler:\n  "
            + "\n  ".join(problems))


validate_patterns()


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

        # 4b. Remove remailer/anonymiser boilerplate. Applied to the whole text
        # (not just the header window) because these footers can appear at the
        # end of a post, and they carry strings that trip the safety screen.
        for pattern in ANONYMISER_BOILERPLATE:
            text = pattern.sub("", text)

        # 5. Fix common OCR / encoding mojibake glitches
        text = text.replace("â€™", "'").replace("â€œ", '"').replace("â€", '"').replace("â€”", "—")
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 6. Normalize paragraph breaks (max 2 consecutive newlines)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
        cleaned = "\n\n".join(paragraphs)

        return cleaned

    @staticmethod
    def audit_safety(text: str, tags: list[str] = None) -> SafetyAudit:
        """Evaluate text and tags against ethical, safety, and legal constraints.

        Three outcomes, in order of precedence:

        - ``FAIL_UNDERAGE_RISK`` — fail-closed. Any underage/CSAM indicator, or
          an underage category tag. A false negative here is a compliance
          failure, so this gate is deliberately over-inclusive relative to the
          others.
        - ``FAIL_EXTREME_VIOLENCE`` — genuinely prohibited content
          (necrophilia, snuff, bestiality, zoophilia).
        - ``FLAGGED_MANUAL_REVIEW`` — ambiguous but legal language (abuse, rape,
          murder, assault, suicide). Quarantined from all inspiration-facing
          views exactly like a FAIL, but distinguishable so a reviewer can
          triage rather than treat it as prohibited.
        """
        tags_list = tags or []
        tags_str = " ".join(tags_list).lower()
        full_content = f"{tags_str} {text.lower()}"

        flagged_terms = []

        # Check tag-level indicators (e.g. category 'adult-youth', 'highschool').
        # Matched on word boundaries, not substrings: a substring test made
        # "youthful" match the "youth" keyword and fail an unrelated story.
        for tag in tags_list:
            tag_clean = tag.lower().strip()
            tag_words = set(re.findall(r"[a-z0-9]+", tag_clean))
            if tag_words & UNDERAGE_TAG_KEYWORDS:
                flagged_terms.append(tag_clean)

        for pat in UNDERAGE_INDICATORS:
            matches = pat.findall(full_content)
            if matches:
                # Drop matches that are directly negated ("he was not fifteen").
                # Scoped narrowly to an immediately-preceding negator so it
                # cannot suppress a genuine reference elsewhere in the text.
                kept = [m for m in matches if not _is_negated(full_content, m)]
                if kept:
                    flagged_terms.extend(kept)

        if flagged_terms:
            return SafetyAudit(
                verdict=SafetyVerdict.FAIL_UNDERAGE_RISK, reasons=["Underage indicator or CSAM legal compliance risk detected."], flagged_terms=list(set(flagged_terms))
            )

        for pat in EXTREME_VIOLENCE_INDICATORS:
            matches = pat.findall(full_content)
            if matches:
                return SafetyAudit(
                    verdict=SafetyVerdict.FAIL_EXTREME_VIOLENCE, reasons=["Non-consensual extreme violence / prohibited content detected."], flagged_terms=list(set(matches))
                )

        review_terms = []
        for pat in MANUAL_REVIEW_INDICATORS:
            matches = pat.findall(full_content)
            if matches:
                review_terms.extend(matches)

        if review_terms:
            return SafetyAudit(
                verdict=SafetyVerdict.FLAGGED_MANUAL_REVIEW,
                reasons=["Ambiguous violence/abuse language; requires human review."],
                flagged_terms=list(set(review_terms)),
            )

        return SafetyAudit(verdict=SafetyVerdict.PASS)

    @staticmethod
    def extract_metadata_from_headers(raw_text: str, default_title: str = "", default_author: str = "") -> tuple[str, str]:
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
    def calculate_text_metrics(cls, text: str, density_scan_chars: int = None) -> dict[str, Any]:
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
        explicit_count = sum(1 for w in density_words if EXPLICIT_PATTERN.match(w))
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
