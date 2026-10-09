# JGF Dataset Insight Platform (JGF-12)

Internal research tooling that turns the 300K-story reference corpus into
browsable insight for authoring **new and adapted** stories. The corpus has
unknown copyright and is **never** shipped, distributed, or exposed to users.
This platform is internal-only and runs locally.

## What it does

| Layer | Module | Output |
| --- | --- | --- |
| Corpus prep | `insights/corpus_prep.py` | `data/catalog.sqlite` (deduped, tagged catalogue) |
| Analysis | `insights/analysis.py` | `insights_output/analysis/analysis.json` |
| Semantic embeddings + clusters | `insights/semantic.py` | `insights_output/vectors.npz`, `clusters.json`, `pipeline.pkl` |
| NER + combination search | `insights/ner.py` | `entity_mentions` table in the catalogue |
| Internal UI + TTS audition | `insights/ui.py`, `insights/tts_audition.py` | local web app on `127.0.0.1:8765` |

The per-story transformations (cleaning, safety audit, metrics, quality tier,
taxonomy tags) are reused from the `pipeline/` package built in JGF-4.

## Corpus prep (streaming, resumable)

`insights/corpus_prep.py` reads the ~18.8 GB `stories_clean.csv` in a single
bounded-memory pass:

1. **Parse** — RFC-quote-balanced record reader with byte-offset checkpoints
   (`meta.ingest_state`), so an interrupted run resumes where it stopped.
2. **Clean** — HTML/entity decode, NFKC, mojibake fixes, Usenet/author-note
   header stripping, paragraph normalisation. Header patterns are scanned on
   the first 3,000 chars per post (headers live at the top) for speed.
3. **Safety audit** — zero-tolerance underage/CSAM and extreme-violence
   screening. Flagged rows are retained as metadata only and excluded from all
   inspiration-facing views.
4. **Metrics + quality + tags** — word counts, dialogue ratio, TTR, sensory and
   explicit density, the 0–100 quality rubric and Tier 1–4 classification,
   tropes/archetypes/settings, POV, pacing, heat, duration tier.
5. **Dedup** — normalised SHA-256 exact-hash dedup plus global **MinHash +
   banded LSH** near-duplicate detection (128 permutations, 4-row bands,
   0.80 signature-similarity threshold). MinHash uses 32-bit Mersenne
   coefficients specifically to avoid the uint64 overflow that biases every
   permutation identically.
6. **Store** — one `stories` row per source record (canonical or duplicate);
   full text stored zlib-compressed **only** for canonical, safety-passing
   Tier 1/2 stories ≥ 150 words, capped at 400 KB.

Run:

```bash
python -m insights.corpus_prep --csv data/raw/stories_clean.csv \
    --db data/catalog.sqlite --workers 2
```

Workers parallelise the per-story pipeline; the parent owns dedup state and the
single-writer SQLite connection.

## Analysis

Aggregates over *canonical, safety-passing* stories: corpus shape, duplicate
rate, safety and tier distribution, trope/archetype/setting/heat/POV/pacing/
duration distributions, category mix, top authors, length buckets, per-year
volume + trope/category share by decade, and quality breakdowns by dimension.

```bash
python -m insights.analysis --db data/catalog.sqlite --out-dir insights_output/analysis
```

## Semantic search + topic clusters

Zero-cost, deterministic, CPU-only: `TfidfVectorizer` (1–2 grams, sublinear TF,
60K features) → `TruncatedSVD` (192 dims, fixed seed) → L2-normalised vectors.
`MiniBatchKMeans` (fixed seed) clusters the same space; cluster labels are the
top terms of the inverse-transformed centroid, with exemplar stories.

```bash
python -m insights.semantic --db data/catalog.sqlite --out-dir insights_output --clusters 40
```

## NER combination search

Lexicon/regex entity extraction over title + preview of canonical,
safety-passing stories, written to `entity_mentions(story_id, etype, label)`:

- `setting` — locker room/gym, sauna, beach, office, cabin, truck stop, …
- `character` — jock/athlete, military/cop, student, blue collar, straight/curious, …
- `dynamic` — voyeur, exhibition, first time, cheating, hookup, reunion, slow burn
- `topic` — normalised Nifty directory category

The UI exposes facet checkboxes with live counts (each facet constrained by the
other active filters) plus category / published-after / min-words constraints.

```bash
python -m insights.ner --db data/catalog.sqlite
```

## Internal UI + TTS audition

```bash
python -m insights.ui --db data/catalog.sqlite --out-dir insights_output
# http://127.0.0.1:8765  (dashboard, /search, /combo, /story/<id>)
```

TTS audition uses the cheapest available **local** engine — `piper` if a voice
model is configured (`PIPER_VOICE`), else `espeak-ng`/`espeak`. Audio is a short
excerpt for inspiration only; it is never production audio and nothing leaves
the machine.

## Reproducibility & cost

- All transforms are deterministic (fixed MinHash coefficients/seeds, sorted
  vocabularies). No RNG, no cloud calls, no paid compute.
- The full build runs on 2 CPU cores / ~1.5 GB RSS. Projected ingest time for
  the 311K-row corpus: ~3–4 hours.
- Never commit the corpus, the catalogue DB, or the OCI PAR link. `.gitignore`
  excludes `data/raw/`, `*.sqlite*`, and analysis outputs.

## Schema (catalogue)

`stories`: id, title, author, category, orientation, path, publication_date,
url, word_count, char_count, paragraph_count, avg_sentence_len, dialogue_ratio,
ttr, sensory_density, explicit_density, safety_verdict, safety_terms,
quality_* (5 sub-scores + total + tier + penalties), tropes, archetypes,
settings, heat_level, pov, pacing, duration_tier, tts_minutes, exact_hash, sig
(MinHash blob), is_canonical, dup_of, preview.

`story_text`: id, full_text (zlib BLOB; canonical PASS Tier 1/2 only).

`entity_mentions`: story_id, etype, label.

`meta`: key/value (includes `ingest_state` checkpoint).

## Verification

`tests/test_insights.py` covers MinHash Jaccard accuracy, exact + near-dup
detection, ingest + resume idempotency, per-row extraction, analysis summary,
NER extraction/combo, and UI smoke tests.
