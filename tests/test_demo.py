"""The local demo serves the real claim store over a small JSON API."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from chat_distiller import ClaimStore, ClaimStoreError
from chat_distiller.demo import build_server
from chat_distiller.demo import scenario


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.server, self.temp = build_server(port=0)
        self.addCleanup(self._stop)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base = f"http://{host}:{port}"

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)
        if self.temp is not None:
            import shutil
            shutil.rmtree(self.temp, ignore_errors=True)

    def _request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=body, method=method,
            headers={"Content-Type": "application/json"} if body else {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _get_text(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return response.status, response.read().decode("utf-8")

    def test_seeded_state_is_the_synthetic_scenario(self):
        status, state = self._request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["counts"], {"current": 7, "disputed": 3, "superseded": 2, "total": 12})
        self.assertEqual(len(state["topics"]), 6)
        self.assertTrue(state["writable"])
        self.assertEqual(state["mode"], "demo")
        self.assertTrue(state["seeded"])
        self.assertEqual(state["scenario"]["name"], "Atlas API")
        self.assertTrue(state["rag"]["available"])
        self.assertEqual(state["rag"]["chunks"], 9)
        self.assertEqual(state["rag"]["provider"], "jsonl-evidence-index")
        by_id = {c["claim_id"]: c for c in state["claims"]}
        # The seeded PostgreSQL decision hangs off the ownership premise, and the
        # Doubao import carries the cross-agent narrative into the timeline.
        self.assertEqual(by_id["clm_9f2a6c1d4e8b73a0"]["depends_on"], ["clm_5c1e8a3b7d64f290"])
        self.assertEqual(state["unmotivated"], [])
        self.assertIn("Doubao", by_id["clm_2d8f4c6a1e09b573"]["source"])

    def test_premise_collapse_flags_the_dependent_as_unmotivated(self):
        status, body = self._request("POST", "/api/record", {
            "text": "The platform team disbands; Atlas moves to managed storage",
            "topic": "database", "supersedes": "clm_5c1e8a3b7d64f290",
        })
        self.assertEqual(status, 200)
        status, state = self._request("GET", "/api/state")
        flagged = state["unmotivated"]
        self.assertEqual([u["claim_id"] for u in flagged], ["clm_9f2a6c1d4e8b73a0"])
        self.assertEqual(flagged[0]["broken_dependencies"], ["clm_5c1e8a3b7d64f290"])

    def test_state_at_reconstructs_the_september_world(self):
        status, state = self._request("GET", "/api/state?at=2026-09-30T00:00:00Z")
        self.assertEqual(status, 200)
        self.assertEqual(state["at"], "2026-09-30T00:00:00Z")
        self.assertEqual(state["counts_at"], {"current": 2, "disputed": 0, "superseded": 0, "not_yet": 10})
        by_id = {c["claim_id"]: c for c in state["claims"]}
        self.assertEqual(by_id["clm_4b81e2a7c9d30f56"]["status_at"], "现行")
        self.assertEqual(by_id["clm_9f2a6c1d4e8b73a0"]["status_at"], None)
        status, brief = self._request("GET", "/api/brief?max_bytes=2048&at=2026-09-30T00:00:00Z")
        self.assertEqual(status, 200)
        self.assertEqual(brief["packet"]["at"], "2026-09-30T00:00:00Z")
        self.assertEqual(brief["packet"]["counts"]["current"], 2)

    def test_resolve_closes_a_dispute_over_http(self):
        status, body = self._request("POST", "/api/resolve", {
            "claim_id": "clm_d28b5f0e4c7a9361", "outcome": "withdraw"})
        # The seeded dispute has no standing target, so withdrawal is refused
        # with the store's own guidance instead of a silent success.
        self.assertEqual(status, 400)
        self.assertIn("no standing claim", body["error"])
        status, body = self._request("POST", "/api/record", {
            "text": "API v1 accepts additive fields; mobile caching is the client bug",
            "topic": "api", "dispute": True})
        self.assertEqual(status, 200)
        dispute_id = body["receipt"]["claim_id"]
        self.assertEqual(body["receipt"]["conflicts_with"], ["clm_a17c3d90e5b2f468"])
        status, body = self._request("POST", "/api/resolve", {
            "claim_id": dispute_id, "outcome": "sustain"})
        self.assertEqual(status, 200)
        self.assertTrue(body["receipt"]["promoted"])
        status, state = self._request("GET", "/api/state")
        by_id = {c["claim_id"]: c for c in state["claims"]}
        self.assertEqual(by_id[dispute_id]["status"], "现行")
        self.assertEqual(by_id["clm_a17c3d90e5b2f468"]["status"], "已过期")

    def test_static_shell_is_served(self):
        status, html = self._get_text("/")
        self.assertEqual(status, 200)
        self.assertIn("ClaimLedger", html)
        self.assertIn("Context", html)
        status, script = self._get_text("/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("/api/record", script)
        self.assertIn("/api/context", script)
        self.assertIn("/api/suggest", script)
        self.assertIn("/api/resolve", script)

    def test_record_accepts_scope_and_claims_expose_it(self):
        status, body = self._request("POST", "/api/record", {
            "text": "Use PostgreSQL 17 for all Atlas production storage",
            "topic": "database", "scope": "production", "supersedes": "clm_9f2a6c1d4e8b73a0",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["receipt"]["scope"], "production")
        _, state = self._request("GET", "/api/state")
        successor = next(c for c in state["claims"] if c["scope"] == "production")
        self.assertEqual(successor["text"], "Use PostgreSQL 17 for all Atlas production storage")
        self.assertIn("expires_at", successor)

    def test_conflict_is_refused_then_can_be_superseded(self):
        payload = {
            "text": "Use SQLite for all Atlas production storage",
            "topic": "database", "tags": ["storage"], "source": "test",
        }
        status, body = self._request("POST", "/api/record", payload)
        self.assertEqual(status, 409)
        self.assertEqual(body["error_type"], "Conflict")
        self.assertEqual([c["claim_id"] for c in body["conflicts"]], ["clm_9f2a6c1d4e8b73a0"])

        status, body = self._request(
            "POST", "/api/record",
            dict(payload, supersedes="clm_9f2a6c1d4e8b73a0"))
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["receipt"]["superseded"], "clm_9f2a6c1d4e8b73a0")

        _, state = self._request("GET", "/api/state")
        self.assertEqual(state["counts"]["total"], 13)
        by_id = {c["claim_id"]: c for c in state["claims"]}
        self.assertEqual(by_id["clm_9f2a6c1d4e8b73a0"]["status"], "已过期")
        self.assertEqual(by_id["clm_9f2a6c1d4e8b73a0"]["superseded_by"],
                         body["receipt"]["claim_id"])

    def test_brief_obeys_the_byte_budget_and_reports_omissions(self):
        status, body = self._request("GET", "/api/brief?max_bytes=1024")
        self.assertEqual(status, 200)
        packet = body["packet"]
        self.assertLessEqual(packet["used_bytes"], 1024)
        self.assertEqual(packet["used_bytes"], len(body["wire"].encode("utf-8")))
        self.assertGreater(packet["omitted"], 0)
        self.assertTrue(body["omitted_claims"])
        self.assertEqual(len(body["wire"].encode("utf-8")), body["wire_bytes"])

    def test_search_compares_status_blind_and_status_aware(self):
        # "use sqlite" matches the stale SQLite claim more strongly than the
        # current PostgreSQL one, so the stale-first result is lexical, not a tie-break.
        _, raw = self._request("GET", "/api/search?q=use%20sqlite&include_superseded=1")
        _, aware = self._request("GET", "/api/search?q=use%20sqlite&include_superseded=0")
        self.assertGreater(raw["stale_in_results"], 0)
        self.assertEqual(aware["stale_in_results"], 0)
        self.assertLess(aware["total"], raw["total"])
        self.assertEqual(raw["results"][0]["status"], "已过期")
        self.assertEqual(aware["results"][0]["status"], "现行")

    def test_context_endpoint_joins_evidence_and_filters_stale(self):
        status, body = self._request("GET", "/api/context?q=use%20sqlite&intent=current")
        self.assertEqual(status, 200)
        packet = body["packet"]
        self.assertEqual(packet["kind"], "context")
        self.assertEqual(packet["authority"], "claim_store")
        self.assertEqual(packet["intent"], "current")
        self.assertEqual(packet["stale_excluded"], 1)
        self.assertEqual([hit["chunk_id"] for hit in packet["evidence"]], ["ev_pg_review"])
        self.assertEqual(packet["evidence"][0]["claim_id"], "clm_9f2a6c1d4e8b73a0")
        self.assertEqual(packet["used_bytes"], len(body["wire"].encode("utf-8")))
        self.assertTrue(body["rag_available"])

    def test_context_historical_intent_labels_superseded_evidence(self):
        _, body = self._request("GET", "/api/context?q=use%20sqlite&intent=historical")
        packet = body["packet"]
        self.assertEqual(packet["stale_excluded"], 0)
        self.assertEqual(len(packet["evidence"]), 2)
        historical = [hit for hit in packet["evidence"] if hit["historical"]]
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0]["status_label"], "superseded")

    def test_context_rejects_unknown_intent(self):
        status, body = self._request("GET", "/api/context?q=use%20sqlite&intent=both")
        self.assertEqual(status, 400)
        self.assertIn("intent", body["error"])

    def test_suggest_proposes_without_writing(self):
        _, before = self._request("GET", "/api/state")
        status, body = self._request("POST", "/api/suggest", {
            "text": "Use SQLite for all Atlas production storage",
            "topic": "database", "tags": ["storage"],
        })
        self.assertEqual(status, 200)
        proposal = body["proposal"]
        self.assertEqual(proposal["kind"], "claim_proposal")
        self.assertEqual(proposal["status"], "proposed")
        self.assertTrue(proposal["requires_review"])
        self.assertEqual(proposal["conflict_ids"], ["clm_9f2a6c1d4e8b73a0"])
        self.assertIn("supersede", proposal["suggested_actions"][0])
        _, after = self._request("GET", "/api/state")
        self.assertEqual(before["store"]["sha256"], after["store"]["sha256"])
        self.assertEqual(before["counts"], after["counts"])

    def test_reset_restores_the_scenario(self):
        self._request("POST", "/api/record", {"text": "A new decision", "topic": "general"})
        _, state = self._request("GET", "/api/state")
        self.assertEqual(state["counts"]["total"], 13)
        status, state = self._request("POST", "/api/reset", {})
        self.assertEqual(status, 200)
        self.assertEqual(state["counts"]["total"], 12)
        self.assertEqual(state["counts"]["superseded"], 2)

    def test_safety_endpoints_backup_list_and_audit(self):
        status, backup = self._request("POST", "/api/backup", {})
        self.assertEqual(status, 200)
        self.assertTrue(backup["ok"])
        self.assertEqual(backup["claims"], 12)
        status, listing = self._request("GET", "/api/backups")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["backups"]), 1)
        self.assertEqual(listing["backups"][0]["claims"], 12)
        self.assertTrue(listing["backups"][0]["snapshot"].endswith(".jsonl"))
        status, audit = self._request("GET", "/api/audit?limit=5")
        self.assertEqual(status, 200)
        self.assertEqual(audit["total"], 0)
        self.assertEqual(audit["entries"], [])

    def test_redact_endpoint_requires_writable_and_confirm(self):
        _, state = self._request("GET", "/api/state")
        target = next(c["claim_id"] for c in state["claims"]
                      if c["claim_id"] == "clm_e5d40b7a1c9f2836")
        status, body = self._request("POST", "/api/redact", {"claim_id": target})
        self.assertEqual(status, 400)
        self.assertIn("confirm", body["error"])
        status, body = self._request(
            "POST", "/api/redact", {"claim_id": target, "confirm": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["claim_ids"], [target])
        _, audit = self._request("GET", "/api/audit")
        self.assertEqual(audit["total"], 1)
        self.assertEqual(audit["entries"][0]["action"], "redact")
        _, state = self._request("GET", "/api/state")
        redacted = next(c for c in state["claims"] if c["claim_id"] == target)
        self.assertEqual(redacted["text"], "[redacted]")
        self.assertTrue(redacted["redacted_at"])

    def test_delete_endpoint_names_the_referencing_claim(self):
        _, state = self._request("GET", "/api/state")
        old_claim = next(c for c in state["claims"] if c["superseded_by"] is not None)
        successor = old_claim["superseded_by"]
        # The successor is referenced by the old claim's superseded_by pointer.
        status, body = self._request(
            "POST", "/api/delete", {"claim_id": successor, "confirm": True})
        self.assertEqual(status, 400)
        self.assertIn("referenced", body["error"])
        self.assertIn(old_claim["claim_id"], body["error"])
        # The old claim itself is referenced by nobody and can be deleted alone.
        status, body = self._request(
            "POST", "/api/delete", {"claim_id": old_claim["claim_id"], "confirm": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["claim_ids"], [old_claim["claim_id"]])
        _, audit = self._request("GET", "/api/audit?action=delete")
        self.assertEqual(audit["total"], 1)

    def test_packaged_demo_evidence_matches_the_checkout_example(self):
        root = Path(__file__).resolve().parents[1]
        example = root / "examples" / "rag" / "evidence.jsonl"
        packaged = root / "chat_distiller" / "demo" / "evidence.jsonl"
        self.assertEqual(example.read_bytes(), packaged.read_bytes())

    def test_unknown_routes_and_paths_are_not_served(self):
        status, _ = self._request("GET", "/api/nope")
        self.assertEqual(status, 404)
        status, _ = self._request("GET", "/static/../server.py")
        self.assertEqual(status, 404)


class DemoTestsWithRealStore(unittest.TestCase):
    def _serve(self, path, **kwargs):
        server, temp = build_server(port=0, store_path=path, **kwargs)
        self.assertIsNone(temp)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        host, port = server.server_address[:2]
        return f"http://{host}:{port}"

    def _request(self, base, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            base + path, data=body, method=method,
            headers={"Content-Type": "application/json"} if body else {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_bound_store_is_read_only_and_reset_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            scenario.seed(path)
            base = self._serve(path)
            status, state = self._request(base, "GET", "/api/state")
            self.assertEqual(status, 200)
            self.assertFalse(state["writable"])
            self.assertEqual(state["mode"], "read_only")
            status, body = self._request(base, "POST", "/api/record", {"text": "Another decision"})
            self.assertEqual(status, 403)
            self.assertEqual(body["error_type"], "ReadOnly")
            status, _ = self._request(base, "POST", "/api/reset", {})
            self.assertEqual(status, 403)

    def test_read_only_store_still_reads_context_and_proposes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            scenario.seed(path)
            base = self._serve(path)
            status, body = self._request(base, "GET", "/api/context?q=use%20sqlite")
            self.assertEqual(status, 200)
            self.assertEqual(body["packet"]["used_bytes"], len(body["wire"].encode("utf-8")))
            status, body = self._request(base, "POST", "/api/suggest",
                                         {"text": "Use SQLite for all Atlas storage"})
            self.assertEqual(status, 200)
            self.assertEqual(body["proposal"]["conflict_ids"], ["clm_9f2a6c1d4e8b73a0"])
            self.assertFalse(self._request(base, "GET", "/api/state")[1]["writable"])

    def test_safety_writes_are_refused_for_read_only_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            scenario.seed(path)
            base = self._serve(path)
            _, state = self._request(base, "GET", "/api/state")
            target = state["claims"][0]["claim_id"]
            status, body = self._request(base, "POST", "/api/redact",
                                         {"claim_id": target, "confirm": True})
            self.assertEqual(status, 403)
            self.assertEqual(body["error_type"], "ReadOnly")
            status, body = self._request(base, "POST", "/api/delete",
                                         {"claim_id": target, "confirm": True})
            self.assertEqual(status, 403)
            status, body = self._request(base, "POST", "/api/backup", {})
            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])

    def test_empty_bound_store_is_not_seeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            path.write_text("", encoding="utf-8")
            base = self._serve(path)
            _, state = self._request(base, "GET", "/api/state")
            self.assertEqual(state["counts"]["total"], 0)
            self.assertFalse(state["seeded"])
            self.assertFalse(state["writable"])
            self.assertEqual(path.read_text(encoding="utf-8"), "")
            status, _ = self._request(base, "POST", "/api/record", {"text": "No accidental write"})
            self.assertEqual(status, 403)
            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_write_mode_allows_record_without_seeding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            path.write_text("", encoding="utf-8")
            base = self._serve(path, writable=True)
            _, state = self._request(base, "GET", "/api/state")
            self.assertEqual(state["counts"]["total"], 0)
            self.assertTrue(state["writable"])
            self.assertEqual(state["mode"], "read_write")
            status, body = self._request(base, "POST", "/api/record", {"text": "A real decision"})
            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            _, state = self._request(base, "GET", "/api/state")
            self.assertEqual(state["counts"]["total"], 1)
            status, _ = self._request(base, "POST", "/api/reset", {})
            self.assertEqual(status, 403)

    def test_seed_is_explicit_for_a_bound_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            path.write_text("", encoding="utf-8")
            base = self._serve(path, writable=True, seed=True)
            _, state = self._request(base, "GET", "/api/state")
            self.assertEqual(state["counts"]["total"], 12)
            self.assertTrue(state["seeded"])
            self.assertTrue(state["writable"])

    def test_missing_bound_store_requires_an_explicit_write_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.jsonl"
            with self.assertRaises(ClaimStoreError):
                build_server(port=0, store_path=path)
            self.assertFalse(path.exists())

    def test_multi_conflict_requires_every_target_in_the_demo_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            store = ClaimStore(path)
            base = store.record("Use SQLite for all storage", topic="database")["recorded"]
            second = dict(base, claim_id="clm_" + "b" * 16,
                          text="Use SQLite for all production storage")
            body = "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                for row in [*store.claims(status="all"), second])
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
            base_url = self._serve(path, writable=True)
            payload = {"text": "Use SQLite for all storage in production", "topic": "database"}
            status, error = self._request(base_url, "POST", "/api/record", payload)
            self.assertEqual(status, 409)
            self.assertEqual(error["error_type"], "Conflict")
            self.assertEqual(len(error["conflicts"]), 2)

            payload["supersedes"] = [base["claim_id"], second["claim_id"]]
            status, receipt = self._request(base_url, "POST", "/api/record", payload)
            self.assertEqual(status, 200)
            self.assertEqual(receipt["receipt"]["superseded_claims"],
                             [base["claim_id"], second["claim_id"]])
            _, state = self._request(base_url, "GET", "/api/state")
            self.assertEqual(state["counts"], {"current": 1, "disputed": 0, "superseded": 2, "total": 3})


if __name__ == "__main__":
    unittest.main()
