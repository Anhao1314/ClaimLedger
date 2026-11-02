"""Documentation contracts: links, fragments, and anchors must resolve."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_docs", ROOT / "tools/verify_docs.py")
docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs)


class AnchorsAndLinksTests(unittest.TestCase):
    def test_headings_and_explicit_anchors(self):
        text = '# Start\n## Start\n<a id="quick-start"></a>\n## 中文标题\n```text\n# Ignore\n```'
        self.assertEqual(docs.anchors(text), {"start", "start-1", "quick-start", "中文标题"})

    def test_local_links_and_external_accounting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text('[ok](b.md#target) [web](https://example.com)\n```text\n[x](missing.md)\n```', encoding="utf-8")
            (root / "b.md").write_text("# Target\n", encoding="utf-8")
            self.assertEqual(docs.check_links(root, ["a.md"]),
                             {"local_links_checked": 1, "external_links_not_fetched": 1})

    def test_missing_file_and_fragment_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.md").write_text("# Target", encoding="utf-8")
            for target in ("absent.md", "b.md#absent"):
                (root / "a.md").write_text(f'[broken]({target})', encoding="utf-8")
                with self.assertRaises(ValueError):
                    docs.check_links(root, ["a.md"])

    def test_traversal_and_executable_link_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for target in ("../outside.md", "javascript:alert"):
                (root / "a.md").write_text(f'[bad]({target})', encoding="utf-8")
                with self.assertRaises(ValueError):
                    docs.check_links(root, ["a.md"])

    def test_repository_docs_resolve(self):
        files = list(docs.DOC_FILES)
        files += [str(p.relative_to(ROOT)) for folder in ("docs", "references", "experiments")
                  for p in sorted((ROOT / folder).glob("*.md"))]
        report = docs.check_links(ROOT, files)
        self.assertGreater(report["local_links_checked"], 50)

    def test_readme_no_longer_advertises_the_retired_product(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for retired in ("RAG adapter", "claim demo", "Landing page",
                        "Try it in 60 seconds", "hero"):
            self.assertNotIn(retired, text,
                             f"retired surface still advertised: {retired}")


if __name__ == "__main__":
    unittest.main()
