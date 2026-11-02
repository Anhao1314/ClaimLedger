"""Check repository documentation: local links, fragments, and anchors.

Simplified during the Jev-first cleanup. The retired product surface (demo
execution, lifecycle receipts, evidence tables, bilingual parity) no longer
has code here; what remains guards documentation integrity itself: every
local link and fragment in README.md and the docs/ + references/ + experiments/
trees must resolve, and README anchors must exist.
"""
from __future__ import annotations

import json
import re
import html
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
README_FILES = ("README.md",)
DOC_FILES = ("README.md", "CONTRIBUTING.md", "CHANGELOG.md")


def anchors(text):
    """Heading IDs for the subset used here, plus explicit HTML anchors."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    found = set(re.findall(r'<[^>]+(?:id|name)=["\']([^"\']+)', text))
    counts: dict = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        heading = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        found.add(slug + ("-" + str(count) if count else ""))
    return found


def check_links(root, files):
    """Validate local targets/Markdown fragments; external links are not fetched."""
    root = Path(root).resolve()
    checked = 0
    external = 0
    for relative in files:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        visible = re.sub(r"```.*?```", "", text, flags=re.S)
        links = re.findall(r"\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)", visible)
        links += re.findall(r'<[^>]+(?:href|src)=["\']([^"\']+)', visible)
        for link in links:
            url = urlsplit(html.unescape(link.strip("<>")))
            if url.scheme or url.netloc:
                if url.scheme not in ("https", "http", "mailto"):
                    raise ValueError(f"{relative}: unexpected link scheme: {link}")
                external += 1
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"{relative}: link escapes repository: {link}") from exc
            if not target.exists():
                raise ValueError(f"{relative}: missing link target: {link}")
            if url.fragment and target.suffix == ".md":
                if unquote(url.fragment) not in anchors(target.read_text(encoding="utf-8")):
                    raise ValueError(f"{relative}: missing fragment: {link}")
            checked += 1
    return {"local_links_checked": checked, "external_links_not_fetched": external}


def main():
    files = list(DOC_FILES)
    files += [str(p.relative_to(ROOT)) for folder in ("docs", "references", "experiments")
              for p in sorted((ROOT / folder).glob("*.md"))]
    links = check_links(ROOT, files)
    print(json.dumps(dict(ok=True, readme_languages=1, **links), indent=2))


if __name__ == "__main__":
    main()