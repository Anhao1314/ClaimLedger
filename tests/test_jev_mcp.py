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

    def test_six_tools_listed(self):
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in response["result"]["tools"]]
        self.assertEqual(names, ["memory_record", "memory_decide", "memory_brief",
                                 "memory_outcome", "memory_calibrate",
                                 "memory_audit"])

    def test_unknown_method_is_jsonrpc_error(self):
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 3, "method": "no/such"})
        self.assertEqual(response["error"]["code"], -32601)

    def test_record_then_duplicate_is_error(self):
        ok = self.server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                 "params": {"name": "memory_record",
                                            "arguments": {"text": "Use PostgreSQL.",
                                                          "source": "agent"}}})
        self.assertFalse(ok["result"]["isError"])
        dup = self.server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                  "params": {"name": "memory_record",
                                             "arguments": {"text": "Use PostgreSQL.",
                                                           "source": "agent"}}})
        self.assertTrue(dup["result"]["isError"])

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

    def test_outcome_then_calibrate(self):
        # Seed the log with a sealed judgment by hand: the server reads the log,
        # it does not care who wrote it.
        records = make_records(["Use PostgreSQL.", "SQLite is deprecated."])
        from jev_first import judge, log as jlog
        from tests.test_jev_first import fake_core
        judgment = judge("t", records, model="jev-test",
                         caller=fake_core({r["record_id"]: (ADMIT, 0.9)
                                           for r in records}, {}))
        jlog.append_judgment(self.server.log_path, judgment.to_dict())
        rid = records[0]["record_id"]
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
             "params": {"name": "memory_outcome",
                        "arguments": {"record_id": rid, "verdict": "upheld",
                                      "by": "human"}}})
        self.assertFalse(response["result"].get("isError", False))
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
        self.assertEqual(len(self._read()["result"]["tools"]), 6)

        self._request("tools/call",
                      {"name": "memory_record",
                       "arguments": {"text": "Use PostgreSQL.",
                                     "source": "agent"}}, 3)
        record = json.loads(self._read()["result"]["content"][0]["text"])["record"]
        self.assertTrue(record["record_id"].startswith("rec_"))

        self._request("tools/call",
                      {"name": "memory_record",
                       "arguments": {"text": "SQLite is deprecated for the service.",
                                     "source": "agent"}}, 4)
        self.assertFalse(self._read()["result"]["isError"])

        self._request("tools/call",
                      {"name": "memory_record",
                       "arguments": {"text": "Use PostgreSQL.",
                                     "source": "agent"}}, 4)
        duplicate = self._read()["result"]
        self.assertTrue(duplicate["isError"])

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