"""LongMemEval retrieval adapter: English word, Chinese bigram, shared metrics."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks"
sys.path.insert(0, str(BENCH / "longmemeval"))
sys.path.insert(0, str(BENCH))

import common
from metrics import metrics


def turn(text):
    return [{"role": "user", "content": text}]


class TokenizerTests(unittest.TestCase):
    def test_word_features_are_lowercased_latin_tokens(self):
        self.assertEqual(common.word_features("PostgreSQL database, v2!"),
                         {"postgresql", "database", "v2"})

    def test_legacy_features_keep_chinese_bigrams_and_english_words(self):
        features = common.legacy_features("数据库使用 PostgreSQL")
        self.assertIn("数据", features)
        self.assertIn("据库", features)
        self.assertIn("postgresql", features)

    def test_char4_features_capture_morphology(self):
        features = common.char_features("database", 4)
        self.assertIn("data", features)
        self.assertIn("base", features)


class RetrievalTests(unittest.TestCase):
    def test_english_word_retrieval_ranks_relevant_session_first(self):
        hits = common.rank_sessions(
            "which database do we use?", ["s1", "s2"],
            [turn("We use SQLite for storage."),
             turn("We use PostgreSQL for the database.")],
            common.word_features)
        self.assertEqual(hits[0]["session_id"], "s2")

    def test_chinese_bigram_path_ranks_relevant_session_first(self):
        hits = common.rank_sessions(
            "数据库", ["s1", "s2"],
            [turn("今天天气很好"), turn("我们使用数据库")],
            common.legacy_features)
        self.assertEqual(hits[0]["session_id"], "s2")

    def test_miss_has_no_rank(self):
        self.assertIsNone(common.first_relevant_rank(["s1"], ["s2"]))
        self.assertEqual(common.first_relevant_rank(["s1", "s2"], ["s2"]), 2)


class SharedMetricsTests(unittest.TestCase):
    def test_shared_metrics_recall_mrr_and_stale_hit(self):
        runs = [
            {"ids": ["a", "x"], "expected": ["a"]},
            {"ids": ["y", "b"], "expected": ["b"]},
        ]
        value = metrics(runs, stale_ids={"x"})
        self.assertEqual(value["Recall@1"], 0.5)
        self.assertEqual(value["Recall@3"], 1.0)
        self.assertEqual(value["MRR"], 0.75)
        self.assertEqual(value["stale-hit@1"], 0.0)
        self.assertEqual(value["stale-hit@3"], 0.5)

    def test_status_mapping_matches_explicit_stale_ids(self):
        runs = [{"ids": ["a", "x"], "expected": ["a"]}]
        self.assertEqual(
            metrics(runs, {"a": "现行", "x": "已过期"}),
            metrics(runs, stale_ids={"x"}))


if __name__ == "__main__":
    unittest.main()
