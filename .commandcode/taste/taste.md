# Taste

## Python style

- Annotates local variables with explicit types, not just parameters and returns — including trivial-looking ones (`dimension: int = data.shape[1]`, `index: faiss.Index = ...`) and fully spelled-out third-party/numpy types (`np.ndarray[Any, np.dtype[np.floating[_32Bit]]]`, `df: DataFrame`). Confidence: 0.6
- Writes hex literals with uppercase digits (`0xBF58476D1CE4E5B9`, not `0xbf58476d1ce4e5b9`), including inside `np.uint64(...)` casts. Confidence: 0.6
