# Story Analysis

A comprehensive pipeline for processing, analyzing, and generating insights from narrative story data. This project provides tools for corpus ingestion, safety filtering, quality scoring, semantic search, and TTS preparation at scale.

## Overview

The **Story Analysis** project is designed to handle large-scale processing of narrative content (300K+ stories) with a focus on:

- **Safety**: Content filtering and classification to prevent harmful material
- **Quality**: Automated scoring and ranking of stories based on narrative metrics
- **Deduplication**: Identifying and handling duplicate content
- **Semantic Search**: Vector embeddings and similarity search
- **TTS Preparation**: Converting text to speech-ready formats

## Repository Structure

```
story-analysis/
├── pipeline/              # Per-story processing modules
│   ├── cli.py             # Command-line interface for pipeline operations
│   ├── profiler.py        # Story profiling, cleaning, and safety screening
│   ├── quality.py         # Quality metrics and scoring
│   ├── dedup.py           # Deduplication logic
│   ├── tagging.py         # Tag classification and management
│   ├── tts_prioritizer.py # TTS candidate prioritization
│   ├── embeddings.py      # Embedding generation
│   └── schemas.py         # Data schemas and types
│
├── insights/              # Full-corpus platform
│   ├── corpus_prep.py     # Streaming ingestion and corpus preparation
│   ├── analysis.py        # Corpus-wide analysis
│   ├── semantic.py        # Semantic search and similarity
│   ├── ner.py             # Named entity recognition
│   ├── tts_audition.py    # TTS audition interface
│   └── ui.py              # Internal web UI
│
├── embedding/             # Vector embedding and search
│   ├── data.py            # Test embedding data
│   ├── data_loading.py    # Streaming Parquet shard and JSONL sample readers
│   ├── faiss_demo.py      # FAISS vector search demonstration
│   ├── get_chuncks.py     # Chunk extraction utilities
│   ├── get_vectors.py     # Vector generation utilities
│   ├── search.py          # Production Faiss chunk search CLI and facade
│   ├── search_engine.py   # End-to-end query -> encoder -> index search engine
│   ├── text_encoder.py    # Jina v5 query and document text encoder
│   └── vector_index.py    # Faiss exact cosine-similarity chunk index
│
├── parse/                 # Document parsing
│   └── parse.py           # Unstructured document parsing client
│
├── scripts/               # Operational scripts
│   ├── ingest.sh          # Full-corpus ingestion wrapper
│   └── measure_safety.py  # Safety filter measurement and analysis
│
├── tests/                 # Test suite
│   ├── test_insights.py   # Tests for insights module
│   └── test_pipeline.py   # Tests for pipeline module
│
├── docs/                  # Documentation and specifications
│   ├── INGESTION_SPECIFICATION.md  # Original pipeline design
│   ├── INSIGHT_PLATFORM.md         # Platform architecture and features
│   ├── DATASET_AUDIT_REPORT.md     # Dataset audit findings
│   └── plans/             # Implementation plans (e.g., STO-1247)
│
├── samples/               # Sample data
│   ├── sample_stories.json        # Sample stories for testing
│   └── faiss_embedding_chunks_sample.jsonl  # 200 sample chunks (text)
│
├── big-query/             # BigQuery data exploration
│   └── data_exploration.ipynb     # Jupyter notebook for data analysis
│
├── types/                 # Type stubs
├── data/                  # Local data (gitignored)
│   ├── raw/               # Raw input data
│   ├── output/            # Processed output
│   ├── chunks/            # Processed chunks
│   ├── vectors/           # Generated vectors
│   └── logs/              # Run logs
│
├── .env                   # Environment configuration
├── .flox/                 # Flox environment configuration
├── package.json           # Node.js dependencies
├── pyproject.toml         # Python project configuration
├── uv.lock                # Python dependency lock file
├── CHANGELOG.md           # Change history
├── AGENTS.md              # Instructions for AI coding agents
└── COMMENTS.md            # Maintainer notes and decisions
```

## Key Features

### Pipeline Processing

The `pipeline/` directory contains the core per-story processing logic:

- **Safety Screening**: Multi-tier verdict system with `PASS`, `FLAGGED_MANUAL_REVIEW`, and `FAIL_EXTREME_VIOLENCE` classifications
- **Text Cleaning**: Removal of boilerplate, site chrome, and formatting artifacts
- **Quality Metrics**: Structural arc detection, prose richness, dialogue percentage
- **Tagging**: Genre and content classification
- **TTS Prioritization**: Ranking stories for text-to-speech conversion

### Insights Platform

The `insights/` directory provides full-corpus capabilities:

- **Streaming Ingestion**: Checkpointed, resumable ingestion with error handling
- **Banded MinHash LSH**: Efficient deduplication for large corpora
- **Semantic Search**: Vector embeddings with FAISS support
- **Named Entity Recognition**: Entity extraction and analysis
- **Internal UI**: Web interface for corpus exploration

### Embedding and Search

The `embedding/` directory contains:

- **FAISS Integration**: GPU-accelerated vector search
- **Test Data**: Sample embeddings for development and testing
- **Utilities**: Chunk extraction and vector generation tools

## Setup

### Prerequisites

- Python 3.14+
- Node.js (for UI dependencies)
- CUDA (for GPU-accelerated embeddings)

### Installation

```bash
# Clone the repository
git clone git@github.com:jgf-dev/story-analysis.git
cd story-analysis

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .
```

### Environment Configuration

Create a `.env` file with the required API keys:

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required keys:

- `HYDRA_DB_API_KEY`: Database API key
- `ES_HOST`: Elasticsearch host URL
- `ES_KB_HOST`: Elasticsearch Knowledge Base host URL
- `ES_API_KEY`: Elasticsearch API key

## Usage

### Running the Pipeline

Process a batch of stories:

```bash
# Process stories from a CSV file
python -m pipeline.cli --input data/stories.csv --output data/output/

# With custom parameters
python -m pipeline.cli --input data/stories.csv --output data/output/ \
    --limit 1000 --allow-errors
```

### Full Corpus Ingestion

Use the ingestion wrapper script:

```bash
# Run full ingestion with logging
./scripts/ingest.sh

# With custom parameters
./scripts/ingest.sh --input data/raw/stories.csv --workers 8
```

### Safety Filter Analysis

Measure safety filter performance:

```bash
# Analyze safety verdicts on a sample
python scripts/measure_safety.py --limit 5000 --json

# Get verbose output
python scripts/measure_safety.py --limit 1000 --verbose
```

### FAISS Vector Search

Run the small demonstration script:

```bash
python embedding/faiss_demo.py
```

Search the committed 200-chunk sample. The sample carries chunk text but no
vectors, so the search pipeline encodes it locally with the Jina document
prompt before searching:

```bash
# Fast smoke test: truncate chunks to 128 tokens and encode one at a time
python -m embedding.search --sample --max-length 128 --encode-batch-size 1 \
  "a first time story at summer camp" --top-k 5

# Search the full Parquet export written by embedding/get_chuncks.py
python -m embedding.search "a cabin weekend" --top-k 10
```

### Web UI

Start the internal web interface:

```bash
python -m insights.ui
```

Then open `http://localhost:5000` in your browser.

## Testing

Run the test suite:

```bash
# Run all tests
python -m pytest tests/ -q

# Run specific test module
python -m pytest tests/test_pipeline.py -v

# Run with coverage
python -m pytest tests/ --cov=pipeline --cov=insights
```

Run the linter:

```bash
# Check all files
python -m ruff check .

# Check specific files
python -m ruff check pipeline/ insights/
```

## Development

### Project Structure

- **pipeline/**: Core processing logic, designed for per-story operations
- **insights/**: Full-corpus analysis and platform features
- **embedding/**: Vector embeddings and similarity search
- **parse/**: Document parsing utilities
- **scripts/**: Operational wrappers and utilities
- **tests/**: Comprehensive test suite
- **docs/**: Specifications, plans, and documentation

### Adding New Features

1. Create a new module in the appropriate directory
2. Add corresponding tests in `tests/`
3. Update the relevant documentation
4. Record changes in `CHANGELOG.md`
5. Verify all tests pass

### Conventions

- Python 3.14+ with `from __future__ import annotations`
- PEP 585/604 type annotations (`list[str]`, `int | None`)
- Regex patterns compiled at module scope
- Long-running jobs must fail loudly (non-zero exit on failure)
- Do not commit dataset artifacts (see `.gitignore`)

## Data Flow

```
Raw Stories
    ↓
[parse/] Document Parsing
    ↓
[pipeline/profiler.py] Text Cleaning & Safety Screening
    ↓
[pipeline/quality.py] Quality Scoring
    ↓
[pipeline/tagging.py] Tag Classification
    ↓
[pipeline/dedup.py] Deduplication
    ↓
[pipeline/tts_prioritizer.py] TTS Ranking
    ↓
[insights/corpus_prep.py] Corpus Ingestion
    ↓
[insights/embeddings.py] Vector Embedding
    ↓
[insights/semantic.py] Semantic Index
    ↓
[insights/ui.py] Web Interface
```

## Recent Changes

See `CHANGELOG.md` for detailed change history.

### Latest Additions (Unreleased)

- **embedding/** directory: FAISS vector search demonstration and test data
- **samples/faiss_embedding_chunks_sample.jsonl**: 200 sample chunks with text for local encoding
- **embedding/data.py**: Test embedding vectors
- **embedding/faiss_demo.py**: FAISS search demonstration script
- **big-query/data_exploration.ipynb**: BigQuery data analysis notebook
- Updated **pyproject.toml**: Added FAISS and CUDA dependencies

### Key Improvements

- Three-tier safety verdict system (PASS, FLAGGED_MANUAL_REVIEW, FAIL)
- Reduced false positives from 43% to <1% (STO-1247)
- Checkpointed, resumable ingestion with error handling
- GPU-accelerated vector search with FAISS

## Related Projects

- **Nifty Corpus data analysis and NLP**: Linear project tracking corpus-related issues
- **Linear Issues**: STO-1245, STO-1247, STO-1248, STO-1249, STO-1250, STO-1251

## License

This project is internal and proprietary. Do not distribute.

## Contributing

See `AGENTS.md` for coding guidelines and requirements.

All changes must be recorded in `CHANGELOG.md` before being committed.

## Contact

For questions or issues, refer to the Linear project: **Nifty Corpus data analysis and NLP**
