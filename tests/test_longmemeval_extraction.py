"""Extraction contract, resume, failure stop, and chronological supersession."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "lme_extraction", ROOT / "benchmarks/longmemeval/extraction.py")
extraction = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extraction)


def record(qid="q1", sessions=2):
    texts = [
        [{"role": "user", "content": "I use SQLite for all storage."}],
        [{"role": "user", "content": "I use PostgreSQL for all production storage."}],
    ]
    return {
        "question_id": qid,
        "question_type": "knowledge-update",
        "answer_session_ids": ["s1"],
        "haystack_session_ids": ["s%d" % i for i in range(sessions)],
        "haystack_dates": ["2024-01-%02d" % (i + 1) for i in range(sessions)],
        "haystack_sessions": (texts * sessions)[:sessions],
    }


class CleanOutputTests(unittest.TestCase):
    def test_valid_output_keeps_claims_and_skipped_turns(self):
        value = extraction.clean_output({
            "claims": [{
                "text": "The user uses SQLite.",
                "quote": "I use SQLite for all storage.",
                "topic": "technology",
                "tags": ["Database", "storage"],
                "turn_indices": [0],
            }],
            "skipped_turns": [],
        }, 2)
        self.assertEqual(len(value["claims"]), 1)
        self.assertEqual(value["claims"][0]["tags"], ["database", "storage"])
        self.assertEqual(value["coverage"]["claimed_turns"], 1)

    def test_invalid_claim_fields_are_dropped_or_repaired(self):
        value = extraction.clean_output({
            "claims": [
                {"text": "x" * 1001, "quote": "q", "topic": "personal", "turn_indices": [0]},
                {"text": "valid", "quote": "q" * 301, "topic": "not-a-topic",
                 "turn_indices": [99]},
            ],
            "skipped_turns": [1],
        }, 2)
        self.assertEqual(len(value["claims"]), 1)
        self.assertEqual(value["claims"][0]["topic"], "other")
        self.assertEqual(len(value["claims"][0]["quote"]), 300)
        self.assertEqual(value["claims"][0]["turn_indices"], [])
        self.assertTrue(any("exceeds" in problem for problem in value["problems"]))

    def test_parse_output_accepts_fenced_json(self):
        raw = extraction.parse_output('```json\n{"claims": [], "skipped_turns": []}\n```')
        self.assertEqual(raw["claims"], [])


class MockClient:
    name = "mock"
    model = "mock"
    is_mock = True

    def chat(self, messages, **_):
        return json.dumps({"claims": [], "skipped_turns": [0]}), {}, 0.0


class FailingClient(MockClient):
    def chat(self, messages, **_):
        raise extraction.FatalApiError("simulated endpoint failure")


class ResumeAndStopTests(unittest.TestCase):
    def test_resume_skips_existing_session_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = record(sessions=2)
            runner = extraction.ExtractionRunner(
                [rec], [rec["question_id"]], Path(tmp), MockClient(),
                prompt_version="test-v1", split="dev")
            first = runner.run()
            self.assertEqual(first["sessions_ok"], 2)
            self.assertEqual(first["calls"], 2)
            second = extraction.ExtractionRunner(
                [rec], [rec["question_id"]], Path(tmp), MockClient(),
                prompt_version="test-v1", split="dev")
            result = second.run()
            self.assertEqual(result["sessions_skipped"], 2)
            self.assertEqual(result["calls"], 2)  # cumulative across resumes

    def test_ten_consecutive_failures_write_stop_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = record(sessions=12)
            runner = extraction.ExtractionRunner(
                [rec], [rec["question_id"]], Path(tmp), FailingClient(),
                prompt_version="test-v1", split="dev")
            result = runner.run()
            self.assertEqual(result["sessions_failed"], 10)
            self.assertEqual(result["stop_reason"], "consecutive_failures")
            self.assertTrue((Path(tmp) / "STOP").is_file())
            with self.assertRaisesRegex(extraction.ExtractionError, "STOP"):
                extraction.ExtractionRunner(
                    [rec], [rec["question_id"]], Path(tmp), MockClient(),
                    prompt_version="test-v1", split="dev").run()


class IngestTests(unittest.TestCase):
    def test_ingest_supersedes_lexical_conflict_in_time_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = record(sessions=2)
            outputs = [
                {"session_id": "s0", "session_date": "2024-01-01", "claims": [{
                    "text": "Use SQLite for all storage", "quote": "I use SQLite",
                    "topic": "technology", "tags": [], "turn_indices": [0]}]},
                {"session_id": "s1", "session_date": "2024-01-02", "claims": [{
                    "text": "Use PostgreSQL for all production storage",
                    "quote": "I use PostgreSQL", "topic": "technology",
                    "tags": [], "turn_indices": [0]}]},
            ]
            meta = extraction.ingest_question(
                rec, outputs, Path(tmp) / "q1.jsonl", "test-v1")
            self.assertEqual(meta["recorded"], 2)
            self.assertEqual(meta["superseded_claims"], 1)
            rows = extraction.ClaimStore(Path(tmp) / "q1.jsonl").claims(status="all")
            by_text = {row["text"]: row for row in rows}
            old = by_text["Use SQLite for all storage"]
            new = by_text["Use PostgreSQL for all production storage"]
            self.assertEqual(old["status"], "已过期")
            self.assertEqual(new["status"], "现行")
            self.assertEqual(old["superseded_by"], new["claim_id"])


if __name__ == "__main__":
    unittest.main()
