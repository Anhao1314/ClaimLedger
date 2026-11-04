import describe

text = describe.describe_margin().lower()
assert "safety margin" in text, text
assert ("not a tuned optimum" in text or "not tuned" in text
        or "not an optimum" in text or "rather than" in text), text
assert "is optimal" not in text and "is the best" not in text, text
