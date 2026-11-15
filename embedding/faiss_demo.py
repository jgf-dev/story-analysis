from typing import Any

import faiss
import numpy as np
import pandas as pd
import transformers
from numpy._typing._nbit_base import _32Bit
from pandas.core.frame import DataFrame

from embedding.data import VECTOR_TEST

print(faiss.get_num_gpus())
df: DataFrame = pd.read_parquet("../data/test.parquet")
data: np.ndarray[Any, np.dtype[np.floating[_32Bit]]] = np.vstack(df["embedding"]).astype(np.float32)

dimension: int = data.shape[1]
index: faiss.Index = faiss.IndexFlatL2(dimension)

index.add(data)

query: np.ndarray[Any, np.dtype[np.floating[_32Bit]]] = np.array(VECTOR_TEST, dtype=np.float32)
k = 2
dist, idx = index.search(query, k)

print("Nearest neighbor index:", idx[0])
print("Distance:", dist[0])


print("\n===== GPU Test =====")
if faiss.get_num_gpus() > 0:
    res = faiss.StandardGpuResources()
    index_cpu = faiss.IndexFlatL2(dimension)
    index_gpu = faiss.index_cpu_to_gpu(res, 0, index_cpu)
    index_gpu.add(data)
    dist_gpu, idx_gpu = index_gpu.search(query, k)

    print("GPU Test Result")
    print("Nearest neighbor index:", idx_gpu[0])
    print("Distance:", dist_gpu[0])
else:
    print("No GPU")
