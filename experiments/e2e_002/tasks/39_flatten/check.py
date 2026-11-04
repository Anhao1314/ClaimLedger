import flatten
assert flatten.flatten([1, [2, 3], 4]) == [1, 2, 3, 4]
assert flatten.flatten([[1], [2]]) == [1, 2]
