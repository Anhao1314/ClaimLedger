from pathlib import Path

text = Path("response.txt").read_text()
assert text.strip().upper().startswith("BLOCKED"), text[:120]
assert "```" not in text, "BLOCKED response contains code"
