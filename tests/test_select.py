"""Offline tests for candidate selection and the end-to-end decide path."""
import json
import tempfile
import unittest
from pathlib import Path

from jev_first import contracts, judge, log
from jev_first.cache import Cache
from jev_first.policy import ADMIT
from jev_first.records import RecordStore
from jev_first.select import select_candidates

from tests.test_jev_first import fake_core

TEXTS = {
    "db": "All storage must use PostgreSQL.",
    "ban": "PostgreSQL is banned for the analytics service.",
    "release": "The release train leaves on Friday.",
    "wiki": "The team wiki lives at wiki.internal.",
    "standup": "Standups are at 09:30 every weekday.",
    "ci": "The CI pipeline runs on GitHub Actions.",
    "review": "Code reviews require two approvals.",
    "staging": "The staging environment refreshes nightly.",
    "logs": "Logs are retained for 30 days.",
    "oncall": "The on-call rotation changes monthly.",
    "bad_newer": "All storage must use PostgreSQL 16.",
    "bad_old": "Use PostgreSQL 15 for all storage.",
}


def build_store(path, items):
    store = RecordStore(path)
    for i, (text, scope) in enumerate(items):
        store.append(text, "agent", scope=scope,
                     at=f"2026-11-0{(i % 9) + 1}T00:00:00Z")
    return store


class SelectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.items = [(TEXTS[k], None if k != "standup" else "office")
                      for k in ("db", "ban", "release", "wiki", "standup",
                                "ci", "review", "staging", "logs", "oncall")]

    def test_lexical_hits_rank_first(self):
        records = build_store(Path(self.tmp.name) / "r.jsonl", self.items).load()
        candidates, stats = select_candidates(
            records, "Which database engine do we use for storage?", limit=4)
        texts = [c["text"] for c in candidates]
        self.assertEqual(candidates[0]["text"], TEXTS["db"])
        self.assertNotIn(TEXTS["standup"], texts)
        self.assertFalse(stats["fallback_to_recency"])
        # honest entrance limitation: the 'ban' record has zero lexical
        # overlap with this task and is NOT selected. Semantic recall is a
        # known gap, deferred to a topic field.

    def test_scope_filters_but_global_survives(self):
        items = self.items + [(TEXTS["ban"], "analytics")]
        records = build_store(Path(self.tmp.name) / "r.jsonl", items).load()
        candidates, stats = select_candidates(
            records, "storage engine decision", scope="analytics", limit=6)
        # 12 records total; the office-scoped one drops out, global ones stay
        self.assertEqual(stats["in_scope"], len(records) - 1)
        for candidate in candidates:
            self.assertIn(candidate.get("scope"), (None, "analytics"))

    def test_zero_hits_fall_back_to_recency(self):
        records = build_store(Path(self.tmp.name) / "r.jsonl", self.items).load()
        candidates, stats = select_candidates(
            records, "zzz qqq xvz", limit=3)
        self.assertTrue(stats["fallback_to_recency"])
        self.assertEqual(len(candidates), 3)
        ats = [c["at"] for c in candidates]
        self.assertEqual(ats, sorted(ats, reverse=True))

    def test_cap_six_omits_the_rest(self):
        records = build_store(Path(self.tmp.name) / "r.jsonl", self.items).load()
        # lexical path: only overlapping records survive the cap
        candidates, stats = select_candidates(records, "storage database release",
                                              limit=6)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(stats["omitted"], 8)
        # fallback path: the cap itself binds
        candidates, stats = select_candidates(records, "zzz qqq xvz", limit=6)
        self.assertEqual(len(candidates), 6)
        self.assertEqual(stats["omitted"], 4)

    def test_bad_inputs(self):
        records = build_store(Path(self.tmp.name) / "r.jsonl", self.items).load()
        with self.assertRaises(ValueError):
            select_candidates(records, "  ")
        with self.assertRaises(ValueError):
            select_candidates(records, "t", limit=0)


class DecidePathTests(unittest.TestCase):
    """End-to-end: a 12-record store, selection, judgment, sealed log."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        items = ([(TEXTS["db"], None), (TEXTS["ban"], None)]
                 + [(TEXTS[k], None) for k in
                    ("release", "wiki", "standup", "ci", "review",
                     "staging", "logs", "oncall", "bad_newer", "bad_old")])
        self.store = build_store(base / "records.jsonl", items)
        self.cache = Cache(base / "cache.jsonl")
        self.log_path = base / "judgments.jsonl"

    def test_store_to_judgment_to_sealed_log(self):
        records = self.store.load()
        candidates, stats = select_candidates(
            records, "write a storage adapter for the analytics service",
            limit=6)
        texts = [c["text"] for c in candidates]
        # both sides of the conflict must reach the judge
        self.assertIn(TEXTS["db"], texts)
        self.assertIn(TEXTS["ban"], texts)
        self.assertLessEqual(len(candidates), 6)

        judgment = judge("write a storage adapter for the analytics service",
                         candidates, budget_bytes=2048, cache=self.cache,
                         caller=fake_core(
                             {c["record_id"]: (ADMIT, 0.9) for c in candidates},
                             {(TEXTS["db"], TEXTS["ban"]): "contradiction"}))
        sealed = log.append_judgment(self.log_path, judgment.to_dict())
        self.assertEqual(log.verify(self.log_path), 1)
        self.assertTrue(judgment.conflicts)
        self.assertLessEqual(len(judgment.entries), 6)
        self.assertIn(sealed["task"], judgment.task)

    def test_full_flow_via_public_api_only(self):
        """The dashed line is now solid: store → select → judge → log, with
        no hand-built candidate list anywhere."""
        records = self.store.load()
        candidates, _ = select_candidates(records, "storage adapter", limit=6)
        decision = judge("storage adapter", candidates, model="jev-test",
                         cache=self.cache,
                         caller=fake_core(
                             {c["record_id"]: (ADMIT, 0.9) for c in candidates},
                             {(TEXTS["db"], TEXTS["ban"]): "contradiction"}))
        self.assertLessEqual(len(decision.entries), 6)
        self.assertGreater(decision.pair_checks, 0)


if __name__ == "__main__":
    unittest.main()