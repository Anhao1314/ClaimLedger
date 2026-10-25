"""Composite context: brief authority plus status-filtered optional evidence."""
import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from chat_distiller import (
    ClaimStore, ContextError, EvidenceHit, JsonlEvidenceIndex, build_context,
    serialize_context, suggest_claim,
)
from chat_distiller import claims_cli as claims_module
from chat_distiller.demo import scenario

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "examples" / "rag" / "evidence.jsonl"


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_path = Path(self.tmp.name) / "claims.jsonl"
        scenario.seed(self.store_path)
        self.store = ClaimStore(self.store_path)
        self.index = JsonlEvidenceIndex(EVIDENCE)

    def test_current_packet_excludes_superseded_evidence(self):
        packet = build_context(self.store, "use sqlite", max_bytes=4096,
                               retriever=self.index, top_k=8)
        self.assertEqual(packet["kind"], "context")
        self.assertEqual(packet["authority"], "claim_store")
        self.assertEqual(packet["intent"], "current")
        self.assertGreaterEqual(packet["stale_excluded"], 1)
        claim_ids = [item["claim_id"] for item in packet["evidence"]]
        self.assertIn("clm_9f2a6c1d4e8b73a0", claim_ids)
        self.assertNotIn("clm_4b81e2a7c9d30f56", claim_ids)
        self.assertTrue(all(not item["historical"] for item in packet["evidence"]))
        self.assertEqual(packet["brief"]["counts"]["superseded"], 2)
        wire = serialize_context(packet).encode("utf-8")
        self.assertEqual(len(wire), packet["used_bytes"])
        self.assertLessEqual(packet["used_bytes"], 4096)

    def test_historical_packet_labels_superseded_evidence(self):
        packet = build_context(self.store, "use sqlite", max_bytes=4096,
                               intent="historical", retriever=self.index, top_k=8)
        self.assertEqual(packet["stale_excluded"], 0)
        items = {item["claim_id"]: item for item in packet["evidence"]}
        self.assertIn("clm_4b81e2a7c9d30f56", items)
        self.assertTrue(items["clm_4b81e2a7c9d30f56"]["historical"])
        self.assertEqual(items["clm_4b81e2a7c9d30f56"]["status_label"], "superseded")

    def test_packet_without_a_retriever_is_brief_only(self):
        packet = build_context(self.store, "database", max_bytes=2048)
        self.assertEqual(packet["evidence"], [])
        self.assertEqual(packet["evidence_provider"], "none")
        self.assertEqual(packet["used_bytes"], len(serialize_context(packet).encode("utf-8")))
        self.assertTrue(packet["brief"]["topics"])

    def test_unlinked_and_unknown_evidence_is_counted_not_used(self):
        extra = Path(self.tmp.name) / "extra-evidence.jsonl"
        extra.write_text(
            json.dumps({"id": "unlinked", "text": "migration note without a claim",
                        "source": "scratch"}) + "\n" +
            json.dumps({"id": "unknown", "claim_id": "clm_" + "f" * 16,
                        "text": "migration note with an unknown claim", "source": "scratch"}) + "\n",
            encoding="utf-8")
        index = JsonlEvidenceIndex(extra)
        packet = build_context(self.store, "migration", max_bytes=2048, retriever=index)
        self.assertEqual(packet["evidence"], [])
        self.assertEqual(packet["unlinked_excluded"], 1)
        self.assertEqual(packet["unresolved_excluded"], 1)

    def test_evidence_is_dropped_when_the_byte_budget_is_full(self):
        packet = build_context(self.store, "use sqlite", max_bytes=2048,
                               retriever=self.index, top_k=8)
        self.assertLessEqual(packet["used_bytes"], 2048)
        self.assertEqual(packet["used_bytes"], len(serialize_context(packet).encode("utf-8")))
        self.assertGreaterEqual(packet["evidence_omitted"], 0)

    def test_invalid_evidence_index_is_rejected(self):
        bad = Path(self.tmp.name) / "bad.jsonl"
        bad.write_text("{not json}\n", encoding="utf-8")
        with self.assertRaisesRegex(ContextError, "line 1"):
            JsonlEvidenceIndex(bad)
        with self.assertRaisesRegex(ContextError, "query"):
            build_context(self.store, " ")
        with self.assertRaises(ContextError):
            build_context(self.store, "x", max_bytes=512)

    def test_mcp_recall_uses_the_evidence_adapter(self):
        from chat_distiller.mcp_server import McpServer
        server = McpServer(self.store, self.index)
        response = server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "claim_recall", "arguments": {
                "query": "use sqlite", "max_bytes": 4096, "intent": "current"}},
        })
        text = response["result"]["content"][0]["text"]
        packet = json.loads(text)
        self.assertEqual(packet["evidence_provider"], "jsonl-evidence-index")
        self.assertGreaterEqual(packet["stale_excluded"], 1)
        self.assertEqual(len(text.encode("utf-8")), packet["used_bytes"])

    def test_adaptive_window_finds_current_evidence_behind_stale_hits(self):
        stale = "clm_4b81e2a7c9d30f56"
        current = "clm_9f2a6c1d4e8b73a0"

        class FakeIndex:
            name = "fake"

            def search(self, query, *, top_k=8):
                hits = [EvidenceHit(text=f"stale {i}", claim_id=stale, chunk_id=f"s{i}")
                        for i in range(3)]
                hits.append(EvidenceHit(text="current", claim_id=current, chunk_id="c1"))
                return hits[:top_k]

        packet = build_context(self.store, "anything", max_bytes=4096, retriever=FakeIndex(),
                               top_k=1, max_per_claim=2)
        self.assertEqual(packet["stale_excluded"], 3)
        self.assertEqual([item["claim_id"] for item in packet["evidence"]], [current])
        self.assertGreaterEqual(packet["evidence_attempts"], 2)
        self.assertGreater(packet["evidence_candidate_window"], 3)

    def test_per_claim_quota_keeps_one_claim_from_crowding_the_packet(self):
        current = "clm_9f2a6c1d4e8b73a0"

        class FakeIndex:
            name = "fake"

            def search(self, query, *, top_k=8):
                return [EvidenceHit(text=f"chunk {i}", claim_id=current, chunk_id=f"c{i}")
                        for i in range(3)][:top_k]

        packet = build_context(self.store, "anything", max_bytes=4096, retriever=FakeIndex(),
                               top_k=3, max_per_claim=1)
        self.assertEqual(len(packet["evidence"]), 1)
        self.assertEqual(packet["per_claim_omitted"], 2)

    def test_retriever_timeout_returns_the_brief_instead_of_hanging(self):
        class SlowIndex:
            name = "slow"

            def search(self, query, *, top_k=8):
                time.sleep(0.2)
                return []

        packet = build_context(self.store, "database", max_bytes=2048,
                               retriever=SlowIndex(), retriever_timeout=0.05)
        self.assertEqual(packet["evidence"], [])
        self.assertTrue(packet["evidence_error"].startswith("timeout"))
        self.assertTrue(packet["brief"]["topics"])
        self.assertEqual(packet["used_bytes"], len(serialize_context(packet).encode("utf-8")))

    def test_sealed_index_is_bound_to_a_store_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            sealed_path = Path(tmp) / "sealed.jsonl"
            sealed = JsonlEvidenceIndex(EVIDENCE).seal(sealed_path, self.store.digest())
            self.assertTrue(sealed["sealed"])
            self.assertTrue(sealed["store_matches"])
            self.assertEqual(sealed["chunks"], 9)
            indexed = JsonlEvidenceIndex(sealed_path)
            packet = build_context(self.store, "use sqlite", max_bytes=4096, retriever=indexed)
            self.assertTrue(packet["evidence"])
            self.assertEqual(packet["evidence_index_sha256"], indexed.index_sha256)
            self.store.record("A new operational decision", topic="general")
            with self.assertRaisesRegex(ContextError, "different claim store"):
                build_context(self.store, "use sqlite", max_bytes=4096, retriever=indexed)

    def test_suggest_claim_is_review_only_and_reports_conflicts(self):
        before = len(self.store.claims(status="all"))
        proposal = suggest_claim(
            self.store, "Use SQLite for all Atlas production storage", topic="database",
            retriever=self.index)
        self.assertEqual(proposal["kind"], "claim_proposal")
        self.assertEqual(proposal["status"], "proposed")
        self.assertTrue(proposal["requires_review"])
        self.assertTrue(proposal["resolution_required"])
        self.assertIn("clm_9f2a6c1d4e8b73a0", proposal["conflict_ids"])
        self.assertTrue(proposal["evidence"])
        self.assertTrue(all(not item["historical"] for item in proposal["evidence"]))
        self.assertEqual(len(self.store.claims(status="all")), before)

    def test_mcp_suggest_never_writes(self):
        from chat_distiller.mcp_server import McpServer
        server = McpServer(self.store, self.index)
        before = len(self.store.claims(status="all"))
        response = server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "claim_suggest", "arguments": {
                "text": "Use SQLite for all Atlas production storage", "topic": "database"}},
        })
        proposal = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(proposal["kind"], "claim_proposal")
        self.assertTrue(proposal["resolution_required"])
        self.assertEqual(len(self.store.claims(status="all")), before)

    def test_cli_index_build_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            sealed_path = Path(tmp) / "sealed.jsonl"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = claims_module.main([
                    "index", "build", "--source", str(EVIDENCE), "--out", str(sealed_path),
                    "--store", str(self.store_path),
                ])
            self.assertEqual(rc, 0)
            built = json.loads(output.getvalue())
            self.assertTrue(built["sealed"])
            self.assertTrue(built["store_matches"])
            self.assertEqual(built["chunks"], 9)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = claims_module.main([
                    "index", "status", "--evidence", str(sealed_path),
                    "--store", str(self.store_path),
                ])
            self.assertEqual(rc, 0)
            self.assertTrue(json.loads(output.getvalue())["store_matches"])

            self.store.record("A new operational decision", topic="general")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = claims_module.main([
                    "index", "status", "--evidence", str(sealed_path),
                    "--store", str(self.store_path),
                ])
            self.assertEqual(rc, 1)
            self.assertFalse(json.loads(output.getvalue())["store_matches"])

    def test_cli_suggest_never_writes(self):
        before = len(self.store.claims(status="all"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = claims_module.main([
                "suggest", "--text", "Use SQLite for all Atlas production storage",
                "--topic", "database", "--store", str(self.store_path),
                "--evidence", str(EVIDENCE),
            ])
        self.assertEqual(rc, 0)
        proposal = json.loads(output.getvalue())
        self.assertEqual(proposal["kind"], "claim_proposal")
        self.assertTrue(proposal["resolution_required"])
        self.assertEqual(len(self.store.claims(status="all")), before)

    def test_cli_recall_emits_a_canonical_packet(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = claims_module.main([
                "recall", "--query", "use sqlite", "--store", str(self.store_path),
                "--evidence", str(EVIDENCE), "--max-bytes", "4096", "--compact",
            ])
        self.assertEqual(rc, 0)
        wire = output.getvalue()
        packet = json.loads(wire)
        self.assertEqual(packet["kind"], "context")
        self.assertEqual(len(wire.encode("utf-8")), packet["used_bytes"])
        self.assertEqual(wire, serialize_context(packet))


if __name__ == "__main__":
    unittest.main()
