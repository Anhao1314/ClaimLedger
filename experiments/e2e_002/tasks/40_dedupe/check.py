import dedupe
assert dedupe.dedupe([1, 2, 1, 3, 2]) == [1, 2, 3]
assert dedupe.dedupe([]) == []
