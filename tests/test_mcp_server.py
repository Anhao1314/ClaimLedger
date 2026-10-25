"""MCP stdio server: real subprocess, line-delimited JSON-RPC round trips."""
import json
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from chat_distiller import __version__


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_path = Path(self.tmp.name) / "claims.jsonl"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "chat_distiller.mcp_server", "--store", str(self.store_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # A reader thread keeps the test portable: select() does not support
        # pipe handles on Windows.
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

    def _read(self, timeout=15):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            self.fail("MCP server did not respond in time")
        if not line:
            self.fail("MCP server closed stdout")
        return json.loads(line)

    def _initialize(self):
        self._request("initialize", {"protocolVersion": "2025-06-18",
                                     "clientInfo": {"name": "test", "version": "0"}}, msg_id=1)
        response = self._read()
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["name"], "claim-ledger")
        self.assertEqual(response["result"]["serverInfo"]["version"], __version__)
        self.assertIn("tools", response["result"]["capabilities"])
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return response

    def _call(self, name, arguments, msg_id):
        self._request("tools/call", {"name": name, "arguments": arguments}, msg_id=msg_id)
        return self._read()

    def _result_text(self, response):
        self.assertNotIn("error", response, response)
        self.assertFalse(response["result"]["isError"])
        return json.loads(response["result"]["content"][0]["text"])

    def test_initialize_echoes_supported_protocol_version(self):
        response = self._initialize()
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")

    def test_initialize_falls_back_on_unknown_version(self):
        self._request("initialize", {"protocolVersion": "1999-01-01"}, msg_id=7)
        response = self._read()
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")

    def test_tools_list_exposes_six_tools_with_schemas(self):
        self._initialize()
        self._request("tools/list", {}, msg_id=2)
        response = self._read()
        tools = {t["name"]: t for t in response["result"]["tools"]}
        self.assertEqual(set(tools), {"claim_brief", "claim_record", "claim_claims",
                                      "claim_recall", "claim_resolve", "claim_suggest"})
        self.assertEqual(tools["claim_resolve"]["inputSchema"]["required"],
                         ["claim_id", "outcome"])
        self.assertIn("at", tools["claim_brief"]["inputSchema"]["properties"])
        self.assertIn("depends_on", tools["claim_record"]["inputSchema"]["properties"])
        self.assertEqual(tools["claim_record"]["inputSchema"]["required"], ["text"])
        self.assertEqual(tools["claim_recall"]["inputSchema"]["required"], ["query"])
        self.assertEqual(tools["claim_suggest"]["inputSchema"]["required"], ["text"])

    def test_record_with_scope_and_brief_scope_filter(self):
        from datetime import datetime, timedelta, timezone
        self._initialize()
        first = self._result_text(self._call(
            "claim_record",
            {"text": "数据库统一使用 SQLite", "topic": "database", "scope": "production"},
            msg_id=20))
        self.assertTrue(first["ok"])
        self.assertEqual(first["recorded"]["scope"], "production")
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        second = self._result_text(self._call(
            "claim_record",
            {"text": "构建仍走旧流水线", "topic": "build", "expires_at": expires},
            msg_id=21))
        self.assertTrue(second["ok"])
        self.assertEqual(second["recorded"]["expires_at"], expires)
        rejected = self._call("claim_record",
                              {"text": "时间倒流的声明", "expires_at": "2020-01-01T00:00:00Z"},
                              msg_id=22)
        self.assertTrue(rejected["result"]["isError"])
        self.assertIn("future", rejected["result"]["content"][0]["text"])
        brief = self._result_text(self._call("claim_brief", {"scope": "staging"}, msg_id=23))
        self.assertEqual(brief["scope"], "staging")
        # Only the all-scope build claim applies to staging.
        self.assertEqual(brief["counts"]["current"], 1)
        production = self._result_text(self._call("claim_brief", {"scope": "production"}, msg_id=24))
        self.assertEqual(production["counts"]["current"], 2)
        everything = self._result_text(self._call("claim_brief", {}, msg_id=25))
        self.assertEqual(everything["counts"]["current"], 2)

    def test_record_conflict_and_resolve_round_trip(self):
        self._initialize()
        first = self._result_text(self._call(
            "claim_record", {"text": "数据库统一使用 SQLite", "topic": "database"}, msg_id=3))
        self.assertTrue(first["ok"])
        old_id = first["recorded"]["claim_id"]
        conflict = self._call("claim_record",
                              {"text": "数据库统一使用 PostgreSQL", "topic": "database"}, msg_id=4)
        self.assertTrue(conflict["result"]["isError"])
        self.assertIn("possible conflict", conflict["result"]["content"][0]["text"])
        resolved = self._result_text(self._call(
            "claim_record",
            {"text": "数据库统一使用 PostgreSQL", "topic": "database", "supersedes": old_id},
            msg_id=5))
        self.assertEqual(resolved["superseded"], old_id)

    def test_brief_via_mcp_keeps_wire_byte_contract(self):
        from chat_distiller import serialize_packet
        self._initialize()
        self._call("claim_record", {"text": "API v1 保持冻结"}, msg_id=6)
        self._call("claim_record", {"text": "迁移方案仍有分歧"}, msg_id=7)  # no conflict -> current
        response = self._call("claim_brief", {}, msg_id=8)
        text = response["result"]["content"][0]["text"]
        packet = json.loads(text)
        self.assertEqual(len(text.encode("utf-8")), packet["used_bytes"])
        self.assertEqual(text, serialize_packet(packet))
        self.assertEqual(packet["status"], "ready")
        self.assertEqual(packet["disputed"], [])
        self.assertIn("API v1 保持冻结", text)

    def test_recall_returns_a_brief_only_context_without_an_evidence_index(self):
        self._initialize()
        self._call("claim_record", {"text": "召回用的声明"}, msg_id=30)
        response = self._call("claim_recall", {"query": "召回"}, msg_id=31)
        text = response["result"]["content"][0]["text"]
        packet = json.loads(text)
        self.assertEqual(packet["kind"], "context")
        self.assertEqual(packet["authority"], "claim_store")
        self.assertEqual(packet["evidence"], [])
        self.assertEqual(packet["evidence_provider"], "none")
        self.assertEqual(len(text.encode("utf-8")), packet["used_bytes"])
        self.assertLessEqual(packet["used_bytes"], packet["budget_bytes"])
        self.assertIn("召回用的声明", text)

    def test_claims_listing_and_status_filter(self):
        self._initialize()
        self._call("claim_record", {"text": "现行声明"}, msg_id=9)
        self._call("claim_record", {"text": "争议声明", "dispute": True}, msg_id=10)
        listing = self._result_text(self._call("claim_claims", {"status": "现行"}, msg_id=11))
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["claims"][0]["text"], "现行声明")
        english = self._result_text(self._call("claim_claims", {"status": "disputed"}, msg_id=20))
        self.assertEqual(english["count"], 1)
        self.assertEqual(english["claims"][0]["text"], "争议声明")
        everything = self._result_text(self._call("claim_claims", {"status": "all"}, msg_id=12))
        self.assertEqual(everything["count"], 2)

    def test_unknown_method_and_unknown_tool_are_jsonrpc_errors(self):
        self._initialize()
        self._request("resources/list", {}, msg_id=13)
        response = self._read()
        self.assertEqual(response["error"]["code"], -32601)
        self._request("tools/call", {"name": "nonexistent", "arguments": {}}, msg_id=14)
        response = self._read()
        self.assertEqual(response["error"]["code"], -32602)

    def test_notifications_produce_no_response_and_ping_answers(self):
        self._initialize()
        self._send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}})
        self._request("ping", {}, msg_id=15)
        response = self._read()
        self.assertEqual(response["id"], 15)
        self.assertEqual(response["result"], {})

    def test_store_is_bound_at_launch(self):
        self._initialize()
        self._call("claim_record", {"text": "启动时绑定的库"}, msg_id=16)
        self.assertTrue(self.store_path.is_file())

    def test_resolve_closes_a_dispute_over_mcp(self):
        self._initialize()
        standing = self._result_text(self._call(
            "claim_record", {"text": "数据库统一使用 SQLite", "topic": "database"}, msg_id=30))
        disputed = self._result_text(self._call(
            "claim_record",
            {"text": "数据库统一使用 PostgreSQL", "topic": "database", "dispute": True},
            msg_id=31))
        self.assertEqual(disputed["recorded"]["disputes"], [standing["recorded"]["claim_id"]])
        resolved = self._result_text(self._call(
            "claim_resolve",
            {"claim_id": disputed["recorded"]["claim_id"], "outcome": "sustain"},
            msg_id=32))
        self.assertTrue(resolved["ok"])
        self.assertTrue(resolved["promoted"])
        rows = self._result_text(self._call(
            "claim_claims", {"status": "all"}, msg_id=33))
        by_id = {c["claim_id"]: c for c in rows["claims"]}
        self.assertEqual(by_id[disputed["recorded"]["claim_id"]]["status"], "现行")
        self.assertEqual(by_id[standing["recorded"]["claim_id"]]["status"], "已过期")

    def test_brief_and_claims_reconstruct_as_of_an_instant(self):
        self._initialize()
        recorded = self._result_text(self._call(
            "claim_record", {"text": "缓存由网关统一管理", "topic": "cache"}, msg_id=40))
        self.assertTrue(recorded["ok"])
        future = self._result_text(self._call(
            "claim_claims", {"status": "current", "at": "2999-01-01T00:00:00Z"}, msg_id=41))
        self.assertEqual(future["count"], 1)
        packet = self._result_text(self._call(
            "claim_brief", {"at": "2000-01-01T00:00:00Z"}, msg_id=42))
        self.assertEqual(packet["counts"]["current"], 0)
        self.assertEqual(packet["at"], "2000-01-01T00:00:00Z")

    def test_record_with_depends_on_flags_fallen_premise_in_brief(self):
        self._initialize()
        premise = self._result_text(self._call(
            "claim_record", {"text": "平台团队长期维护 PostgreSQL", "topic": "database"},
            msg_id=50))
        dependent = self._result_text(self._call(
            "claim_record",
            {"text": "数据库统一使用 PostgreSQL", "topic": "database",
             "depends_on": [premise["recorded"]["claim_id"]]},
            msg_id=51))
        self.assertEqual(dependent["recorded"]["depends_on"],
                         [premise["recorded"]["claim_id"]])
        collapsed = self._result_text(self._call(
            "claim_record",
            {"text": "平台团队解散，无人维护 PostgreSQL", "topic": "database",
             "supersedes": premise["recorded"]["claim_id"]},
            msg_id=52))
        self.assertTrue(collapsed["ok"])
        brief = self._call("claim_brief", {}, msg_id=53)
        text = brief["result"]["content"][0]["text"]
        self.assertIn('"unmotivated"', text)
        self.assertIn(dependent["recorded"]["claim_id"], text)


if __name__ == "__main__":
    unittest.main()
