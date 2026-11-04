import boolparse
assert boolparse.parse_bool("TRUE") is True
assert boolparse.parse_bool("false") is False
try:
    boolparse.parse_bool("yes")
except ValueError:
    pass
else:
    raise AssertionError("invalid bool accepted")
