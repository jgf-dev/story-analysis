# 300K Story Dataset — Executable Ingestion Pipeline Specification

**Specification Version:** 1.0.0  
**Date:** October 8, 2026  
**Author:** Data Scientist, JGF (`17ae5fbc-f51f-4587-a8a2-7e98ecc4729b`)  
**Target Repository:** `jgf-dev/story-analysis`  
**Downstream Consuming Systems:** `jgf-dev/story-builder` (Scraper/TTS), `jgf-dev/listenuplads` (Frontend)

---

## 1. Overview & System Objectives

This specification defines the production data engineering architecture for ingesting, standardizing, deduplicating, scoring, and indexing the 300,000-story gay male erotic fiction dataset.

### Core Architecture Objectives:
1. **Deterministic & Version-Controlled**: Every data transformation is scripted in pure, reproducible Python without non-deterministic side effects.
2. **Cost-Efficient Local & Batch Processing**: Avoids expensive per-token cloud LLM API calls on the 300,000 raw documents. Employs lightweight, highly optimized lexical, statistical, and vector algorithms.
3. **Memory-Bounded Streaming Execution**: Capable of processing the 18.78 GB uncompressed CSV file on commodity hardware with bounded RAM consumption (< 2 GB memory footprint).
4. **Seamless Downstream Integration**: Generates SQLite FTS5 databases (matching `story-builder`), Parquet / Delta tables (matching `story-analysis` on Databricks), and SSML-chunked JSON packages for multi-speaker TTS inference (Gemini / Cartesia).

---

## 2. End-to-End Pipeline Architecture

```
                                      [ OCI Object Storage ]
                                     (stories_clean.csv 18.8GB)
                                                 │
                                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Streaming Ingestion & Normalization Worker                                    │
│  - HTTP Byte-Range / Chunked CSV Reader (Chunk size: 5,000 records)                   │
│  - Column Mapping: id, path, category, slug, author, content, publication_date         │
│  - Metadata Recovery: Extract Title/Author from Usenet Headers if Unknown              │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Text Cleaning & Normalization Engine                                          │
│  - HTML entity decoding & NFKC unicode normalization                                   │
│  - Regex removal of Usenet headers, author notes, disclaimer lines, ASCII dividers    │
│  - Mojibake substitution (â€™ -> ', â€” -> —)                                          │
│  - Paragraph structure regularization                                                  │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: Zero-Tolerance Safety Audit Filter                                            │
│  - Underage / CSAM indicator evaluation (Strict age constructs, high-risk categories)  │
│  - Non-consensual extreme violence screening                                           │
│  - Verdict Branching: PASS -> Proceed; FAIL -> Quarantine Table                        │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: Deduplication & Near-Duplicate Clustering                                     │
│  - Normalized SHA-256 Exact Hash Deduplication                                         │
│  - Word 4-Shingle MinHash LSH (64 permutations) & Jaccard Verification (Threshold 0.80)│
│  - Canonical Selection & Series/Chapter Linking                                        │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: Multi-Dimensional Quality Evaluation & Scoring                                │
│  - Formatting & Cleanliness (0 - 20 pts)                                               │
│  - Structural Arc & Story Length (0 - 20 pts)                                          │
│  - Prose Richness & Sensory Immersion (0 - 25 pts)                                     │
│  - Dialogue & Pacing Balance (0 - 15 pts)                                              │
│  - TTS Readability & Acoustic Cadence (0 - 20 pts)                                     │
│  - Tier Classification: Tier 1 (Master), Tier 2 (Secondary), Tier 3 (Polish), Tier 4   │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 6: Taxonomy Classification & Semantic Vector Indexing                            │
│  - Rule-based Trope, Archetype, Setting, POV, and Pacing extraction                   │
│  - Heat Level scoring (Levels 1 - 4 based on explicit density)                         │
│  - TF-IDF + Bigram Semantic Vector Indexing (512 dimensions, L2 normalized)            │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 7: TTS Prioritization & Export Artifacts                                         │
│  - Top 50,000 Master Candidate Selection (Safe, Canonical, Tier 1, Score >= 75)        │
│  - Voice Profile Matching (Baritone, Husky, Mid-Atlantic, Warm Tenor)                  │
│  - Acoustic SSML Chunking (350 words/chunk, breath & paragraph pause tags)             │
│  - Output: Cleaned JSONL Catalog, SQLite DB with FTS5, Vector Index, TTS Priority Queue│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Processing Stage Specifications

### Stage 1: Streaming Ingestion & Column Mapping

The pipeline ingests raw stories from `stories_clean.csv`. To ensure zero memory exhaustion on machines with 8-16 GB RAM, ingestion uses Python generator streaming or PySpark chunked partitions.

```python
# Streaming chunked ingestion pattern
def stream_csv_chunks(file_path: str, chunk_size: int = 5000):
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        chunk = []
        for row in reader:
            chunk.append(row)
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk
```

**Metadata Fallback Logic:**
- If `title` is empty or `"Unknown"`:
  1. Check for `Subject: [STORY] ...` or `Title: ...` in text.
  2. Fall back to `story_slug.replace('-', ' ').title()`.
- If `author_name` is empty or `"Unknown"`:
  1. Check for `By: ...`, `From: ... (<Name>)`, or `(c) YEAR "Name"`.
  2. Fall back to `"Unknown / Anonymous"`.

### Stage 2: Noise Removal & Cleanliness Normalization

All raw texts pass through `StoryProfiler.clean_text`:
- `html.unescape()` decodes entities.
- `unicodedata.normalize("NFKC", text)` standardizes quotes, dashes, accents.
- Regular expressions strip HTML markup (`<br>`, `<p>`, `<div>`, `<hr>`).
- 7 Usenet header families are stripped:
  - `^(archive|date|from|subject|newsgroups|path|message-id|organization):\s+.*$`
  - `^disclaimer:\s+.*$`
  - `^(a/n|author'?s?\s*note):\s+.*$`
  - `<!--[\s\S]*?-->`
  - `^(please\s+review|leave\s+feedback|feedback\s+to|all\s+characters\s+are\s+over\s+18).*$`
  - `^[~*=\-_#]{4,}\s*$`
- Mojibake encoding correction: `â€™` $\to$ `'`, `â€œ` $\to$ `"`, `â€”` $\to$ `—`.
- Standard paragraph boundary normalization (`\n\n`).

### Stage 3: Zero-Tolerance Safety Filter

Every document is audited against ethical and legal constraints:
```python
UNDERAGE_PATTERNS = [
    re.compile(r"\b(?:1[0-5]|thirteen|fourteen|fifteen)\s*(?:-| )*(?:years?|yrs?)(?:-| )*old\b", re.IGNORECASE),
    re.compile(r"\bage[d]?\s*(?:1[0-5]|thirteen|fourteen|fifteen)\b", re.IGNORECASE),
    re.compile(r"\b(?:under\s*18|underage|prepubescent|pedophil\w*|hebephil\w*|kindergarten|elementary\s+school|middle\s+school|junior\s+high)\b", re.IGNORECASE),
    re.compile(r"\b(?:high\s+school\s+freshman|freshman\s+boy|junior\s+high\s+boy|middle\s+school\s+boy|fourteen|fifteen|thirteen)\b", re.IGNORECASE),
    re.compile(r"\b(?:boyhood|child\s+(?:abuse|victim|exploitation|porn|sex))\b", re.IGNORECASE),
]
UNDERAGE_TAG_KEYWORDS = {"adult-youth", "youth", "underage", "teen", "prepubescent", "junior-high", "highschool", "high-school"}
```
- Stories matching these patterns or tagged with prohibited keywords receive `SafetyVerdict.FAIL_UNDERAGE_RISK` and are segregated to a quarantine table.
- Stories with extreme non-consensual violence (`necrophilia`, `snuff`, `bestiality`) receive `SafetyVerdict.FAIL_EXTREME_VIOLENCE`.

### Stage 4: Deduplication & Near-Duplicate Clustering

1. **Normalized SHA-256**:
   ```python
   def compute_exact_hash(text: str) -> str:
       normalized = re.sub(r"\s+", " ", text.lower().strip())
       return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
   ```
2. **MinHash Shingling**:
   - Computes word 4-shingles.
   - Generates 64 MinHash permutations ($P = 4294967311$).
   - Computes Jaccard similarity when estimated MinHash match $\ge 0.70$.
   - Clusters stories with $\text{Jaccard} \ge 0.80$.
3. **Canonical Selection**: Highest score among cluster members is elected `is_canonical = True`; duplicate records are referenced under `cluster_id`.

### Stage 5: Multi-Dimensional Quality Scoring (0 - 100)

Composite score formula:
$$\text{Total Score} = S_{\text{formatting}} (20) + S_{\text{structure}} (20) + S_{\text{prose}} (25) + S_{\text{dialogue}} (15) + S_{\text{tts}} (20)$$

- **$S_{\text{formatting}}$**: Penalizes walls of text (-10), unstripped artifacts (-6), missing punctuation (-6).
- **$S_{\text{structure}}$**: Optimal length 800 - 6,000 words (20 pts). Novellas 6,000 - 15,000 words (18 pts). Fragments < 150 words (2 pts).
- **$S_{\text{prose}}$**: Rewards Type-Token Ratio diversity ($\ge 0.45$: +6) and sensory descriptor density ($\ge 2.5\%$: +9).
- **$S_{\text{dialogue}}$**: Audio sweet spot is 15% - 45% dialogue (15 pts); penalties for < 8% or > 65% dialogue.
- **$S_{\text{tts}}$**: Sentence length 8 - 25 words/sentence optimal. Penalizes run-on sentences > 35 words (-8).

**Tiers**:
- `Tier 1: Master Candidate`: Score $\ge 78.0$
- `Tier 2: Good Secondary`: Score $62.0 - 77.9$
- `Tier 3: Needs Polishing`: Score $45.0 - 61.9$
- `Tier 4: Reject`: Score $< 45.0$

### Stage 6: Taxonomy & Semantic Indexing

- **Tropes**: Rules classify `Enemies to Lovers`, `Friends to Lovers`, `Forced Proximity`, `Boss / Employee`, `Strangers to Lovers`, `First Time`, `Contemporary Romance`.
- **Archetypes**: `Executive / Corporate`, `Uniform / Law Enforcement`, `Athletic / Jock`, `Medical / Healthcare`, `Rugged / Outdoors`.
- **Heat Level**: Density of explicit anatomical/erotic terms:
  - $< 0.5\% \implies$ Level 1 (Sweet Romance)
  - $0.5\% - 1.8\% \implies$ Level 2 (Moderate Sensual)
  - $1.8\% - 3.5\% \implies$ Level 3 (High Heat)
  - $> 3.5\% \implies$ Level 4 (Hardcore)
- **Vector Index**: 512-dimensional TF-IDF + bigram vocabulary with L2 normalization, serialized to JSON for real-time semantic discovery.

### Stage 7: TTS Audio Chunking & Prioritization

For each candidate in the top queue:
1. Calculates recommended reading speed: 150 WPM.
2. Selects voice profile based on character archetypes.
3. Chunks story into $\approx 350$-word segments:
   - Formats SSML tags: `<speak><p>...</p><break time="650ms"/><p>...</p></speak>`.
   - Normalizes quotation marks to standard ASCII double quotes.
   - Calculates estimated audio runtime in seconds per chunk.

---

## 4. Execution Workflows & CLI Interface

### 4.1 Standalone Python Execution (Local / Virtual Machine)

```bash
# Ingest local sample dataset
python3 -m pipeline.cli \
  --input data/samples/sample_stories.json \
  --output-dir data/output \
  --export-tts-chunks

# Ingest full CSV or bounded slice
python3 -m pipeline.cli \
  --input /path/to/stories_clean.csv \
  --limit 50000 \
  --output-dir data/output \
  --min-tts-score 78.0 \
  --export-tts-chunks
```

### 4.2 Databricks PySpark Distributed Execution (`jgf-dev/story-analysis`)

For running on the Databricks cluster configured in `story-analysis` (`https://dbc-e4419c7a-65f4.cloud.databricks.com`):

```python
# Databricks Spark Job implementation:
from pyspark.sql import SparkSession
from pyspark.sql.functions import udf
from pyspark.sql.types import StructType, StructField, StringType, FloatType, BooleanType

spark = SparkSession.builder.appName("300K_Story_Ingestion").getOrCreate()

# 1. Read OCI CSV mount
df = spark.read.option("header", "true").option("multiLine", "true").csv("dbfs:/mnt/oci/stories_clean.csv")

# 2. Partition and apply UDF transformations
# Orchestrator runs across worker nodes
```

---

## 5. Database Schema & Storage Layout

### 5.1 Cleaned SQLite FTS5 Schema (`catalog.db`)

Aligned with `story-builder` and `listenuplads`:

```sql
CREATE TABLE stories (
    id                      TEXT PRIMARY KEY,
    original_id             TEXT,
    title                   TEXT NOT NULL,
    author                  TEXT NOT NULL,
    clean_text              TEXT NOT NULL,
    word_count              INTEGER,
    estimated_audio_min     REAL,
    quality_score           REAL,
    quality_tier            TEXT,
    safety_verdict          TEXT,
    heat_level              INTEGER,
    point_of_view           TEXT,
    pacing                  TEXT,
    primary_trope           TEXT,
    character_archetype     TEXT,
    recommended_voice       TEXT,
    is_canonical            BOOLEAN,
    cluster_id              TEXT
);

-- Full Text Search virtual table
CREATE VIRTUAL TABLE stories_fts USING fts5(
    title,
    author,
    clean_text,
    primary_trope,
    character_archetype,
    content='stories',
    content_rowid='rowid'
);
```

### 5.2 Parquet Partition Strategy (Analytics & Embeddings)

```text
data/catalog/
├── tier=Tier 1: Master Candidate/
│   ├── category=athletics/part-0000.parquet
│   ├── category=college/part-0000.parquet
│   └── category=first-time/part-0000.parquet
├── tier=Tier 2: Good Secondary/
│   └── ...
└── quarantine_safety_fails/
    └── part-0000.parquet
```

---

## 6. Verification & Test Plan

The pipeline is verified by a 16-test automated suite (`tests/test_pipeline.py`):
1. **`test_clean_html_and_headers`**: Verifies removal of Usenet headers, HTML tags, and divider noise.
2. **`test_safety_audit_underage_rejection`**: Verifies zero-tolerance rejection of underage terms.
3. **`test_safety_audit_adult_pass`**: Verifies safe adult stories pass.
4. **`test_safety_audit_numbers_not_misflagged`**: Verifies numbers ("10:00 PM", "12 miles") are not falsely flagged.
5. **`test_safety_audit_youth_tag_flagged`**: Verifies category keywords (`adult-youth`) trigger rejection.
6. **`test_extract_metadata_from_headers`**: Verifies recovery of title and author from Usenet headers and bylines.
7. **`test_text_metrics_calculation`**: Verifies word count, dialogue ratio, and sensory density.
8. **`test_exact_deduplication`**: Verifies identical hash detection.
9. **`test_near_duplicate_detection`**: Verifies MinHash and Jaccard clustering at 0.75-0.80.
10. **`test_high_quality_story`**: Verifies Tier 1 classification on rich narrative prose.
11. **`test_low_quality_wall_penalty`**: Verifies wall-of-text penalty and Tier 4 rejection.
12. **`test_trope_and_archetype_tagging`**: Verifies multi-attribute taxonomy detection.
13. **`test_ssml_chunking`**: Verifies valid SSML markup generation and paragraph pauses.
14. **`test_filter_and_rank`**: Verifies priority queue filtering excludes safety violations and duplicates.
15. **`test_vectorizer_and_search`**: Verifies TF-IDF cosine similarity search and story recommendations.
16. **`test_load_csv_stories`**: Verifies RFC 4180 CSV parsing and automatic field mapping.

All 16 tests pass deterministically in `< 0.1` seconds.
