"""Tests for the jev-memory MCP server: offline handler tests + a real
subprocess speaking line-delimited JSON-RPC."""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from jev_first import contracts
from jev_first import proposals as proposal_log
from jev_first.mcp_server import MemoryServer
from jev_first.records import body_hash
from jev_first.policy import ADMIT
from tests.test_jev_first import make_records


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = MemoryServer(Path(self.tmp.name))

    def test_initialize_negotiates_version(self):
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}})
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "jev-memory")

    def test_unknown_version_falls_back(self):
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")

    def test_notification_returns_none(self):
        self.assertIsNone(self.server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_seven_tools_listed(self):
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in response["result"]["tools"]]
        self.assertEqual(names, ["memory_record", "memory_propose",
                                 "memory_decide", "memory_brief",
                                 "memory_calibrate", "memory_audit",
                                 "memory_proposals"])

    def test_unknown_method_is_jsonrpc_error(self):
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 3, "method": "no/such"})
        self.assertEqual(response["error"]["code"], -32601)

    def test_record_is_a_proposal_not_a_write(self):
        ok = self.server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                 "params": {"name": "memory_record",
                                            "arguments": {"text": "Use PostgreSQL.",
                                                          "source": "agent"}}})
        payload = json.loads(ok["result"]["content"][0]["text"])
        self.assertFalse(ok["result"].get("isError", False))
        self.assertEqual(payload["status"], "pending")
        self.assertTrue(payload["proposal"]["proposal_id"].startswith("prp_"))
        self.assertIn("deprecated", payload)
        self.assertEqual(self.server.store.load(), [])

    def test_paraphrased_proposal_returns_existing_pending(self):
        first = self.server.handle(
            {"jsonrpc": "2.0", "id": 51, "method": "tools/call",
             "params": {"name": "memory_propose", "arguments": {
                 "text": "In the README, the delta=0.2 margin threshold must "
                         "consistently be described as a safety margin, not a "
                         "tuned optimum.", "source": "zcode"}}})
        first_payload = json.loads(first["result"]["content"][0]["text"])
        second = self.server.handle(
            {"jsonrpc": "2.0", "id": 52, "method": "tools/call",
             "params": {"name": "memory_propose", "arguments": {
                 "text": "The margin threshold delta=0.2 is a safety margin, "
                         "not a tuned optimum; the ablation cannot distinguish "
                         "0.0 to 0.2.", "source": "doubao-work"}}})
        second_payload = json.loads(second["result"]["content"][0]["text"])
        self.assertFalse(second_payload["created"])
        self.assertEqual(second_payload["duplicate"], "pending")
        self.assertEqual(second_payload["proposal"]["proposal_id"],
                         first_payload["proposal"]["proposal_id"])
        self.assertEqual(len(proposal_log.pending(self.server.proposals_path)), 1)

    def test_propose_refuses_an_existing_record(self):
        self.server.store.append("All storage must use PostgreSQL.", "agent")
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 53, "method": "tools/call",
             "params": {"name": "memory_propose", "arguments": {
                 "text": "All storage must use PostgreSQL for analytics.",
                 "source": "doubao-work"}}})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertFalse(payload["created"])
        self.assertEqual(payload["duplicate"], "record")
        self.assertEqual(proposal_log.pending(self.server.proposals_path), [])

    def test_decide_on_empty_store_is_error(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                                       "params": {"name": "memory_decide",
                                                  "arguments": {"task": "t"}}})
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("empty", result["content"][0]["text"])

    def test_decide_without_key_is_degraded_not_broken(self):
        records = make_records(["Use PostgreSQL.", "SQLite is deprecated."])
        for record in records:
            self.server.store.append(record["text"], "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            response = self.server.handle(
                {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                 "params": {"name": "memory_decide",
                            "arguments": {"task": "write an adapter"}}})
        self.assertFalse(response["result"].get("isError", False))
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["model"], "unavailable")
        self.assertTrue(all(a["action"] == "review"
                            for a in payload["actions"].values()))

    def test_brief_returns_text_and_bytes(self):
        for text in ("Use PostgreSQL.", "SQLite is deprecated."):
            self.server.store.append(text, "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            response = self.server.handle(
                {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                 "params": {"name": "memory_brief",
                            "arguments": {"task": "write an adapter"}}})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("TASK:", payload["brief"])
        self.assertEqual(payload["bytes"],
                         len(payload["brief"].encode("utf-8")))

    def test_brief_seals_so_the_call_is_auditable_and_scoreable(self):
        """The MCP path is the main integration: a brief an agent acted on must
        exist in the log, or calibration can never see it."""
        records = make_records(["Use PostgreSQL.", "SQLite is deprecated."])
        for record in records:
            self.server.store.append(record["text"], "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            response = self.server.handle(
                {"jsonrpc": "2.0", "id": 81, "method": "tools/call",
                 "params": {"name": "memory_brief",
                            "arguments": {"task": "write an adapter"}}})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("judgment_hash", payload)
        audit = self.server.handle(
            {"jsonrpc": "2.0", "id": 82, "method": "tools/call",
             "params": {"name": "memory_audit", "arguments": {}}})
        self.assertEqual(
            json.loads(audit["result"]["content"][0]["text"])["n_judgments"], 1)
        # A human surface records the outcome against the returned hash; the
        # MCP server has no tool for it.
        from jev_first.outcomes import append_outcome
        outcome = append_outcome(
            self.server.outcomes_path, judgment_hash=payload["judgment_hash"],
            record_id=records[0]["record_id"], verdict="upheld", by="human")
        self.assertEqual(outcome["verdict"], "upheld")

    def test_decide_also_seals(self):
        for text in ("Use PostgreSQL.", "SQLite is deprecated."):
            self.server.store.append(text, "agent")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.server.handle(
                {"jsonrpc": "2.0", "id": 84, "method": "tools/call",
                 "params": {"name": "memory_decide",
                            "arguments": {"task": "write an adapter"}}})
        audit = self.server.handle(
            {"jsonrpc": "2.0", "id": 85, "method": "tools/call",
             "params": {"name": "memory_audit", "arguments": {}}})
        self.assertEqual(
            json.loads(audit["result"]["content"][0]["text"])["n_judgments"], 1)

    def test_outcome_is_not_an_mcp_tool(self):
        """Calibration's ground truth must come from a human surface."""
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
             "params": {"name": "memory_outcome",
                        "arguments": {"record_id": "rec_x", "verdict": "upheld",
                                      "by": "agent"}}})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("unknown tool", response["result"]["content"][0]["text"])

    def test_calibrate_reads_human_recorded_outcomes(self):
        # Seed the log with a sealed judgment by hand: the server reads the log,
        # it does not care who wrote it.
        records = make_records(["Use PostgreSQL.", "SQLite is deprecated."])
        from jev_first import judge, log as jlog
        from jev_first.outcomes import append_outcome
        from tests.test_jev_first import fake_core
        judgment = judge("t", records, model="jev-test",
                         caller=fake_core({r["record_id"]: (ADMIT, 0.9)
                                           for r in records}, {}))
        sealed = jlog.append_judgment(self.server.log_path, judgment.to_dict())
        append_outcome(self.server.outcomes_path,
                       judgment_hash=sealed["judgment_hash"],
                       record_id=records[0]["record_id"], verdict="upheld",
                       by="human")
        report = self.server.handle(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
             "params": {"name": "memory_calibrate", "arguments": {}}})
        payload = json.loads(report["result"]["content"][0]["text"])
        self.assertEqual(payload["n_scored"], 1)
        self.assertEqual(payload["overall_upheld_rate"], 1.0)

    def test_audit_summary_and_per_record(self):
        summary = self.server.handle(
            {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
             "params": {"name": "memory_audit", "arguments": {}}})
        payload = json.loads(summary["result"]["content"][0]["text"])
        self.assertEqual(payload["n_judgments"], 0)


class SubprocessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = dict(os.environ)
        env["TYPESAFE_API_KEY"] = ""  # hermetic: no network, degraded path
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "jev_first.mcp_server", "--dir", self.tmp.name],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env)
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self._pump, daemon=True)
        self.reader.start()
        self.addCleanup(self._terminate)

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)

    def _terminate(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait(timeout=10)

    def _send(self, message):
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _request(self, method, params=None, msg_id=None):
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if msg_id is not None:
            message["id"] = msg_id
        self._send(message)

    def _read(self, timeout=20):
        return json.loads(self.lines.get(timeout=timeout))

    def test_stdio_round_trip(self):
        self._request("initialize", {"protocolVersion": "2025-06-18"}, 1)
        self.assertEqual(self._read()["result"]["serverInfo"]["name"], "jev-memory")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._request("tools/list", {}, 2)
        self.assertEqual(len(self._read()["result"]["tools"]), 7)

        self._request("tools/call",
                      {"name": "memory_propose",
                       "arguments": {"text": "All storage must use PostgreSQL.",
                                     "source": "agent"}}, 3)
        proposed = json.loads(self._read()["result"]["content"][0]["text"])
        self.assertEqual(proposed["status"], "pending")
        self.assertTrue(proposed["proposal"]["proposal_id"].startswith("prp_"))

        self._request("tools/call",
                      {"name": "memory_proposals", "arguments": {}}, 31)
        self.assertEqual(
            json.loads(self._read()["result"]["content"][0]["text"])["count"], 1)

        # Confirmation is a human surface (console/CLI), not an MCP tool: seed
        # the confirmed records directly, as a human decision would.
        from jev_first.records import RecordStore
        store = RecordStore(Path(self.tmp.name) / "records.jsonl")
        store.append("All storage must use PostgreSQL.", "agent")
        store.append("SQLite is deprecated for the service.", "agent")

        self._request("tools/call",
                      {"name": "memory_decide",
                       "arguments": {"task": "write an adapter"}}, 5)
        decision = json.loads(self._read()["result"]["content"][0]["text"])
        self.assertTrue(decision["degraded"])
        self.assertEqual(len(decision["actions"]), 2)

        self._request("ping", msg_id=6)
        self.assertEqual(self._read()["id"], 6)


if __name__ == "__main__":
    unittest.main()