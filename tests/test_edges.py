"""Offline tests for the edge proposal log. No network."""
import tempfile
import unittest
from pathlib import Path

from jev_first import edges


class EdgeIdTests(unittest.TestCase):
    def test_identity_is_pair_and_type(self):
        a = edges.edge_id("rec_a", "rec_b", "supports")
        self.assertEqual(a, edges.edge_id("rec_a", "rec_b", "supports"))
        self.assertNotEqual(a, edges.edge_id("rec_a", "rec_b", "contradicts"))
        self.assertTrue(a.startswith("edg_"))

    def test_unrelated_is_never_proposable(self):
        with self.assertRaises(ValueError):
            edges.edge_id("rec_a", "rec_b", "unrelated")

    def test_self_edge_rejected(self):
        with self.assertRaises(ValueError):
            edges.edge_id("rec_a", "rec_a", "supports")


class EdgeLogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "edges.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def propose(self, **overrides):
        args = dict(src="rec_a", dst="rec_b", edge_type="supports",
                    confidence=0.92, source="jev")
        args.update(overrides)
        return edges.propose_edge(self.path, **args)

    def test_propose_confirm_round_trip(self):
        proposal = self.propose()
        self.assertEqual(proposal["edge_id"], edges.edge_id("rec_a", "rec_b", "supports"))
        self.assertEqual(edges.statuses(self.path), {proposal["edge_id"]: "pending"})
        self.assertEqual(len(edges.pending(self.path)), 1)
        event = edges.decide_edge(self.path, proposal["edge_id"],
                                  decision="confirmed", by="cli-human")
        self.assertEqual(event["decision"], "confirmed")
        self.assertEqual(edges.statuses(self.path)[proposal["edge_id"]], "confirmed")
        self.assertEqual(edges.pending(self.path), [])
        self.assertEqual(len(edges.confirmed(self.path)), 1)
        self.assertEqual(edges.verify(self.path), 2)

    def test_repropose_pending_or_confirmed_is_a_noop(self):
        first = self.propose()
        self.assertIsNone(self.propose())
        edges.decide_edge(self.path, first["edge_id"],
                          decision="confirmed", by="cli-human")
        self.assertIsNone(self.propose())
        self.assertEqual(edges.verify(self.path), 2)

    def test_repropose_after_rejection_creates_a_new_proposal(self):
        first = self.propose()
        edges.decide_edge(self.path, first["edge_id"],
                          decision="rejected", by="cli-human")
        again = self.propose()
        self.assertIsNotNone(again)
        self.assertEqual(again["edge_id"], first["edge_id"])
        self.assertEqual(edges.statuses(self.path)[first["edge_id"]], "pending")
        self.assertEqual(edges.verify(self.path), 3)

    def test_confidence_is_part_of_the_event_not_the_identity(self):
        self.propose(confidence=0.81)
        self.assertIsNone(self.propose(confidence=0.95))

    def test_double_decision_rejected(self):
        proposal = self.propose()
        edges.decide_edge(self.path, proposal["edge_id"],
                          decision="confirmed", by="cli-human")
        with self.assertRaises(ValueError):
            edges.decide_edge(self.path, proposal["edge_id"],
                              decision="rejected", by="cli-human")

    def test_decision_before_proposal_rejected(self):
        with self.assertRaises(ValueError):
            edges.decide_edge(self.path, "edg_" + "0" * 24,
                              decision="confirmed", by="cli-human")

    def test_bad_inputs_rejected(self):
        with self.assertRaises(ValueError):
            self.propose(edge_type="unrelated")
        with self.assertRaises(ValueError):
            self.propose(confidence=1.5)
        with self.assertRaises(ValueError):
            self.propose(source="")
        with self.assertRaises(ValueError):
            self.propose(src="rec_a", dst="rec_a")

    def test_tampering_breaks_the_chain(self):
        self.propose()
        rows = edges.read(self.path)
        rows[0]["confidence"] = 0.10
        import json
        with open(self.path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False,
                                        sort_keys=True,
                                        separators=(",", ":")) + "\n")
        with self.assertRaises(ValueError):
            edges.verify(self.path)

    def test_judgment_hash_is_carried(self):
        proposal = self.propose(judgment_hash="abc123")
        self.assertEqual(proposal["judgment_hash"], "abc123")

    def test_supersedes_requires_direction(self):
        """edge-schema.v1.json requires_direction: a malformed directed edge
        must be rejected at the log boundary."""
        with self.assertRaises(ValueError):
            self.propose(edge_type="supersedes")
        proposal = self.propose(edge_type="supersedes", direction="src→dst")
        self.assertEqual(proposal["direction"], "src→dst")
        with self.assertRaises(ValueError):
            self.propose(edge_type="supports", direction="sideways")


if __name__ == "__main__":
    unittest.main()
