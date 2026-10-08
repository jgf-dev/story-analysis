"""Unit and integration test suite for the story dataset ingestion pipeline."""

import unittest
import json
from pathlib import Path

from pipeline.schemas import (
    RawStory,
    SafetyVerdict,
    QualityTier,
    HeatLevel,
    AudioDurationTier
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
from pipeline.cli import load_raw_stories
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
        stories_file = Path("data/samples/sample_stories.json")
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
