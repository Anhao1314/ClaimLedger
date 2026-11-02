"""Offline tests for the Jev-first core: policy v2, record chain, judge, cache, log."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chat_distiller import jev
from jev_first import Policy, contracts, judge, log
from jev_first.cache import Cache
from jev_first.judge import Judgment
from jev_first.policy import ADMIT, EXCLUDE, REVIEW
from jev_first.records import RecordStore, body_hash


def make_records(texts, prefix="clm"):
    return [contracts.make_record(texts[i], "agent",
                                  f"2026-11-02T00:00:0{i}Z")
            for i, text in enumerate(texts)]


def fake_caller(admit, *, contradiction=0.0, governing="none", gconf=0.95):
    """admit: {record_id: (choice, confidence, p_admit)}"""
    def call(state, questions):
        answers = {"contradiction": {"type": "noul", "noul": contradiction}}
        for record_id, (choice, confidence, p_admit) in admit.items():
            answers[f"admit::{record_id}"] = {
                "type": "choice", "choice": choice, "confidence": confidence,
                "probabilities": {"admit": p_admit, "review": 0.1, "exclude": 0.05},
            }
        answers["governing"] = {"type": "choice", "choice": governing,
                                "confidence": gconf}
        return {"model": "jev-test", "answers": answers,
                "usage": {"input_tokens": 10, "output_tokens": 5}}
    return call


class PolicyTests(unittest.TestCase):
    def test_argmax_passthrough(self):
        policy = Policy()
        self.assertEqual(policy.action(ADMIT), ADMIT)
        self.assertEqual(policy.action(REVIEW), REVIEW)
        self.assertEqual(policy.action(EXCLUDE), EXCLUDE)

    def test_contradiction_makes_admit_impossible(self):
        policy = Policy()
        self.assertEqual(policy.action(ADMIT, contradiction=0.9), REVIEW)
        self.assertEqual(policy.action(REVIEW, contradiction=0.9), REVIEW)
        self.assertEqual(policy.action(EXCLUDE, contradiction=0.9), EXCLUDE)

    def test_governing_promotes_review_only(self):
        policy = Policy()
        self.assertEqual(policy.action(REVIEW, governing=True), ADMIT)
        self.assertEqual(policy.action(EXCLUDE, governing=True), EXCLUDE)

    def test_governing_cannot_override_contradiction(self):
        self.assertEqual(
            Policy().action(REVIEW, contradiction=0.9, governing=True), REVIEW)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            Policy().action("maybe")
        with self.assertRaises(ValueError):
            Policy().action(ADMIT, contradiction=7)
        with self.assertRaises(ValueError):
            Policy(contradiction_review_at=2)


class RecordStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = RecordStore(Path(self.tmp.name) / "records.jsonl")

    def test_chain_grows_and_verifies(self):
        first = self.store.append("Use PostgreSQL.", "agent")
        second = self.store.append("Retries at most 3.", "agent")
        self.assertEqual(second["prev_hash"], body_hash(first))
        self.assertEqual(len(self.store.load()), 2)

    def test_empty_store(self):
        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.store.last_hash(), "0" * 64)

    def test_duplicate_content_is_rejected(self):
        self.store.append("Use PostgreSQL.", "agent")
        self.store.append("Use PostgreSQL.", "agent")
        with self.assertRaises(contracts.ContractError):
            self.store.load()

    def test_tampering_breaks_the_chain(self):
        self.store.append("Use PostgreSQL.", "agent")
        self.store.append("Retries at most 3.", "agent")
        rows = self.store.path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(rows[1])
        tampered["text"] = "Retries at most 300."
        rows[1] = json.dumps(tampered, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        self.store.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaises(contracts.ContractError):
            self.store.load()


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.records = make_records([
            "All storage must use PostgreSQL.",
            "PostgreSQL is banned for the analytics service.",
            "The release train leaves on Friday.",
        ])

    def test_argmax_becomes_the_action(self):
        decision = judge(
            "write a storage adapter", self.records, model="jev-test",
            caller=fake_caller({
                self.records[0]["record_id"]: (ADMIT, 0.9, 0.9),
                self.records[1]["record_id"]: (EXCLUDE, 0.8, 0.1),
                self.records[2]["record_id"]: (REVIEW, 0.6, 0.4),
            }))
        by_id = {e.record_id: e for e in decision.entries}
        self.assertEqual(by_id[self.records[0]["record_id"]].action, ADMIT)
        self.assertEqual(by_id[self.records[1]["record_id"]].action, EXCLUDE)
        self.assertEqual(by_id[self.records[2]["record_id"]].action, REVIEW)

    def test_contradiction_blocks_admit(self):
        decision = judge(
            "write an adapter", self.records, model="jev-test",
            caller=fake_caller({
                r["record_id"]: (ADMIT, 0.9, 0.9) for r in self.records
            }, contradiction=0.92, governing=self.records[0]["record_id"]))
        self.assertEqual({e.action for e in decision.entries}, {REVIEW})
        self.assertEqual(decision.contradiction, 0.92)

    def test_governing_promotes_review(self):
        decision = judge(
            "write an adapter", self.records, model="jev-test",
            caller=fake_caller({
                r["record_id"]: (REVIEW, 0.6, 0.45) for r in self.records
            }, governing=self.records[0]["record_id"], gconf=0.95))
        by_id = {e.record_id: e for e in decision.entries}
        self.assertEqual(by_id[self.records[0]["record_id"]].action, ADMIT)
        self.assertTrue(by_id[self.records[0]["record_id"]].governing)
        self.assertEqual(by_id[self.records[1]["record_id"]].action, REVIEW)

    def test_budget_packing_omits_and_reports(self):
        records = make_records(["x" * 200 for _ in range(5)])
        decision = judge(
            "t", records, model="jev-test", budget_bytes=500,
            caller=fake_caller({r["record_id"]: (ADMIT, 0.9, 0.9)
                                for r in records}))
        self.assertGreater(decision.omitted, 0)
        self.assertLessEqual(decision.used_bytes, 500)
        self.assertEqual(len(decision.admitted) + decision.omitted, 5)

    def test_transport_failure_raises_when_asked(self):
        def boom(state, questions):
            raise jev.JevError("timeout")
        with self.assertRaises(jev.JevError):
            judge("t", self.records, model="jev-test", caller=boom,
                  on_error="raise")

    def test_transport_failure_fails_open_to_review(self):
        def boom(state, questions):
            raise jev.JevError("timeout")
        decision = judge("t", self.records, model="jev-test", caller=boom,
                         on_error="review")
        self.assertTrue(decision.degraded)
        self.assertEqual(decision.model, "unavailable")
        self.assertTrue(all(e.action == REVIEW for e in decision.entries))
        self.assertFalse(any(e.action == EXCLUDE for e in decision.entries))

    def test_more_than_six_records_rejected(self):
        records = make_records([f"r{i}" for i in range(7)])
        with self.assertRaises(ValueError):
            judge("t", records, model="jev-test",
                  caller=fake_caller({r["record_id"]: (ADMIT, 0.9, 0.9)
                                      for r in records}))

    def test_round_trip_preserves_the_decision(self):
        decision = judge("t", self.records, model="jev-test",
                         caller=fake_caller({
                             r["record_id"]: (ADMIT, 0.9, 0.9) for r in self.records}))
        restored = Judgment.from_dict(decision.to_dict())
        self.assertEqual(restored.to_dict(), decision.to_dict())
        self.assertTrue(restored.cached)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.records = make_records([
            "All storage must use PostgreSQL.",
            "PostgreSQL is banned for the analytics service.",
        ])

    def test_second_identical_call_is_served_from_cache(self):
        calls = []

        def counting_caller(state, questions):
            calls.append(state)
            return fake_caller({r["record_id"]: (ADMIT, 0.9, 0.9)
                                for r in self.records})(state, questions)

        cache = Cache(Path(self.tmp.name) / "cache.jsonl")
        first = judge("write an adapter", self.records, model="jev-test",
                      caller=counting_caller, cache=cache)
        second = judge("write an adapter", self.records, model="jev-test",
                       caller=counting_caller, cache=cache)
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_different_task_misses(self):
        cache = Cache(Path(self.tmp.name) / "cache.jsonl")
        caller = fake_caller({r["record_id"]: (ADMIT, 0.9, 0.9)
                              for r in self.records})
        first = judge("task one", self.records, model="jev-test",
                      caller=caller, cache=cache)
        second = judge("task two", self.records, model="jev-test",
                       caller=caller, cache=cache)
        self.assertFalse(first.cached)
        self.assertFalse(second.cached)


class LogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "judgments.jsonl"
        self.records = make_records(["All storage must use PostgreSQL.",
                                     "PostgreSQL is banned for analytics."])

    def test_chain_seals_and_verifies(self):
        first = judge("t1", self.records, model="jev-test",
                      caller=fake_caller({r["record_id"]: (ADMIT, 0.9, 0.9)
                                          for r in self.records}))
        second = judge("t2", self.records, model="jev-test",
                       caller=fake_caller({r["record_id"]: (ADMIT, 0.9, 0.9)
                                           for r in self.records}))
        sealed_a = log.append_judgment(self.path, first.to_dict())
        sealed_b = log.append_judgment(self.path, second.to_dict())
        self.assertEqual(sealed_a["prev_hash"], "0" * 64)
        self.assertEqual(sealed_b["prev_hash"], sealed_a["judgment_hash"])
        self.assertEqual(log.verify(self.path), 2)

    def test_tampering_is_detected(self):
        judgment = judge("t", self.records, model="jev-test",
                         caller=fake_caller({r["record_id"]: (ADMIT, 0.9, 0.9)
                                             for r in self.records}))
        log.append_judgment(self.path, judgment.to_dict())
        rows = self.path.read_text(encoding="utf-8").splitlines()
        row = json.loads(rows[0])
        row["contradiction"] = 0.99
        rows[0] = json.dumps(row, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        self.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            log.verify(self.path)

    def test_empty_log_verifies_to_zero(self):
        self.assertEqual(log.verify(self.path), 0)


if __name__ == "__main__":
    unittest.main()