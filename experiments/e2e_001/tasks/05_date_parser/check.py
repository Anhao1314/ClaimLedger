from datetime import date
import dateparse

assert dateparse.parse_date("2026-11-04") == date(2026, 11, 4)
assert dateparse.parse_date("2026-11-03") == date(2026, 11, 3)
try:
    dateparse.parse_date("not-a-date")
except ValueError:
    pass
else:
    raise AssertionError("invalid input accepted")
