import faiss
import numpy as np

print(faiss.get_num_gpus())
data = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12]], dtype=np.float32)

dimension = data.shape[1]
index = faiss.IndexFlatL2(dimension)

index.add(data)

query = np.array([[0, 0, 0]], dtype=np.float32)
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
