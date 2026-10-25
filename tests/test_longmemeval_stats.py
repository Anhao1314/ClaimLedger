"""LongMemEval-S stage-0 split sampler: deterministic, stratified, disjoint."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "longmemeval_stats", ROOT / "benchmarks/longmemeval/stats.py")
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


def record(qid, question_type):
    return {
        "question_id": qid,
        "question_type": question_type,
        "question": "question",
        "answer": "answer",
        "answer_session_ids": [],
        "haystack_session_ids": ["session"],
        "haystack_dates": ["2024-01-01"],
        "haystack_sessions": [[{"role": "user", "content": "text"}]],
    }


class LongMemEvalSplitTests(unittest.TestCase):
    def setUp(self):
        self.records = [record("ku_%02d" % i, "knowledge-update") for i in range(72)]
        self.records += [record("abs_%02d_abs" % i, "multi-session") for i in range(30)]

    def test_splits_are_deterministic_and_disjoint(self):
        first = stats.build_splits(self.records)
        second = stats.build_splits(self.records)
        self.assertEqual(first["dev"]["ids"], second["dev"]["ids"])
        self.assertEqual(first["report"]["ids"], second["report"]["ids"])
        self.assertEqual(first["dev"]["questions"], 30)
        self.assertEqual(first["dev"]["knowledge_update_non_abs"], 20)
        self.assertEqual(first["dev"]["abstention"], 10)
        self.assertEqual(first["report"]["questions"], 60)
        self.assertEqual(first["report"]["knowledge_update_non_abs"], 40)
        self.assertEqual(first["report"]["abstention"], 20)
        self.assertFalse(set(first["dev"]["ids"]) & set(first["report"]["ids"]))
        self.assertEqual(first["pools"]["unused_knowledge_update_non_abs"], 12)
        self.assertEqual(first["pools"]["unused_abstention"], 0)

    def test_split_ids_are_sorted(self):
        splits = stats.build_splits(self.records)
        for name in ("dev", "report"):
            self.assertEqual(splits[name]["ids"], sorted(splits[name]["ids"]))

    def test_cost_projection_has_zero_free_extraction_and_paid_tail(self):
        cost = stats.project_cost(stats.build_splits(self.records))
        self.assertEqual(cost["extraction"]["free_endpoint"]["usd"], 0.0)
        self.assertGreater(cost["answer"]["expected"]["usd"], 0)
        self.assertGreater(cost["judge"]["expected"]["usd"], 0)
        self.assertLess(
            cost["totals"]["free_extraction_expected"]["usd"],
            cost["totals"]["free_extraction_worst_case"]["usd"])


if __name__ == "__main__":
    unittest.main()
