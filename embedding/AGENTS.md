## Sample Data

`samples/faiss_embedding_chunks_sample.jsonl` contains 200 chunks as JSONL
(`id`, `content`, other Elasticsearch hit metadata). The chunks have text but no
vectors, so `python -m embedding.search --sample` encodes them locally with the
Jina document prompt before searching.
