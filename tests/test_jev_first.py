"""Offline tests for the Jev-first decision layer. No network."""
import json
import tempfile
import unittest
from pathlib import Path

from jev_first import Policy, build_questions, decide, render_state
from jev_first import log
from jev_first.policy import ADMIT, EXCLUDE, REVIEW

CLAIMS = [
    {"claim_id": "clm_a", "text": "All storage must use PostgreSQL."},
    {"claim_id": "clm_b", "text": "PostgreSQL is banned for the analytics service."},
    {"claim_id": "clm_c", "text": "The release train leaves on Friday."},
]


def fake_caller(probabilities, governing="none", contradiction=0.0):
    """probabilities: {claim_id: (p_applies, p_holds)}"""
    def call(state, questions):
        answers = {"contradiction": {"type": "noul", "noul": contradiction}}
        for claim_id, (applies, holds) in probabilities.items():
            answers[f"applies::{claim_id}"] = {"type": "noul", "noul": applies}
            answers[f"holds::{claim_id}"] = {"type": "noul", "noul": holds}
        answers["governing"] = {
            "type": "choice", "choice": governing, "confidence": 0.9,
            "probabilities": {governing: 0.9},
        }
        return {"model": "jev-test", "answers": answers, "usage": {"input_tokens": 10}}
    return call


class QuestionTests(unittest.TestCase):
    def test_state_defaults_to_no_status(self):
        text = render_state("do a thing", CLAIMS)
        self.assertIn("TASK: do a thing", text)
        self.assertIn("clm_a: All storage must use PostgreSQL.", text)
        self.assertNotIn("recorded status", text)

    def test_status_is_opt_in(self):
        claims = [{"claim_id": "clm_a", "text": "x", "status": "已过期"}]
        self.assertIn("recorded status", render_state("t", claims, include_status=True))

    def test_one_question_pair_per_claim_plus_two(self):
        questions = build_questions(CLAIMS)
        self.assertEqual(len(questions), len(CLAIMS) * 2 + 2)
        self.assertIn("applies::clm_a", questions)
        self.assertIn("holds::clm_c", questions)
        self.assertEqual(questions["governing"]["type"], "choice")
        self.assertIn("none", questions["governing"]["criteria"])

    def test_reserved_id_rejected(self):
        with self.assertRaises(ValueError):
            build_questions([{"claim_id": "governing", "text": "x"}])

    def test_empty_claims_rejected(self):
        with self.assertRaises(ValueError):
            build_questions([])


class PolicyTests(unittest.TestCase):
    def test_bands(self):
        policy = Policy()
        self.assertEqual(policy.action(0.90), ADMIT)
        self.assertEqual(policy.action(0.45), REVIEW)
        self.assertEqual(policy.action(0.10), EXCLUDE)

    def test_contradiction_forces_review_not_exclusion(self):
        policy = Policy()
        self.assertEqual(policy.action(0.90, contradiction=0.95), REVIEW)
        self.assertEqual(policy.action(0.45, contradiction=0.95), REVIEW)

    def test_irrelevant_claim_still_excluded_under_contradiction(self):
        # A claim that does not constrain the task is not made relevant by a
        # contradiction elsewhere in the set.
        self.assertEqual(Policy().action(0.05, contradiction=0.99), EXCLUDE)

    def test_invalid_thresholds_rejected(self):
        with self.assertRaises(ValueError):
            Policy(admit_at=0.2, review_at=0.8)


class DecideTests(unittest.TestCase):
    def test_scores_and_actions(self):
        decision = decide(
            "write an adapter for analytics", CLAIMS,
            caller=fake_caller({
                "clm_a": (0.9, 0.9),
                "clm_b": (0.8, 0.85),
                "clm_c": (0.05, 0.9),
            }, governing="clm_b"),
        )
        by_id = {e.claim_id: e for e in decision.entries}
        self.assertEqual(by_id["clm_a"].action, ADMIT)
        self.assertEqual(by_id["clm_b"].action, ADMIT)
        self.assertEqual(by_id["clm_c"].action, EXCLUDE)
        self.assertAlmostEqual(by_id["clm_a"].score, 0.81)
        self.assertEqual(decision.governing, "clm_b")

    def test_contradiction_downgrades_to_review(self):
        decision = decide(
            "write an adapter", CLAIMS,
            caller=fake_caller({
                "clm_a": (0.9, 0.9),
                "clm_b": (0.9, 0.9),
                "clm_c": (0.1, 0.9),
            }, contradiction=0.9),
        )
        self.assertEqual({e.action for e in decision.entries if e.score > 0.5}, {REVIEW})

    def test_confident_governing_claim_is_admitted_under_contradiction(self):
        decision = decide(
            "write an adapter for analytics", CLAIMS,
            caller=fake_caller({
                "clm_a": (0.83, 0.18),
                "clm_b": (0.89, 0.63),
                "clm_c": (0.1, 0.9),
            }, governing="clm_b", contradiction=0.92),
        )
        by_id = {e.claim_id: e for e in decision.entries}
        self.assertTrue(by_id["clm_b"].governing)
        self.assertEqual(by_id["clm_b"].action, ADMIT)
        self.assertEqual(decision.contradiction, 0.92)

    def test_low_confidence_governing_does_not_override(self):
        def weak(state, questions):
            answers = {"contradiction": {"type": "noul", "noul": 0.9},
                       "governing": {"type": "choice", "choice": "clm_b", "confidence": 0.5},
                       "applies::clm_a": {"type": "noul", "noul": 0.9},
                       "holds::clm_a": {"type": "noul", "noul": 0.9},
                       "applies::clm_b": {"type": "noul", "noul": 0.55},
                       "holds::clm_b": {"type": "noul", "noul": 0.55},
                       "applies::clm_c": {"type": "noul", "noul": 0.1},
                       "holds::clm_c": {"type": "noul", "noul": 0.9}}
            return {"model": "jev-test", "answers": answers}
        decision = decide("t", CLAIMS, caller=weak)
        by_id = {e.claim_id: e for e in decision.entries}
        self.assertFalse(by_id["clm_b"].governing)
        self.assertEqual(by_id["clm_b"].action, REVIEW)

    def test_budget_omits_and_reports(self):
        claims = [{"claim_id": f"clm_{i}", "text": "x" * 200} for i in range(5)]
        probs = {f"clm_{i}": (0.9, 0.9) for i in range(5)}
        decision = decide("t", claims, caller=fake_caller(probs), budget_bytes=500)
        self.assertGreater(decision.omitted, 0)
        self.assertLessEqual(decision.used_bytes, 500)
        self.assertEqual(len(decision.admitted) + decision.omitted,
                         sum(1 for e in decision.entries if e.action != EXCLUDE))

    def test_missing_answer_fails_loudly(self):
        def partial(state, questions):
            return {"model": "x", "answers": {"contradiction": {"type": "noul", "noul": 0.0},
                                              "governing": {"type": "choice", "choice": "none"}}}
        with self.assertRaises(Exception):
            decide("t", CLAIMS, caller=partial)

    def test_output_carries_no_generation_model(self):
        decision = decide("t", CLAIMS, caller=fake_caller(
            {"clm_a": (0.9, 0.9), "clm_b": (0.9, 0.9), "clm_c": (0.9, 0.9)}))
        self.assertEqual(decision.model, "jev-test")
        self.assertNotIn("generation_model", decision.to_dict())

    def test_transport_failure_raises_by_default(self):
        from chat_distiller import jev
        def boom(state, questions):
            raise jev.JevError("timeout")
        with self.assertRaises(jev.JevError):
            decide("t", CLAIMS, caller=boom)

    def test_transport_failure_fails_open_to_review(self):
        from chat_distiller import jev
        def boom(state, questions):
            raise jev.JevError("timeout")
        decision = decide("t", CLAIMS, caller=boom, on_error="review")
        self.assertTrue(decision.degraded)
        self.assertEqual(decision.model, "unavailable")
        self.assertTrue(all(e.action == REVIEW for e in decision.entries))
        self.assertFalse(any(e.action == EXCLUDE for e in decision.entries))

    def test_bad_on_error_rejected(self):
        with self.assertRaises(ValueError):
            decide("t", CLAIMS, caller=fake_caller({"clm_a": (0.9, 0.9)}), on_error="ignore")


class LogTests(unittest.TestCase):
    def test_append_and_read(self):
        decision = decide("t", CLAIMS, caller=fake_caller(
            {"clm_a": (0.9, 0.9), "clm_b": (0.9, 0.9), "clm_c": (0.1, 0.9)}))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.jsonl"
            record = log.append(path, decision, extra={"run": "test"})
            self.assertEqual(record["run"], "test")
            rows = log.read(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["model"], "jev-test")
            self.assertEqual(len(rows[0]["entries"]), 3)

    def test_read_missing_file_is_empty(self):
        self.assertEqual(log.read("/nonexistent/decisions.jsonl"), [])

    def test_bad_line_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.jsonl"
            path.write_text("not json\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                log.read(path)


if __name__ == "__main__":
    unittest.main()