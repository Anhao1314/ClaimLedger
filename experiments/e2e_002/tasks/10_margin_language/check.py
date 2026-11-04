import describe

text = describe.describe_margin().lower()
assert "safety margin" in text, text
assert "optimal" not in text and "tuned" not in text and "best" not in text, text
