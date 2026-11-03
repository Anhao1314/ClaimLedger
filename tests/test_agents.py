"""Offline tests for the agent registry and its console endpoints."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jev_first import agents
from jev_first.web import Console


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "agents.jsonl"

    def test_register_and_verify(self):
        first = agents.append_agent(self.path, name="researcher-01", kind="agent")
        second = agents.append_agent(self.path, name="eason", kind="human")
        self.assertTrue(first["agent_id"].startswith("agt_"))
        self.assertEqual(second["prev_hash"], first["agent_hash"])
        self.assertEqual(agents.verify(self.path), 2)

    def test_duplicate_name_refused_case_insensitively(self):
        agents.append_agent(self.path, name="Researcher", kind="agent")
        with self.assertRaises(ValueError):
            agents.append_agent(self.path, name="researcher", kind="human")

    def test_invalid_name_and_kind(self):
        for name in ("", "has space", "x" * 65, "-leading-dash"):
            with self.assertRaises(ValueError):
                agents.append_agent(self.path, name=name)
        with self.assertRaises(ValueError):
            agents.append_agent(self.path, name="ok", kind="robot")

    def test_resolve(self):
        agents.append_agent(self.path, name="researcher-01")
        self.assertIsNotNone(agents.resolve(self.path, "RESEARCHER-01"))
        self.assertIsNone(agents.resolve(self.path, "nobody"))

    def test_tampering_detected(self):
        agents.append_agent(self.path, name="researcher-01")
        rows = self.path.read_text(encoding="utf-8").splitlines()
        import json
        row = json.loads(rows[0])
        row["kind"] = "human"
        rows[0] = json.dumps(row, sort_keys=True, separators=(",", ":"))
        self.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            agents.verify(self.path)


class ConsoleAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.console = Console(Path(self.tmp.name) / "records.jsonl", Path(self.tmp.name))

    def test_register_then_list(self):
        self.console.api_register_agent({"name": "researcher-01", "kind": "agent"})
        listed = self.console.api_agents()
        names = {row["name"]: row for row in listed}
        self.assertIn("researcher-01", names)
        self.assertTrue(names["researcher-01"]["registered"])
        self.assertEqual(names["researcher-01"]["records"], 0)

    def test_unregistered_source_is_flagged_not_hidden(self):
        self.console.store.append("Use PostgreSQL.", "legacy-agent")
        listed = self.console.api_agents()
        legacy = next(row for row in listed if row["name"] == "legacy-agent")
        self.assertFalse(legacy["registered"])
        self.assertEqual(legacy["kind"], "unknown")
        self.assertEqual(legacy["records"], 1)

    def test_record_counts_track_attribution(self):
        self.console.api_register_agent({"name": "researcher-01", "kind": "agent"})
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.console.api_record({"text": "Use PostgreSQL.", "source": "researcher-01"})
            self.console.api_record({"text": "Cap retries at 3.", "source": "researcher-01"})
        listed = {row["name"]: row for row in self.console.api_agents()}
        self.assertEqual(listed["researcher-01"]["records"], 2)

    def test_duplicate_registration_is_an_error(self):
        self.console.api_register_agent({"name": "researcher-01"})
        with self.assertRaises(ValueError):
            self.console.api_register_agent({"name": "researcher-01"})


if __name__ == "__main__":
    unittest.main()