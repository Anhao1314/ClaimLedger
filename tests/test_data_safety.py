"""Backups, restores, redaction and deletion for the claim store."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from chat_distiller import (
    ClaimStore, ClaimStoreError, JsonlEvidenceIndex, build_context,
)


class DataSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store_path = self.root / "claims.jsonl"
        self.store = ClaimStore(self.store_path)

    def unique(self):
        return uuid.uuid4().hex

    def chain(self):
        old = self.store.record(
            "Use SQLite for all storage zqold", source="old source",
            quote="old secret quote", tags=["old-secret"])["recorded"]
        new = self.store.record(
            "Use PostgreSQL for all storage zqnew", supersedes=old["claim_id"],
            source="new source", quote="new secret quote", tags=["new-secret"])["recorded"]
        return old, new

    def test_backup_manifest_and_restore_roundtrip(self):
        first = self.store.record(self.unique())["recorded"]
        second = self.store.record(self.unique())["recorded"]
        backup = self.store.backup()
        self.assertTrue(Path(backup["path"]).is_file())
        self.assertTrue(Path(backup["manifest"]).is_file())
        self.assertEqual(backup["claims"], 2)
        manifest = json.loads(Path(backup["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["kind"], "claim-ledger-backup")
        self.assertEqual(manifest["store_sha256"], backup["store_sha256"])

        self.store.record(self.unique())
        self.assertEqual(len(self.store.claims(status="all")), 3)
        restored = self.store.restore(backup["path"], overwrite=True)
        self.assertEqual(restored["claims"], 2)
        self.assertTrue(restored["backup_of_previous"])
        rows = self.store.claims(status="all")
        self.assertEqual({row["claim_id"] for row in rows},
                         {first["claim_id"], second["claim_id"]})
        self.assertTrue((self.root / "claims.audit.jsonl").is_file())

    def test_backup_of_a_missing_store_is_refused(self):
        with self.assertRaisesRegex(ClaimStoreError, "not found"):
            self.store.backup()

    def test_backups_listing_reports_manifest_facts(self):
        self.store.record(self.unique())
        backup = self.store.backup()
        listing = self.store.backups()
        self.assertEqual(listing["directory"], str(self.root / "backups"))
        self.assertEqual(len(listing["backups"]), 1)
        entry = listing["backups"][0]
        self.assertEqual(entry["snapshot"], Path(backup["path"]).name)
        self.assertTrue(entry["present"])
        self.assertEqual(entry["claims"], 1)
        self.assertEqual(entry["file_sha256"], backup["file_sha256"])

    def test_backup_keep_prunes_older_snapshots(self):
        self.store.record(self.unique())
        backup_dir = self.root / "keep"
        for _ in range(3):
            self.store.backup(backup_dir)
        self.assertEqual(len(list(backup_dir.glob("*.jsonl"))), 3)
        result = self.store.backup(backup_dir, keep=2)
        self.assertEqual(len(result["pruned"]), 2)
        remaining = sorted(p.name for p in backup_dir.glob("*.jsonl"))
        self.assertEqual(len(remaining), 2)
        self.assertIn(Path(result["path"]).name, remaining)
        self.assertEqual(len(list(backup_dir.glob("*.manifest.json"))), 2)
        with self.assertRaisesRegex(ClaimStoreError, "keep"):
            self.store.backup(backup_dir, keep=0)

    def test_audit_entries_are_validated_and_filtered(self):
        claim = self.store.record(self.unique())["recorded"]
        self.store.redact(claim["claim_id"])
        restored = self.store.backup()
        listing = self.store.audit_entries()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["entries"][0]["action"], "redact")
        self.assertEqual(listing["entries"][0]["claim_ids"], [claim["claim_id"]])
        self.assertIsNone(listing["entries"][0]["actor"])
        filtered = self.store.audit_entries(action="delete")
        self.assertEqual(filtered["total"], 0)
        with self.assertRaisesRegex(ClaimStoreError, "action"):
            self.store.audit_entries(action="export")
        corrupt = self.root / "claims.audit.jsonl"
        corrupt.write_text("{broken}\n", encoding="utf-8")
        with self.assertRaisesRegex(ClaimStoreError, "audit"):
            self.store.audit_entries()

    def test_init_creates_an_empty_store_and_refuses_data(self):
        target = self.root / "fresh" / "claims.jsonl"
        result = self.store.__class__(target).init()
        self.assertTrue(result["created"])
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), b"")
        self.assertIn("claim record", result["next_steps"][0])
        again = self.store.__class__(target).init()
        self.assertFalse(again["created"])
        target.write_text('{"claim_id": "clm_' + 'a' * 16 + '"}\n', encoding="utf-8")
        with self.assertRaisesRegex(ClaimStoreError, "not empty"):
            self.store.__class__(target).init()

    def test_cli_init_backups_and_audit(self):
        from chat_distiller import claims_cli as claims_module
        target = self.root / "cli" / "claims.jsonl"
        rc = claims_module.main(["init", "--store", str(target)])
        self.assertEqual(rc, 0)
        rc = claims_module.main(["record", self.unique(), "--store", str(target)])
        self.assertEqual(rc, 0)
        rc = claims_module.main(["backups", "--store", str(target)])
        self.assertEqual(rc, 0)
        rc = claims_module.main(["audit", "--store", str(target)])
        self.assertEqual(rc, 0)
        rc = claims_module.main(["backup", "--store", str(target), "--keep", "1"])
        self.assertEqual(rc, 0)
        rc = claims_module.main(["audit", "--store", str(target), "--action", "delete"])
        self.assertEqual(rc, 0)

    def test_restore_requires_a_manifest_or_explicit_unverified_flag(self):
        self.store.record(self.unique())
        backup = self.store.backup()
        raw = self.root / "raw.jsonl"
        raw.write_bytes(Path(backup["path"]).read_bytes())
        with self.assertRaisesRegex(ClaimStoreError, "manifest"):
            self.store.restore(raw, overwrite=True)
        restored = self.store.restore(raw, overwrite=True, allow_unverified=True)
        self.assertEqual(restored["claims"], 1)

    def test_restore_refuses_to_replace_without_overwrite(self):
        self.store.record(self.unique())
        backup = self.store.backup()
        with self.assertRaisesRegex(ClaimStoreError, "not empty"):
            self.store.restore(backup["path"])
        self.assertEqual(len(self.store.claims(status="all")), 1)

    def test_tampered_backup_is_rejected(self):
        self.store.record(self.unique())
        backup = self.store.backup()
        target = Path(backup["path"])
        target.write_bytes(target.read_bytes() + b"\n")
        with self.assertRaisesRegex(ClaimStoreError, "digest|byte count"):
            self.store.restore(target, overwrite=True)

    def test_redact_scrubs_content_but_preserves_identity_and_chain(self):
        old, new = self.chain()
        result = self.store.redact(old["claim_id"])
        self.assertFalse(result["already_redacted"])
        self.assertTrue(Path(result["backup"]["path"]).is_file())
        rows = {row["claim_id"]: row for row in self.store._read()}
        redacted = rows[old["claim_id"]]
        self.assertEqual(redacted["text"], "[redacted]")
        self.assertEqual(redacted["tags"], [])
        self.assertIsNone(redacted["source"])
        self.assertIsNone(redacted["quote"])
        self.assertIsNone(redacted["session_hint"])
        self.assertIn("redacted_at", redacted)
        self.assertEqual(redacted["topic"], "redacted")
        self.assertEqual(redacted["status"], "已过期")
        self.assertEqual(redacted["superseded_by"], new["claim_id"])

        visible = self.store.claims(status="all")
        self.assertEqual([row["claim_id"] for row in visible], [new["claim_id"]])
        with_redacted = self.store.claims(status="all", include_redacted=True)
        self.assertEqual(len(with_redacted), 2)
        packet = self.store.brief()
        self.assertEqual(packet["counts"]["superseded"], 0)
        self.assertEqual(packet["recently_superseded"], [])

        audit = (self.root / "claims.audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"action":"redact"', audit)
        self.assertNotIn("old secret quote", audit)
        self.assertNotIn("old source", audit)
        self.assertNotIn("Use SQLite", audit)

    def test_redact_can_skip_the_plaintext_backup(self):
        claim = self.store.record("zqnobackup decision")["recorded"]
        result = self.store.redact(claim["claim_id"], keep_backup=False)
        self.assertIsNone(result["backup"])
        self.assertFalse((self.root / "backups").exists())
        self.assertTrue((self.root / "claims.audit.jsonl").is_file())

    def test_audit_failure_rolls_the_store_back(self):
        claim = self.store.record("zqrollback decision")["recorded"]
        (self.root / "claims.audit.jsonl").mkdir()
        with self.assertRaisesRegex(ClaimStoreError, "audit"):
            self.store.redact(claim["claim_id"])
        rows = self.store._read()
        self.assertEqual(rows[0]["text"], "zqrollback decision")

    def test_redact_is_idempotent(self):
        claim = self.store.record(self.unique())["recorded"]
        self.store.redact(claim["claim_id"])
        again = self.store.redact(claim["claim_id"])
        self.assertTrue(again["already_redacted"])
        self.assertEqual(len(self.store._read()), 1)

    def test_redact_cascade_scrubs_the_whole_chain(self):
        old, new = self.chain()
        result = self.store.redact(new["claim_id"], cascade=True)
        self.assertEqual(result["claim_ids"], sorted([old["claim_id"], new["claim_id"]]))
        rows = self.store._read()
        self.assertEqual({row["text"] for row in rows}, {"[redacted]"})
        rows = {row["claim_id"]: row for row in rows}
        self.assertEqual(rows[old["claim_id"]]["superseded_by"], new["claim_id"])

    def test_delete_refuses_a_referenced_claim_and_cascade_removes_the_chain(self):
        old, new = self.chain()
        with self.assertRaisesRegex(ClaimStoreError, "referenced"):
            self.store.delete(new["claim_id"])
        result = self.store.delete(new["claim_id"], cascade=True)
        self.assertEqual(result["claim_ids"], sorted([old["claim_id"], new["claim_id"]]))
        self.assertEqual(self.store._read(), [])
        self.assertEqual(self.store.brief()["status"], "empty")

    def test_delete_of_an_unreferenced_old_claim_keeps_the_successor(self):
        old, new = self.chain()
        self.store.delete(old["claim_id"])
        rows = self.store.claims(status="all")
        self.assertEqual([row["claim_id"] for row in rows], [new["claim_id"]])

    def test_redacted_claims_are_excluded_from_rag_evidence(self):
        claim = self.store.record("zqredactable database decision")["recorded"]
        evidence_path = self.root / "evidence.jsonl"
        evidence_path.write_text(json.dumps({
            "id": "ev1", "claim_id": claim["claim_id"],
            "text": "zqredactable supporting passage",
        }) + "\n", encoding="utf-8")
        index = JsonlEvidenceIndex(evidence_path)
        before = build_context(self.store, "zqredactable", retriever=index)
        self.assertEqual(len(before["evidence"]), 1)
        self.store.redact(claim["claim_id"])
        after = build_context(self.store, "zqredactable", retriever=index)
        self.assertEqual(after["evidence"], [])
        self.assertEqual(after["unresolved_excluded"], 1)

    def test_cli_backup_redact_delete_and_restore(self):
        from chat_distiller import claims_cli as claims_module
        claim = self.store.record(self.unique())["recorded"]
        backup_dir = self.root / "cli-backups"
        rc = claims_module.main([
            "backup", "--store", str(self.store_path), "--out", str(backup_dir), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(list(backup_dir.glob("*.jsonl"))), 1)

        rc = claims_module.main(["redact", claim["claim_id"], "--store", str(self.store_path)])
        self.assertEqual(rc, 1)
        rc = claims_module.main([
            "redact", claim["claim_id"], "--store", str(self.store_path),
            "--yes", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.store.claims(status="all"), [])

        backup_path = list(backup_dir.glob("*.jsonl"))[0]
        rc = claims_module.main([
            "restore", "--from", str(backup_path), "--store", str(self.store_path),
            "--yes", "--backup-dir", str(self.root / "restore-backups")])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.store.claims(status="all")), 1)

        rc = claims_module.main([
            "delete", claim["claim_id"], "--store", str(self.store_path), "--yes"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.store.claims(status="all")), 0)


if __name__ == "__main__":
    unittest.main()
