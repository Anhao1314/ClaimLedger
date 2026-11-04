"""Offline tests for the frozen contracts. No network."""
import importlib.util
import json
import unittest
from pathlib import Path

from chat_distiller import jev
from jev_first import contracts

ROOT = Path(__file__).resolve().parents[1]


def load_eval_module():
    spec = importlib.util.spec_from_file_location(
        "jev_relation_eval", ROOT / "scripts" / "jev_relation_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManifestTests(unittest.TestCase):
    def test_contract_files_match_the_manifest(self):
        status = contracts.verify_manifest()
        self.assertEqual(status, {"questions.v1.json": "ok",
                                  "questions.v2.json": "ok",
                                  "questions.v3.json": "ok",
                                  "records.v1.json": "ok"})

    def test_tampered_file_is_detected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            (tmpdir / "records.v1.json").write_bytes(
                contracts.RECORDS_FILE.read_bytes() + b" ")
            for attr in ("QUESTIONS_FILE", "QUESTIONS_V2_FILE",
                         "QUESTIONS_V1_FILE"):
                path = getattr(contracts, attr)
                (tmpdir / path.name).write_bytes(path.read_bytes())
            manifest = json.loads((ROOT / "contracts" / "manifest.json").read_text())
            (tmpdir / "manifest.json").write_text(json.dumps(manifest))
            original_dir = contracts.CONTRACT_DIR
            contracts.CONTRACT_DIR = tmpdir
            try:
                with self.assertRaises(contracts.ContractError):
                    contracts.verify_manifest()
            finally:
                contracts.CONTRACT_DIR = original_dir


class QuestionContractTests(unittest.TestCase):
    def test_active_set_is_v3(self):
        self.assertEqual(contracts.questions()["version"], "v3")
        self.assertEqual(contracts.questions("v2")["version"], "v2")
        self.assertEqual(contracts.questions("v1")["version"], "v1")
        with self.assertRaises(contracts.ContractError):
            contracts.questions("v9")

    def test_carried_questions_are_verbatim(self):
        """Promotion must not drift the semantics that were already validated."""
        active = contracts.questions()["questions"]
        for version in ("v1", "v2"):
            carried = contracts.questions(version)["questions"]
            for name, entry in carried.items():
                self.assertEqual(active[name], entry, f"{version}:{name}")
        self.assertEqual(contracts.questions()["retired"],
                         contracts.questions("v1")["retired"])

    def test_edge_question_matches_the_validated_experiment(self):
        """The edges_v1 result only transfers if the wire payload is identical."""
        spec = json.loads((ROOT / "experiments" / "edges_v1"
                           / "questions.v2.json").read_text(encoding="utf-8"))
        self.assertEqual(contracts.edge_question(),
                         {k: spec["questions"]["edge"][k]
                          for k in ("type", "instructions", "criteria")})

    def test_replacement_question_matches_the_validated_experiment(self):
        spec = json.loads((ROOT / "experiments" / "supersedes_003"
                           / "questions.json").read_text(encoding="utf-8"))
        self.assertEqual(contracts.replacement_question(),
                         {k: spec["questions"]["replacement"][k]
                          for k in ("type", "instructions", "criteria")})

    def test_direction_question_matches_the_validated_experiment(self):
        spec = json.loads((ROOT / "experiments" / "supersedes_001"
                           / "questions.json").read_text(encoding="utf-8"))
        self.assertEqual(contracts.direction_question(),
                         {k: spec["questions"]["direction"][k]
                          for k in ("type", "instructions", "criteria")})

    def test_cascade_questions_are_validated(self):
        self.assertEqual(contracts.question("replacement")
                         ["validation"]["status"], "VALIDATED")
        self.assertEqual(contracts.question("direction")
                         ["validation"]["status"], "VALIDATED")

    def test_edge_question_is_validated_with_four_criteria(self):
        entry = contracts.question("edge")
        self.assertEqual(entry["validation"]["status"], "VALIDATED")
        self.assertEqual(set(entry["criteria"]),
                         {"supports", "contradicts", "supersedes", "unrelated"})

    def test_relation_question_matches_the_validated_experiment(self):
        """The 30-pair result only transfers if the question is byte-identical."""
        eval_module = load_eval_module()
        self.assertEqual(contracts.relation_question(), eval_module.QUESTION)

    def test_relation_question_is_validated(self):
        entry = contracts.question("relation")
        self.assertEqual(entry["validation"]["status"], "VALIDATED")

    def test_retired_questions_are_not_silent(self):
        retired = {item["name"] for item in contracts.questions()["retired"]}
        self.assertIn("applies", retired)
        self.assertIn("holds", retired)
        for name in retired:
            self.assertNotIn(name, contracts.questions()["questions"])

    def test_unknown_question_rejected(self):
        with self.assertRaises(contracts.ContractError):
            contracts.question("sentiment")


class RecordContractTests(unittest.TestCase):
    def test_make_record_is_deterministic_and_valid(self):
        record = contracts.make_record("Use PostgreSQL.", "agent", "2026-11-02T00:00:00Z")
        contracts.validate_record(record)
        again = contracts.make_record("Use PostgreSQL.", "agent", "2026-11-02T00:00:00Z")
        self.assertEqual(record["record_id"], again["record_id"])

    def test_different_scope_changes_identity(self):
        a = contracts.make_record("x", "agent", "2026-11-02T00:00:00Z")
        b = contracts.make_record("x", "agent", "2026-11-02T00:00:00Z", scope="analytics")
        self.assertNotEqual(a["record_id"], b["record_id"])

    def test_stored_status_is_rejected(self):
        record = contracts.make_record("x", "agent", "2026-11-02T00:00:00Z")
        record["status"] = "superseded"
        with self.assertRaises(contracts.ContractError):
            contracts.validate_record(record)

    def test_tampered_text_breaks_identity(self):
        record = contracts.make_record("x", "agent", "2026-11-02T00:00:00Z")
        record["text"] = "y"
        with self.assertRaises(contracts.ContractError):
            contracts.validate_record(record)

    def test_bad_prev_hash_rejected(self):
        record = contracts.make_record("x", "agent", "2026-11-02T00:00:00Z", prev_hash="zz")
        with self.assertRaises(contracts.ContractError):
            contracts.validate_record(record)

    def test_chain_links(self):
        first = contracts.make_record("a", "agent", "2026-11-02T00:00:00Z")
        import hashlib
        link = hashlib.sha256(json.dumps(
            {k: v for k, v in first.items()}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        second = contracts.make_record("b", "agent", "2026-11-02T00:00:01Z", prev_hash=link)
        contracts.validate_record(second)
        self.assertEqual(second["prev_hash"], link)


if __name__ == "__main__":
    unittest.main()