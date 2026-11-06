import retry

calls = 0


def boom():
    global calls
    calls += 1
    raise RuntimeError("x")

try:
    retry.fetch_with_retry(boom, attempts=10)
except RuntimeError:
    pass
else:
    raise AssertionError("did not re-raise")
assert calls == 3, calls

assert retry.fetch_with_retry(lambda: 7, attempts=10) == 7
