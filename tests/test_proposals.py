"""Offline tests for the proposal log: agent writes wait for a human."""
import json
import tempfile
import unittest
from pathlib import Path

from jev_first import proposals


class ProposalLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "proposals.jsonl"

    def test_propose_is_pending_and_verifies(self):
        row = proposals.propose(self.path, text="Use PostgreSQL.", source="agent")
        self.assertTrue(row["proposal_id"].startswith("prp_"))
        self.assertEqual(proposals.verify(self.path), 1)
        self.assertEqual(len(proposals.pending(self.path)), 1)
        self.assertEqual(proposals.statuses(self.path), {
            row["proposal_id"]: "pending"})

    def test_confirm_requires_the_record_it_created(self):
        row = proposals.propose(self.path, text="Use PostgreSQL.", source="agent")
        with self.assertRaises(ValueError):
            proposals.decide(self.path, row["proposal_id"],
                             decision="confirmed", by="human")

    def test_confirm_and_reject_are_terminal(self):
        first = proposals.propose(self.path, text="Use PostgreSQL.", source="agent")
        second = proposals.propose(self.path, text="Cap retries at 3.",
                                   source="agent")
        proposals.decide(self.path, first["proposal_id"], decision="confirmed",
                         by="human", record_id="rec_a")
        proposals.decide(self.path, second["proposal_id"], decision="rejected",
                         by="human")
        self.assertEqual(proposals.statuses(self.path), {
            first["proposal_id"]: "confirmed",
            second["proposal_id"]: "rejected"})
        self.assertEqual(proposals.pending(self.path), [])
        self.assertEqual(proposals.verify(self.path), 4)
        with self.assertRaises(ValueError):
            proposals.decide(self.path, first["proposal_id"],
                             decision="rejected", by="human")

    def test_unknown_proposal_is_refused(self):
        with self.assertRaises(ValueError):
            proposals.decide(self.path, "prp_missing", decision="rejected",
                             by="human")

    def test_tampering_is_detected(self):
        proposals.propose(self.path, text="Use PostgreSQL.", source="agent")
        rows = self.path.read_text(encoding="utf-8").splitlines()
        body = json.loads(rows[0])
        body["text"] = "Use MySQL."
        rows[0] = json.dumps(body, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        self.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            proposals.verify(self.path)

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            proposals.propose(self.path, text="", source="agent")
        with self.assertRaises(ValueError):
            proposals.propose(self.path, text="Use PostgreSQL.", source="")


if __name__ == "__main__":
    unittest.main()