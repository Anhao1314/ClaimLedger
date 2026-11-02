"""Offline tests for the views: brief, outcomes, calibration, audit."""
import json
import tempfile
import unittest
from pathlib import Path

from chat_distiller import jev
from jev_first import contracts, judge
from jev_first.audit import for_record, summarize, timeline
from jev_first.brief import render_brief
from jev_first.calibration import calibrate
from jev_first.outcomes import append_outcome, verify as verify_outcomes
from jev_first.policy import ADMIT, REVIEW
from tests.test_jev_first import fake_core, make_records


def entry(record_id, text, action, p_admit=None, **extra):
    base = {"record_id": record_id, "text": text, "action": action,
            "confidence": 0.9, "p_admit": p_admit, "governing": False,
            "conflicted": False, "low_margin": False, "included": True}
    base.update(extra)
    return base


def judgment_body(hash_value, entries, *, task="t", model="jev-test",
                  conflicts=None, uncertain=None, degraded=False):
    return {"task": task, "model": model, "question_set_version": "v1",
            "policy": {"version": "v2.2", "governing_at": 0.8, "margin": 0.2},
            "input_hash": "0" * 64, "conflicts": conflicts or [],
            "uncertain_pairs": uncertain or [], "pair_checks": 0,
            "governing": None, "governing_confidence": None,
            "used_bytes": 10, "budget_bytes": 2048, "omitted": 0,
            "latency_ms": 100, "requests": 1, "usage": {},
            "created_at": "2026-11-03T00:00:00Z", "degraded": degraded,
            "judgment_hash": hash_value, "prev_hash": "0" * 64,
            "entries": entries}


class BriefTests(unittest.TestCase):
    def _judgment(self, records, **kwargs):
        return judge("write an adapter", records, model="jev-test", **kwargs)

    def test_admitted_records_become_constraints(self):
        records = make_records(["Use PostgreSQL.", "Skip CI on Fridays."])
        judgment = self._judgment(records, caller=fake_core(
            {r["record_id"]: (ADMIT, 0.9) for r in records}, {}))
        brief = render_brief(judgment)
        self.assertIn("ACTIVE CONSTRAINTS (must follow):", brief["text"])
        self.assertIn("- Use PostgreSQL.", brief["text"])
        self.assertIn("- Skip CI on Fridays.", brief["text"])
        self.assertEqual(brief["bytes"], len(brief["text"].encode("utf-8")))
        self.assertEqual(brief["admitted"], 2)

    def test_conflicts_move_to_warnings(self):
        records = make_records(["Use PostgreSQL.", "SQLite only."])
        judgment = self._judgment(records, caller=fake_core(
            {r["record_id"]: (ADMIT, 0.9) for r in records},
            {(records[0]["text"], records[1]["text"]): "contradiction"}))
        brief = render_brief(judgment)
        self.assertIn("UNRESOLVED CONFLICTS", brief["text"])
        self.assertIn("⟂", brief["text"])
        self.assertIn(records[0]["record_id"], brief["warnings"])

    def test_degraded_note(self):
        records = make_records(["Use PostgreSQL."])
        def boom(state, questions):
            raise jev.JevError("down")
        judgment = self._judgment(records, caller=boom, on_error="review")
        brief = render_brief(judgment)
        self.assertIn("ran degraded", brief["text"])

    def test_thin_margin_is_flagged(self):
        records = make_records(["Use PostgreSQL."])
        def caller(state, questions):
            if "governing" in questions:
                return {"model": "jev-test", "answers": {"governing": {
                    "type": "choice", "choice": "none", "confidence": 0.9}},
                    "usage": {}}
            rid = state.split("CLAIM:\n- ", 1)[1].split(":", 1)[0]
            return {"model": "jev-test", "answers": {"admit": {
                "type": "choice", "choice": ADMIT, "confidence": 0.5,
                "probabilities": {"admit": 0.45, "review": 0.40,
                                  "exclude": 0.15}}}, "usage": {}}
        judgment = self._judgment(records, caller=caller)
        brief = render_brief(judgment)
        self.assertIn("[thin margin", brief["text"])


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "outcomes.jsonl"

    def test_append_and_verify(self):
        first = append_outcome(self.path, judgment_hash="h1",
                               record_id="rec_a", verdict="upheld", by="human")
        second = append_outcome(self.path, judgment_hash="h1",
                                record_id="rec_b", verdict="overturned",
                                by="human", note="it was wrong")
        self.assertEqual(first["prev_hash"], "0" * 64)
        self.assertEqual(second["prev_hash"], first["outcome_hash"])
        self.assertEqual(verify_outcomes(self.path), 2)

    def test_bad_verdict_rejected(self):
        with self.assertRaises(ValueError):
            append_outcome(self.path, judgment_hash="h", record_id="r",
                           verdict="maybe", by="human")

    def test_tampering_detected(self):
        append_outcome(self.path, judgment_hash="h", record_id="r",
                       verdict="upheld", by="human")
        rows = self.path.read_text(encoding="utf-8").splitlines()
        row = json.loads(rows[0])
        row["verdict"] = "overturned"
        rows[0] = json.dumps(row, sort_keys=True, separators=(",", ":"))
        self.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            verify_outcomes(self.path)


class CalibrationTests(unittest.TestCase):
    def test_brier_and_buckets(self):
        judgments = [
            judgment_body("h1", [entry("rec_a", "a", ADMIT, p_admit=0.9)]),
            judgment_body("h2", [entry("rec_b", "b", ADMIT, p_admit=0.6)]),
        ]
        outcomes = [
            {"judgment_hash": "h1", "record_id": "rec_a", "verdict": "upheld"},
            {"judgment_hash": "h2", "record_id": "rec_b", "verdict": "overturned"},
        ]
        report = calibrate(judgments, outcomes)
        self.assertEqual(report["n_scored"], 2)
        self.assertEqual(report["overall_upheld_rate"], 0.5)
        # Brier (mean squared error): (0.01 + 0.36) / 2 = 0.185
        self.assertEqual(report["brier"], 0.185)
        self.assertEqual(report["buckets"]["[0.9,1.0]"]["n"], 1)
        self.assertEqual(report["buckets"]["[0.9,1.0]"]["upheld_rate"], 1.0)
        self.assertEqual(report["buckets"]["[0.6,0.7)"]["upheld_rate"], 0.0)

    def test_orphans_counted_not_dropped(self):
        judgments = [judgment_body("h1", [entry("rec_a", "a", ADMIT, 0.9)])]
        outcomes = [{"judgment_hash": "missing", "record_id": "rec_x",
                     "verdict": "upheld"}]
        report = calibrate(judgments, outcomes)
        self.assertEqual(report["orphans"], 1)
        self.assertEqual(report["n_scored"], 0)
        self.assertIsNone(report["brier"])

    def test_review_entries_out_of_v1_scope(self):
        judgments = [judgment_body("h1", [entry("rec_a", "a", REVIEW, 0.3)])]
        outcomes = [{"judgment_hash": "h1", "record_id": "rec_a",
                     "verdict": "upheld"}]
        report = calibrate(judgments, outcomes)
        self.assertEqual(report["unsupported"], 1)
        self.assertEqual(report["n_scored"], 0)

    def test_unclear_excluded_from_scoring(self):
        judgments = [judgment_body("h1", [entry("rec_a", "a", ADMIT, 0.9)])]
        outcomes = [{"judgment_hash": "h1", "record_id": "rec_a",
                     "verdict": "unclear"}]
        report = calibrate(judgments, outcomes)
        self.assertEqual(report["unsupported"], 1)


class AuditTests(unittest.TestCase):
    def test_summarize_and_for_record(self):
        records = make_records(["Use PostgreSQL.", "SQLite only."])
        judgment = judge("t", records, model="jev-test",
                         caller=fake_core({r["record_id"]: (ADMIT, 0.9)
                                           for r in records},
                                          {(records[0]["text"],
                                            records[1]["text"]): "contradiction"}))
        rows = [judgment.to_dict()]
        summary = summarize("log.jsonl", reader=lambda path: rows)
        self.assertEqual(summary["n_judgments"], 1)
        self.assertEqual(summary["confirmed_conflicts"], 1)
        self.assertEqual(summary["models"], {"jev-test": 1})

        per_record = for_record("log.jsonl", records[0]["record_id"],
                                reader=lambda path: rows)
        self.assertEqual(len(per_record), 1)
        self.assertEqual(per_record[0]["action"], REVIEW)
        self.assertTrue(per_record[0]["conflicted"])

    def test_timeline_newest_first(self):
        rows = [judgment_body("h1", [entry("rec_a", "a", ADMIT, 0.9)],
                              task="old",
                              ), judgment_body("h2", [entry("rec_a", "a", ADMIT, 0.9)],
                                               task="new")]
        rows[0]["created_at"] = "2026-11-01T00:00:00Z"
        rows[1]["created_at"] = "2026-11-03T00:00:00Z"
        out = timeline("log.jsonl", reader=lambda path: rows)
        self.assertEqual([item["task"] for item in out], ["new", "old"])


if __name__ == "__main__":
    unittest.main()