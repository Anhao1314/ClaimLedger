"""Offline tests for the memory console: handler-level, hermetic, no network."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jev_first import contracts
from jev_first.web import Console
from tests.test_jev_first import make_records


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.console = Console(self.base / "records.jsonl", self.base)

    def test_decide_without_key_is_degraded(self):
        for text in ("Use PostgreSQL.", "SQLite is deprecated."):
            self.console.store.append(text, "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            result = self.console.api_decide({"task": "write an adapter"})
        self.assertTrue(result["degraded"])
        self.assertEqual(result["model"], "unavailable")
        self.assertTrue(all(e["action"] == "review" for e in result["entries"]))
        self.assertIn("ACTIVE CONSTRAINTS: none admitted", result["brief_text"])
        # every decide seals onto the log
        self.assertEqual(len(list(self.base.glob("judgments.jsonl"))), 1)

    def test_record_then_decide_flow(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.console.api_record({"text": "Use PostgreSQL.", "source": "console"})
            with self.assertRaises(Exception):
                self.console.api_record({"text": "Use PostgreSQL.", "source": "console"})
            result = self.console.api_decide({"task": "write an adapter"})
        self.assertEqual(result["selection"]["total_records"], 1)
        self.assertEqual(len(result["entries"]), 1)

    def test_outcome_feeds_calibration(self):
        records = make_records(["Use PostgreSQL.", "SQLite is deprecated."])
        for record in records:
            self.console.store.append(record["text"], "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            decided = self.console.api_decide({"task": "write an adapter"})
        rid = decided["entries"][0]["record_id"]
        outcome = self.console.api_outcome({
            "record_id": rid, "verdict": "upheld",
            "judgment_hash": decided["judgment_hash"], "by": "human"})
        self.assertIn("outcome", outcome)
        report = self.console.api_calibrate()
        # the entry is in review (degraded run) — v1 calibration scores admit only
        self.assertEqual(report["orphans"], 0)

    def test_history_returns_sealed_judgments_with_outcomes(self):
        for text in ("Use PostgreSQL.", "SQLite is deprecated."):
            self.console.store.append(text, "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            decided = self.console.api_decide({"task": "write an adapter"})
        rid = decided["entries"][0]["record_id"]
        self.console.api_outcome({"record_id": rid, "verdict": "upheld",
                                  "judgment_hash": decided["judgment_hash"],
                                  "by": "human"})
        history = self.console.api_history(limit=5)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["judgment_hash"], decided["judgment_hash"])
        self.assertEqual(history[0]["outcomes"][rid], "upheld")
        self.assertEqual(len(history[0]["entries"]), 2)
        # newest first
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.console.api_decide({"task": "another task"})
        history = self.console.api_history(limit=5)
        self.assertEqual(history[0]["task"], "another task")

    def test_chains_verify_after_use(self):
        from jev_first import log as jlog
        from jev_first.outcomes import verify as verify_outcomes
        records = make_records(["Use PostgreSQL."])
        for record in records:
            self.console.store.append(record["text"], "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.console.api_decide({"task": "t"})
        self.assertGreater(jlog.verify(self.console.log_path), 0)
        self.assertGreaterEqual(verify_outcomes(self.console.outcomes_path), 0)

    def test_duplicate_record_surfaces_as_error_payload(self):
        self.console.store.append("Use PostgreSQL.", "agent")
        with self.assertRaises(contracts.ContractError):
            self.console.api_record({"text": "Use PostgreSQL.", "source": "agent"})

    def test_history_carries_renderable_brief_text(self):
        """The console copies the brief from history, so it must be rebuilt
        server-side; the sealed entry alone is not the brief."""
        self.console.store.append("Use PostgreSQL.", "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.console.api_decide({"task": "write an adapter"})
        history = self.console.api_history(limit=5)
        self.assertIn("ACTIVE CONSTRAINTS", history[0]["brief_text"])

    def test_record_history_follows_one_record_across_judgments(self):
        self.console.store.append("Use PostgreSQL.", "agent")
        self.console.store.append("SQLite is deprecated.", "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            first = self.console.api_decide({"task": "write an adapter"})
            second = self.console.api_decide({"task": "pick a database"})
        rid = first["entries"][0]["record_id"]
        rows = self.console.api_record_history(rid)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["record_id"] == rid for row in rows))
        self.assertTrue(all("action" in row and "p_admit" in row for row in rows))
        self.assertEqual(self.console.api_record_history("rec_" + "0" * 24), [])
        self.assertNotEqual(first["judgment_hash"], second["judgment_hash"])

    def test_seed_examples_only_into_an_empty_store(self):
        seeded = self.console.api_seed_examples()
        self.assertEqual(seeded["seeded"], 5)
        self.assertEqual(len(self.console.store.load()), 5)
        self.assertEqual(len(seeded["records"]), 5)
        # the seeding identity is registered so attribution is not "unknown"
        names = {row["name"] for row in self.console.api_agents()}
        self.assertIn("examples", names)
        # a second seed is refused, and the store is untouched
        again = self.console.api_seed_examples()
        self.assertIn("error", again)
        self.assertEqual(len(self.console.store.load()), 5)


if __name__ == "__main__":
    unittest.main()