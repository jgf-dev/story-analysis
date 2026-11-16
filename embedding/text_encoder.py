"""Jina v5 text encoder for chunk search queries and documents."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from embedding.data_loading import DEFAULT_ENCODE_BATCH_SIZE, EMBEDDING_DIM

DEFAULT_MODEL = "jinaai/jina-embeddings-v5-text-small"
TASKS = ("retrieval", "text-matching", "clustering", "classification")


class JinaTextEncoder:
    """Encode queries and documents with the Jina v5 retrieval adapter.

    ``AutoModel.from_pretrained`` downloads the model and its task adapters on
    first use and reuses the Hugging Face cache afterwards. Documents are
    encoded with the model's ``document`` prompt and queries with its ``query``
    prompt, which is how Elasticsearch's ``semantic_text`` field uses the model
    by default. The model L2-normalises its output, so both live in the same
    cosine space as the indexed chunk vectors.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        device: str | None = None,
        task: str = "retrieval",
        dimension: int = EMBEDDING_DIM,
        encode_batch_size: int = DEFAULT_ENCODE_BATCH_SIZE,
        max_length: int | None = None,
    ) -> None:
        if task not in TASKS:
            raise ValueError(f"task must be one of {TASKS}, got {task!r}")
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if encode_batch_size <= 0:
            raise ValueError("encode_batch_size must be positive")
        if max_length is not None and max_length <= 0:
            raise ValueError("max_length must be positive")
        self.model_name = model_name
        self.device = device
        self.task = task
        self.dimension = dimension
        self.encode_batch_size = encode_batch_size
        self.max_length = max_length
        self._model: Any | None = None

    def _load(self) -> Any:
        import torch
        from transformers import AutoModel

        device = torch.device(
            self.device
            if self.device is not None
            else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        if device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(
                f"requested device {str(device)!r}, but CUDA is not available"
            )
        dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
        model = AutoModel.from_pretrained(
            self.model_name, trust_remote_code=True, dtype=dtype
        )
        self._model = model.to(device).eval()
        self.device = str(device)
        return self._model

    def encode_query(self, query: str) -> np.ndarray:
        """Encode one plaintext query with the retrieval ``query`` prompt."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        return self._encode([query], prompt_name="query")[0]

    def encode_documents(self, documents: Sequence[str]) -> np.ndarray:
        """Encode chunk text with the retrieval ``document`` prompt."""
        texts = list(documents)
        if not texts:
            raise ValueError("documents must not be empty")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("documents must be non-empty strings")

        batches = [
            self._encode(
                texts[start : start + self.encode_batch_size],
                prompt_name="document",
            )
            for start in range(0, len(texts), self.encode_batch_size)
        ]
        return np.vstack(batches)

    def _encode(self, texts: list[str], *, prompt_name: str) -> np.ndarray:
        model = self._model if self._model is not None else self._load()
        kwargs: dict[str, Any] = {
            "texts": texts,
            "task": self.task,
            "prompt_name": prompt_name,
        }
        if self.max_length is not None:
            kwargs["max_length"] = self.max_length
        embeddings = model.encode(**kwargs)
        array = np.asarray(embeddings.detach().float().cpu().numpy(), dtype=np.float32)
        if array.ndim != 2 or array.shape[0] != len(texts):
            raise RuntimeError(
                f"{self.model_name} returned {array.shape} for {len(texts)} texts"
            )
        if array.shape[1] != self.dimension:
            raise ValueError(
                f"{self.model_name} returned {array.shape[1]} dimensions, "
                f"expected {self.dimension}"
            )
        return np.ascontiguousarray(array)
