import textnorm
assert textnorm.collapse_spaces("  a   b\tc ") == "a b c"
assert textnorm.collapse_spaces("") == ""
