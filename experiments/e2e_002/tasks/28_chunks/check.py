import chunk
assert chunk.chunks([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
assert chunk.chunks([], 2) == []
