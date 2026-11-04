import paging
assert paging.paginate([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
assert paging.paginate([], 3) == []
