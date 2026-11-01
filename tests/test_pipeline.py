"""Unit and integration test suite for the story dataset ingestion pipeline."""

import unittest
import json
import contextlib
import io
import sys
from pathlib import Path

from pipeline.schemas import (
    RawStory,
    SafetyVerdict,
    QualityTier,
    HeatLevel,
    AudioDurationTier,
    ProcessedStory,
    SafetyAudit,
    QualityBreakdown,
)
from pipeline.profiler import StoryProfiler
from pipeline.dedup import (
    compute_exact_hash,
    generate_shingles,
    jaccard_similarity,
    MinHashSignature,
    StoryDeduplicator
)
from pipeline.quality import StoryQualityScorer
from pipeline.tagging import StoryTaxonomyTagger
from pipeline.tts_prioritizer import TTSPrioritizer
from pipeline.orchestrator import PipelineOrchestrator
from pipeline.embeddings import VectorIndex, PurePythonVectorizer
from pipeline.cli import load_raw_stories, main as cli_main
import tempfile
import csv


class TestStoryProfiler(unittest.TestCase):
    def test_clean_html_and_headers(self):
        dirty = """Archive: alt.sex.stories
Date: 12 Jan 2001
From: user@test.com
Subject: [Story] The Cabin
A/N: Thanks for reading!
*~*~*~*~*~*~*~*~*~*~*~*~*~*
<p>He stepped into the <b>warm</b> room.</p>
<p>\"Hello,\" he said.</p>
[Reposted from web]"""
        cleaned = StoryProfiler.clean_text(dirty)
        self.assertNotIn("Archive:", cleaned)
        self.assertNotIn("<p>", cleaned)
        self.assertNotIn("<b>", cleaned)
        self.assertNotIn("*~*~*", cleaned)
        self.assertIn("He stepped into the warm room.", cleaned)
        self.assertIn('"Hello," he said.', cleaned)

    def test_safety_audit_underage_rejection(self):
        text = "Tommy was a 14-year-old freshman in high school."
        audit = StoryProfiler.audit_safety(text, tags=["teen", "school"])
        self.assertEqual(audit.verdict, SafetyVerdict.FAIL_UNDERAGE_RISK)
        self.assertTrue(len(audit.reasons) > 0)

    def test_safety_audit_adult_pass(self):
        text = "Marcus, thirty-two years old, poured another cup of coffee."
        audit = StoryProfiler.audit_safety(text, tags=["romance", "contemporary"])
        self.assertEqual(audit.verdict, SafetyVerdict.PASS)

    def test_safety_audit_numbers_not_misflagged(self):
        text = "He arrived at 10:00 PM after walking 12 miles. There was a minor detail to resolve."
        audit = StoryProfiler.audit_safety(text, tags=["adult", "contemporary"])
        self.assertEqual(audit.verdict, SafetyVerdict.PASS)

    def test_safety_audit_youth_tag_flagged(self):
        text = "They sat together talking about life."
        audit = StoryProfiler.audit_safety(text, tags=["adult-youth"])
        self.assertEqual(audit.verdict, SafetyVerdict.FAIL_UNDERAGE_RISK)

    def test_extract_metadata_from_headers(self):
        text = """Subject: [STORY] Secret Desires at Midnight
From: user@net.com (Alexander Vance)
(c) 1995 Alexander Vance

The room was quiet."""
        title, author = StoryProfiler.extract_metadata_from_headers(text)
        self.assertEqual(title, "Secret Desires at Midnight")
        self.assertEqual(author, "Alexander Vance")

    def test_text_metrics_calculation(self):
        text = 'Marcus looked up with dark eyes. "You took your time out there," he whispered softly, his skin warm.'
        metrics = StoryProfiler.calculate_text_metrics(text)
        self.assertTrue(metrics["word_count"] > 10)
        self.assertTrue(metrics["dialogue_ratio"] > 0.0)
        self.assertTrue(metrics["sensory_density"] > 0.0)
        self.assertTrue(metrics["ttr"] > 0.5)


# (text, tags, expected verdict, label)
FALSE_POSITIVES = [
    ("After fifteen minutes of getting his ass plowed", [], SafetyVerdict.PASS,
     "duration, not an age"),
    ("his number was thirteen", [], SafetyVerdict.PASS,
     "jersey number"),
    ("the lamp only cost fourteen", [], SafetyVerdict.PASS,
     "price"),
    ("Raphael was thirteen penis-lengths tall", [], SafetyVerdict.PASS,
     "unit of measurement"),
    ("Um... it's six-fifteen", [], SafetyVerdict.PASS,
     "clock time"),
    ("report inappropriate use to abuse@anon.penet.fi", [], SafetyVerdict.PASS,
     "anonymiser footer"),
]

# Ambiguous-but-legal violence language. Not a FAIL verdict, but quarantined
# for review rather than passed — see REQ-007.
REVIEW_CASES = [
    ("Sgt Bullock continued his assault on the hard throbbing cock", [],
     SafetyVerdict.FLAGGED_MANUAL_REVIEW, "erotic metaphor"),
    ("He screamed bloody murder into my gag", [],
     SafetyVerdict.FLAGGED_MANUAL_REVIEW, "idiom"),
    ("he would murder me", [],
     SafetyVerdict.FLAGGED_MANUAL_REVIEW, "hyperbole"),
]

# Genuinely prohibited content must still hard-fail.
PROHIBITED_CASES = [
    ("a story about necrophilia", [], SafetyVerdict.FAIL_EXTREME_VIOLENCE,
     "necrophilia"),
    ("snuff film content", [], SafetyVerdict.FAIL_EXTREME_VIOLENCE,
     "snuff"),
    ("bestiality with a dog", [], SafetyVerdict.FAIL_EXTREME_VIOLENCE,
     "bestiality"),
]

TRUE_POSITIVES = [
    ("Tommy was a 14-year-old freshman in high school.", ["teen", "school"],
     SafetyVerdict.FAIL_UNDERAGE_RISK, "explicit age + school"),
    ("he was fifteen years old", [], SafetyVerdict.FAIL_UNDERAGE_RISK,
     "explicit age phrase"),
    ("They sat together talking about life.", ["adult-youth"],
     SafetyVerdict.FAIL_UNDERAGE_RISK, "underage category tag"),
    ("girls under 18", [], SafetyVerdict.FAIL_UNDERAGE_RISK,
     "under-18 phrase"),
    ("Marcus, thirty-two years old, poured another cup of coffee.",
     ["romance", "contemporary"], SafetyVerdict.PASS, "adult control"),
]


# Genuine age assertions that must keep failing. These were briefly lost
# when the bare-numeral rule was removed outright: 288 rows containing
# "I was fifteen" / "who was 15" started passing. The age-verb rule restores
# them while still excluding durations and measurements.
AGE_ASSERTIONS = [
    ("he was fifteen", [], SafetyVerdict.FAIL_UNDERAGE_RISK, "was + word"),
    ("I was fifteen and on the swim team", [], SafetyVerdict.FAIL_UNDERAGE_RISK,
     "was + word in prose"),
    ("who was 15, with us", [], SafetyVerdict.FAIL_UNDERAGE_RISK, "was + digit"),
    ("when I was fourteen", [], SafetyVerdict.FAIL_UNDERAGE_RISK, "when I was"),
    ("he turned fourteen", [], SafetyVerdict.FAIL_UNDERAGE_RISK, "turned"),
    ("he was not fifteen", [], SafetyVerdict.PASS, "negated age"),
]

# Durations and measurements that must NOT fail.
NON_AGE_NUMERALS = [
    ("he had been doing for fifteen years already", [], SafetyVerdict.PASS,
     "years of duration"),
    ("need about fifteen more chapters", [], SafetyVerdict.PASS,
     "count of chapters"),
    ("he waited fifteen seconds", [], SafetyVerdict.PASS, "seconds"),
]


class TestSafetyFilterPrecision(unittest.TestCase):
    """STO-1247: the safety filter must not fail ordinary prose.

    Each case is a class of false positive measured on the real corpus, paired
    with the true-positive cases that must keep failing. The filter is
    deliberately fail-closed on underage content, so a false negative is worse
    than a false positive — these tests assert both directions.
    """

    def test_false_positive_classes_do_not_fail(self):
        for text, tags, expected, label in FALSE_POSITIVES:
            with self.subTest(label=label):
                audit = StoryProfiler.audit_safety(text, tags)
                self.assertEqual(
                    audit.verdict, expected,
                    f"{label}: {text!r} -> {audit.verdict.value} "
                    f"(flagged: {audit.flagged_terms})")

    def test_ambiguous_violence_routes_to_review_not_fail(self):
        """REQ-001: these must not be a FAIL verdict, but must be quarantined."""
        for text, tags, expected, label in REVIEW_CASES:
            with self.subTest(label=label):
                audit = StoryProfiler.audit_safety(text, tags)
                self.assertEqual(
                    audit.verdict, expected,
                    f"{label}: {text!r} -> {audit.verdict.value}")
                self.assertNotEqual(audit.verdict, SafetyVerdict.PASS,
                                    f"{label} must not pass unreviewed")

    def test_prohibited_content_still_hard_fails(self):
        for text, tags, expected, label in PROHIBITED_CASES:
            with self.subTest(label=label):
                audit = StoryProfiler.audit_safety(text, tags)
                self.assertEqual(
                    audit.verdict, expected,
                    f"{label}: {text!r} -> {audit.verdict.value}")

    def test_true_positive_classes_still_fail(self):
        for text, tags, expected, label in TRUE_POSITIVES:
            with self.subTest(label=label):
                audit = StoryProfiler.audit_safety(text, tags)
                self.assertEqual(
                    audit.verdict, expected,
                    f"{label}: {text!r} -> {audit.verdict.value}")

    def test_age_assertions_still_fail(self):
        for text, tags, expected, label in AGE_ASSERTIONS:
            with self.subTest(label=label):
                audit = StoryProfiler.audit_safety(text, tags)
                self.assertEqual(
                    audit.verdict, expected,
                    f"{label}: {text!r} -> {audit.verdict.value}")

    def test_non_age_numerals_do_not_fail(self):
        for text, tags, expected, label in NON_AGE_NUMERALS:
            with self.subTest(label=label):
                audit = StoryProfiler.audit_safety(text, tags)
                self.assertEqual(
                    audit.verdict, expected,
                    f"{label}: {text!r} -> {audit.verdict.value}")

    def test_negation_is_adjacency_scoped(self):
        """A negator must not suppress a genuine reference elsewhere."""
        audit = StoryProfiler.audit_safety(
            "he was not fifteen, but his brother was fourteen", [])
        self.assertEqual(audit.verdict, SafetyVerdict.FAIL_UNDERAGE_RISK)

    def test_anonymiser_footer_is_stripped_before_screening(self):
        """The footer must not survive cleaning, or it reaches the screen."""
        raw = ("From: x@anon.penet.fi\n"
               "*Automatically* ANONYMIZED. Please, report inappropriate use to\n"
               "abuse@anon.penet.fi For information write to help@anon.penet.fi\n\n"
               "He walked into the bar and saw the jock standing there.\n")
        cleaned = StoryProfiler.clean_text(raw)
        self.assertNotIn("anon.penet.fi", cleaned)
        self.assertNotIn("report inappropriate use", cleaned.lower())
        self.assertIn("walked into the bar", cleaned)
        self.assertEqual(StoryProfiler.audit_safety(cleaned, []).verdict,
                         SafetyVerdict.PASS)

    def test_tag_matching_is_not_substring_based(self):
        """'youthful' must not match the 'youth' keyword."""
        audit = StoryProfiler.audit_safety("They talked about the weather.", ["youthful"])
        self.assertEqual(audit.verdict, SafetyVerdict.PASS,
                         "'youthful' is not an underage category tag")


class TestDeduplication(unittest.TestCase):
    def test_exact_deduplication(self):
        dedup = StoryDeduplicator(near_dup_threshold=0.80)
        story_text = "The mountain air had turned bitter by four in the afternoon."

        is_can1, cluster1, sim1 = dedup.process_story("id_1", story_text)
        self.assertTrue(is_can1)
        self.assertEqual(cluster1, "id_1")

        is_can2, cluster2, sim2 = dedup.process_story("id_2", story_text)
        self.assertFalse(is_can2)
        self.assertEqual(cluster2, "id_1")
        self.assertEqual(sim2, 1.0)

    def test_near_duplicate_detection(self):
        dedup = StoryDeduplicator(near_dup_threshold=0.75)
        text_a = "Julian pulled his wool collar tighter as the mountain wind whipped across the porch of the remote Tahoe cabin. Marcus was waiting inside with hot coffee."
        text_b = "Julian pulled his wool collar tighter as the mountain wind whipped across the porch of the remote Tahoe cabin. Marcus was waiting inside with steaming hot coffee."

        is_can_a, cl_a, _ = dedup.process_story("story_a", text_a)
        self.assertTrue(is_can_a)

        is_can_b, cl_b, sim_b = dedup.process_story("story_b", text_b)
        self.assertFalse(is_can_b)
        self.assertEqual(cl_b, "story_a")
        self.assertTrue(sim_b >= 0.75)


class TestQualityScorer(unittest.TestCase):
    def test_high_quality_story(self):
        text = """The mountain air had turned bitter by four in the afternoon. Julian pulled his wool collar tighter as the wind whipped across the porch of the remote Tahoe cabin.

Inside, the hearth was already blazing. Marcus looked up from the wooden kitchen counter, where two mugs of black coffee were steaming against the chill. His sleeves were rolled past his forearms, dark curls damp from the hike.

\"You took your time out there,\" Marcus said quietly, his voice low and raspy in the quiet room. \"I was starting to think you got lost in the pines.\"

Julian closed the heavy timber door behind him, bolting it against the storm. He stepped closer, shaking off the cold. \"Not lost. Just thinking.\"

Marcus set his mug down with a soft click. His gaze lingered on Julian's lips, then lifted to meet his eyes. The tension that had simmered between them for three days suddenly felt electric. \"Stop thinking so much.\"

The warmth radiating from Marcus was intoxicating, smelling of cedarwood, bitter coffee, and rain. Marcus reached up, pressing his warm palm against Julian's cold cheek. Julian let out a shaky exhale."""
        metrics = StoryProfiler.calculate_text_metrics(text)
        score = StoryQualityScorer.evaluate(text, metrics)
        self.assertTrue(score.total_score >= 70.0)
        self.assertIn(score.tier, [QualityTier.TIER_1_MASTER, QualityTier.TIER_2_SECONDARY])

    def test_low_quality_wall_penalty(self):
        text = "i went to the gym today and saw this guy and we worked out then went to the shower and then did stuff it was hot the end"
        metrics = StoryProfiler.calculate_text_metrics(text)
        score = StoryQualityScorer.evaluate(text, metrics)
        self.assertTrue(score.total_score < 50.0)
        self.assertEqual(score.tier, QualityTier.TIER_4_REJECT)


class TestTaxonomyTagger(unittest.TestCase):
    def test_trope_and_archetype_tagging(self):
        text = "The elevator ground to a halt between the floors. Christian adjusted his bespoke silk tie, staring at Liam, his rival senior partner. 'You've been glaring at me for six months.'"
        metrics = StoryProfiler.calculate_text_metrics(text)
        tax = StoryTaxonomyTagger.tag_story(
            text=text,
            title="The Penthouse Elevator",
            raw_tags=["rivals", "office"],
            metrics=metrics
        )
        self.assertIn("Enemies to Lovers", tax.primary_tropes)
        self.assertIn("Forced Proximity", tax.primary_tropes)
        self.assertIn("Executive / Corporate", tax.character_archetypes)
        self.assertEqual(tax.duration_tier, AudioDurationTier.MICRO)


class TestTTSPrioritizer(unittest.TestCase):
    def test_ssml_chunking(self):
        text = "Paragraph one of the story is here.\n\nParagraph two follows shortly.\n\nParagraph three concludes the scene."
        chunks = TTSPrioritizer.chunk_story_for_tts(text, max_words_per_chunk=10)
        self.assertTrue(len(chunks) >= 2)
        self.assertTrue("<speak>" in chunks[0]["ssml_payload"])
        self.assertTrue("<p>" in chunks[0]["ssml_payload"])

    def test_filter_and_rank(self):
        stories_file = Path("samples/sample_stories.json")
        with open(stories_file, "r") as f:
            raw_data = json.load(f)
        raw_stories = [RawStory(**d) for d in raw_data]

        orchestrator = PipelineOrchestrator()
        processed = orchestrator.process_batch(raw_stories)
        ranked = TTSPrioritizer.filter_and_rank_candidates(processed, min_quality_score=65.0)

        # Confirm safety violation story and duplicates are not in ranked candidates
        for r in ranked:
            self.assertEqual(r.safety.verdict, SafetyVerdict.PASS)
            self.assertTrue(r.is_canonical)
            self.assertNotEqual(r.id, "raw_story_005_safety_violation")
            self.assertNotEqual(r.id, "raw_story_003_near_duplicate")

    def test_review_verdict_is_quarantined_from_tts_queue(self):
        """REQ-007: FLAGGED_MANUAL_REVIEW must be excluded like a FAIL.

        Every downstream consumer gates on `== PASS`, so a new non-PASS verdict
        is quarantined by construction — but that is an assumption until tested.
        """
        def story(sid, verdict, score=90.0):
            return ProcessedStory(
                id=sid, original_id=sid, title=f"T {sid}", author="A",
                clean_text="He walked into the bar. " * 40,
                word_count=200, char_count=1000, paragraph_count=4,
                exact_hash="h", cluster_id=sid, is_canonical=True,
                safety=SafetyAudit(verdict=verdict),
                quality=QualityBreakdown(20, 20, 25, 15, 20, score,
                                         QualityTier.TIER_1_MASTER),
            )

        stories = [
            story("pass", SafetyVerdict.PASS),
            story("review", SafetyVerdict.FLAGGED_MANUAL_REVIEW),
            story("underage", SafetyVerdict.FAIL_UNDERAGE_RISK),
            story("violence", SafetyVerdict.FAIL_EXTREME_VIOLENCE),
        ]
        ranked = TTSPrioritizer.filter_and_rank_candidates(stories, min_quality_score=75.0)
        ids = {r.id for r in ranked}
        self.assertIn("pass", ids)
        self.assertNotIn("review", ids, "FLAGGED_MANUAL_REVIEW must not reach the TTS queue")
        self.assertNotIn("underage", ids)
        self.assertNotIn("violence", ids)

    def test_export_prunes_stale_chunks(self):
        """A run over a different input must not leave the previous run's
        chunks behind: the directory is keyed by story id and never pruned, so
        stale files would otherwise be indistinguishable from current output."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            chunks = out / "tts_chunks"
            chunks.mkdir(parents=True)
            # a chunk from a previous run, including one for a safety failure
            (chunks / "9999_stale_chunks.json").write_text("[]")
            (chunks / "raw_story_005_safety_violation_chunks.json").write_text("[]")

            buf = io.StringIO()
            # invoke via argv so argparse defaults apply
            argv = sys.argv
            sys.argv = ["cli", "--input", "samples/sample_stories.json",
                        "--output-dir", str(out), "--export-tts-chunks"]
            try:
                with contextlib.redirect_stdout(buf):
                    cli_main()
            finally:
                sys.argv = argv

            remaining = {p.name for p in chunks.glob("*_chunks.json")}
            self.assertNotIn("9999_stale_chunks.json", remaining)
            self.assertNotIn("raw_story_005_safety_violation_chunks.json", remaining)
            # every remaining chunk corresponds to a PASS candidate
            self.assertTrue(remaining)
            for name in remaining:
                self.assertNotIn("safety_violation", name)


class TestVectorIndex(unittest.TestCase):
    def test_vectorizer_and_search(self):
        stories = [
            {
                "id": "story_1",
                "title": "Cabin Romance in the Woods",
                "clean_text": "Julian and Marcus stayed in the snowy cabin with hot coffee and a warm hearth.",
                "taxonomy": {"primary_tropes": ["Friends to Lovers", "Forced Proximity"]},
                "quality": {"total_score": 85.0},
                "tts": {"estimated_duration_min": 15.0}
            },
            {
                "id": "story_2",
                "title": "Corporate Boardroom Rivalry",
                "clean_text": "Christian and Liam fought for the executive promotion in the skyscraper elevator.",
                "taxonomy": {"primary_tropes": ["Enemies to Lovers", "Boss / Employee"]},
                "quality": {"total_score": 88.0},
                "tts": {"estimated_duration_min": 12.0}
            }
        ]
        index = VectorIndex().build_from_stories(stories)
        results = index.search("cabin snowy hearth", top_k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "story_1")

        recommendations = index.recommend_similar("story_1", top_k=1)
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["id"], "story_2")


class TestCSVLoading(unittest.TestCase):
    def test_load_csv_stories(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False) as tf:
            writer = csv.writer(tf)
            writer.writerow([
                "id", "path", "orientation", "category", "story_slug",
                "chapter_num", "title", "author_name", "author_email",
                "publication_date", "url", "char_count", "word_count", "content"
            ])
            writer.writerow([
                "101", "nifty/gay/athletics/test.txt", "gay", "athletics",
                "working-on-my-lunge", "", "Unknown", "Unknown", "",
                "1990-07-24", "https://nifty.org/test", "1500", "300",
                "Subject: [STORY] Working On My Lunge\nBy: John Thomas\n\nHe entered the gym."
            ])
            temp_path = tf.name

        try:
            stories = load_raw_stories(temp_path)
            self.assertEqual(len(stories), 1)
            self.assertEqual(stories[0].id, "101")
            self.assertEqual(stories[0].title, "Working On My Lunge")
            self.assertEqual(stories[0].author, "John Thomas")
            self.assertIn("athletics", stories[0].tags)
        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
