"""Offline tests for the Jev-first core v2: two-stage judgment, localization,
record chain, cache, sealed log."""
import json
import tempfile
import unittest
from pathlib import Path

from chat_distiller import jev
from jev_first import Policy, contracts, judge, log
from jev_first.cache import Cache
from jev_first.judge import Judgment
from jev_first.policy import ADMIT, EXCLUDE, REVIEW
from jev_first.records import RecordStore, body_hash, find_near_duplicate

TEXTS = {
    "clm_a": "All storage must use PostgreSQL.",
    "clm_b": "PostgreSQL is banned for the analytics service.",
    "clm_c": "The release train leaves on Friday.",
}


def make_records(texts):
    return [contracts.make_record(text, "agent",
                                  f"2026-11-02T00:00:0{i}Z")
            for i, text in enumerate(texts)]


def fake_core(admit, relations, governing=("none", 0.0), calls=None,
              fail_pairs=(), edges=None, fail_edges=(),
              replacement=None, fail_replacement=(),
              direction=None, fail_direction=()):
    """admit: {record_id: (choice, p_admit)}
    relations: {(text_a, text_b): label}
    edges: {(text_a, text_b): (label, p)} — defaults to a confident unrelated,
    which proposes nothing and keeps pre-edge tests unchanged.
    replacement: {(text_a, text_b): p_yes} — defaults to 0.0 (conflict stands).
    direction: {(text_a, text_b): "A"|"B"} — defaults to "A" (src is newer)."""
    def call(state, questions):
        if calls is not None:
            calls.append(state)
        if "replacement" in questions:
            a = state.split("Record A (src): ", 1)[1].split("\n", 1)[0]
            b = state.split("Record B (dst): ", 1)[1].strip()
            if (a, b) in fail_replacement or (b, a) in fail_replacement:
                raise jev.JevError("transport failure")
            p_yes = (replacement or {}).get((a, b), (replacement or {}).get((b, a), 0.0))
            p_no = round(1.0 - p_yes, 4)
            return {"model": "jev-test",
                    "answers": {"replacement": {
                        "type": "choice",
                        "choice": "yes" if p_yes >= 0.5 else "no",
                        "confidence": max(p_yes, p_no),
                        "probabilities": {"yes": p_yes, "no": p_no}}},
                    "usage": {}}
        if "direction" in questions:
            a = state.split("Record A (src): ", 1)[1].split("\n", 1)[0]
            b = state.split("Record B (dst): ", 1)[1].strip()
            if (a, b) in fail_direction or (b, a) in fail_direction:
                raise jev.JevError("transport failure")
            newer = (direction or {}).get((a, b), (direction or {}).get((b, a), "A"))
            return {"model": "jev-test",
                    "answers": {"direction": {
                        "type": "choice", "choice": newer, "confidence": 0.9,
                        "probabilities": {"A": 0.9 if newer == "A" else 0.1,
                                          "B": 0.1 if newer == "A" else 0.9}}},
                    "usage": {}}
        if "edge" in questions:
            a = state.split("Record A (src): ", 1)[1].split("\n", 1)[0]
            b = state.split("Record B (dst): ", 1)[1].strip()
            if (a, b) in fail_edges or (b, a) in fail_edges:
                raise jev.JevError("transport failure")
            label, p = ((edges or {}).get((a, b))
                        or (edges or {}).get((b, a)) or ("unrelated", 0.95))
            others = round((1.0 - p) / 3, 4)
            probabilities = {"supports": others, "contradicts": others,
                             "supersedes": others, "unrelated": others}
            probabilities[label] = p
            return {"model": "jev-test",
                    "answers": {"edge": {
                        "type": "choice", "choice": label, "confidence": p,
                        "probabilities": probabilities}},
                    "usage": {}}
        if "relation" in questions:
            a = state.split("Statement A: ", 1)[1].split("\n", 1)[0]
            b = state.split("Statement B: ", 1)[1].strip()
            if (a, b) in fail_pairs or (b, a) in fail_pairs:
                raise jev.JevError("transport failure")
            label = relations.get((a, b)) or relations.get((b, a)) or "unrelated"
            probabilities = {l: 0.05 for l in
                             ("contradiction", "complementary", "unrelated")}
            probabilities[label] = 0.9
            return {"model": "jev-test",
                    "answers": {"relation": {
                        "type": "choice", "choice": label, "confidence": 0.9,
                        "probabilities": probabilities}},
                    "usage": {}}
        if "admit" in questions:
            rid = state.split("CLAIM:\n- ", 1)[1].split(":", 1)[0]
            choice, p_admit = admit[rid]
            probabilities = {"admit": 0.05, "review": 0.05, "exclude": 0.05}
            probabilities[choice] = p_admit if choice != "exclude" else 0.8
            return {"model": "jev-test",
                    "answers": {"admit": {"type": "choice", "choice": choice,
                                          "confidence": 0.9,
                                          "probabilities": probabilities}},
                    "usage": {}}
        if "governing" in questions:
            return {"model": "jev-test",
                    "answers": {"governing": {"type": "choice",
                                              "choice": governing[0],
                                              "confidence": governing[1]}},
                    "usage": {}}
        raise AssertionError(f"unexpected questions: {sorted(questions)}")
    return call


class PolicyTests(unittest.TestCase):
    def test_argmax_passthrough(self):
        policy = Policy()
        self.assertEqual(policy.action(ADMIT), ADMIT)
        self.assertEqual(policy.action(REVIEW), REVIEW)
        self.assertEqual(policy.action(EXCLUDE), EXCLUDE)

    def test_governing_promotes_review_only(self):
        policy = Policy()
        self.assertEqual(policy.action(REVIEW, governing=True), ADMIT)
        self.assertEqual(policy.action(ADMIT, governing=True), ADMIT)
        self.assertEqual(policy.action(EXCLUDE, governing=True), EXCLUDE)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            Policy().action("maybe")
        with self.assertRaises(ValueError):
            Policy(governing_at=7)


class RecordStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = RecordStore(Path(self.tmp.name) / "records.jsonl")

    def test_chain_grows_and_verifies(self):
        first = self.store.append("Use PostgreSQL.", "agent")
        second = self.store.append("Retries at most 3.", "agent")
        self.assertEqual(second["prev_hash"], body_hash(first))
        self.assertEqual(len(self.store.load()), 2)

    def test_empty_store(self):
        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.store.last_hash(), "0" * 64)

    def test_duplicate_content_is_rejected(self):
        self.store.append("Use PostgreSQL.", "agent")
        # Content-addressed identity: an exact repeat is refused at the write,
        # not deferred to a load-time failure.
        with self.assertRaises(contracts.ContractError):
            self.store.append("Use PostgreSQL.", "agent")
        self.assertEqual(len(self.store.load()), 1)

    def test_tampering_breaks_the_chain(self):
        self.store.append("Use PostgreSQL.", "agent")
        self.store.append("Retries at most 3.", "agent")
        rows = self.store.path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(rows[1])
        tampered["text"] = "Retries at most 300."
        rows[1] = json.dumps(tampered, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        self.store.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaises(contracts.ContractError):
            self.store.load()


class NearDuplicateTests(unittest.TestCase):
    """Two agents describe the same decision differently; the write edge should
    return the existing record, not grow a paraphrase pile."""

    A = ("In the README, the delta=0.2 margin threshold must consistently be "
         "described as a safety margin, not a tuned optimum.")
    B = ("The margin threshold delta=0.2 is a safety margin, not a tuned "
         "optimum; the ablation cannot distinguish 0.0 to 0.2.")

    def test_paraphrase_returns_existing_record(self):
        records = [{"record_id": "rec_a", "text": self.A, "scope": None}]
        found = find_near_duplicate(records, self.B)
        self.assertIsNotNone(found)
        record, similarity = found
        self.assertEqual(record["record_id"], "rec_a")
        self.assertGreaterEqual(similarity, 0.65)

    def test_paraphrase_with_negation_swap_is_found(self):
        """Regression: 'not' vs 'never' and a past-tense verb must not hide
        the same decision."""
        records = [{"record_id": "rec_a", "text": self.A, "scope": None}]
        found = find_near_duplicate(
            records,
            "Always describe the delta=0.2 margin threshold as a safety "
            "margin, never as a tuned optimum.")
        self.assertIsNotNone(found)
        self.assertEqual(found[0]["record_id"], "rec_a")

    def test_mixed_language_record_matches_english_paraphrase(self):
        records = [{"record_id": "rec_a", "text": self.A, "scope": None}]
        found = find_near_duplicate(
            records,
            "README 中 delta=0.2 的 margin 阈值必须始终表述为 safety margin，"
            "而不是 tuned optimum。")
        self.assertIsNotNone(found)
        self.assertEqual(found[0]["record_id"], "rec_a")

    def test_value_twin_conflicts_are_not_merged(self):
        """A2A finding, fixed: a containment-similar pair differing only in a
        content value is two conflicting decisions — the guard must let both
        enter memory or the relation stage never sees the conflict."""
        records = make_records(["Deployments must happen only on Tuesdays."])
        self.assertIsNone(find_near_duplicate(
            records, "Deployments must happen only on Fridays."))
        # identical text is still a duplicate — escape requires a real diff
        self.assertIsNotNone(find_near_duplicate(
            records, "Deployments must happen only on Tuesdays."))

    def test_negation_is_not_merged(self):
        records = [{"record_id": "rec_a",
                    "text": "All new services must emit structured logs.",
                    "scope": None}]
        self.assertIsNone(find_near_duplicate(
            records, "All new services must not emit structured logs."))

    def test_distinct_decisions_are_not_merged(self):
        records = [{"record_id": "rec_a",
                    "text": "All new services must emit structured logs.",
                    "scope": None}]
        self.assertIsNone(find_near_duplicate(
            records, "All new services must use PostgreSQL."))

    def test_short_texts_are_skipped(self):
        records = [{"record_id": "rec_a", "text": "Use PostgreSQL.",
                    "scope": None}]
        self.assertIsNone(find_near_duplicate(records, "Use PostgreSQL only."))

    def test_scope_must_match(self):
        records = [{"record_id": "rec_a", "text": self.A, "scope": "analytics"}]
        self.assertIsNone(find_near_duplicate(records, self.B, scope="billing"))
        self.assertIsNotNone(find_near_duplicate(records, self.B, scope="analytics"))


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.records = make_records([TEXTS["clm_a"], TEXTS["clm_b"], TEXTS["clm_c"]])
        self.a, self.b, self.c = (r["record_id"] for r in self.records)
        self.admit_all = {rid: (ADMIT, 0.9) for rid in (self.a, self.b, self.c)}

    def test_conflict_is_localized_not_global(self):
        decision = judge(
            "write a storage adapter for analytics", self.records,
            model="jev-test", caller=fake_core(
                self.admit_all,
                {(TEXTS["clm_a"], TEXTS["clm_b"]): "contradiction",
                 (TEXTS["clm_a"], TEXTS["clm_c"]): "unrelated",
                 (TEXTS["clm_b"], TEXTS["clm_c"]): "unrelated"}))
        by_id = {e.record_id: e for e in decision.entries}
        self.assertEqual(by_id[self.a].action, REVIEW)
        self.assertTrue(by_id[self.a].conflicted)
        self.assertEqual(by_id[self.b].action, REVIEW)
        self.assertTrue(by_id[self.b].conflicted)
        self.assertEqual(by_id[self.c].action, ADMIT)
        self.assertFalse(by_id[self.c].conflicted)
        self.assertEqual(decision.conflicts, [[self.a, self.b]])
        self.assertEqual(decision.pair_checks, 3)

    def test_no_conflict_all_admitted(self):
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {}))
        self.assertEqual({e.action for e in decision.entries}, {ADMIT})
        self.assertEqual(decision.conflicts, [])

    def test_flow_uses_pair_requests_not_a_global_signal(self):
        calls = []
        judge("t", self.records, model="jev-test",
              caller=fake_core(self.admit_all, {}, calls=calls))
        # 3 per-record admits + 3 relation pairs + 3 edge pairs + 1 governing
        self.assertEqual(len(calls), 10)
        self.assertNotIn("Two or more of the listed claims", "".join(calls))

    def test_pair_failure_fails_open_to_review(self):
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             fail_pairs={(TEXTS["clm_a"], TEXTS["clm_b"])}),
            on_error="review")
        by_id = {e.record_id: e for e in decision.entries}
        self.assertEqual(by_id[self.a].action, REVIEW)
        self.assertEqual(by_id[self.b].action, REVIEW)
        self.assertFalse(by_id[self.a].conflicted)
        self.assertTrue(decision.degraded)

    def test_pair_failure_raises_when_asked(self):
        with self.assertRaises(jev.JevError):
            judge("t", self.records, model="jev-test",
                  caller=fake_core(self.admit_all, {},
                                   fail_pairs={(TEXTS["clm_a"], TEXTS["clm_b"])}),
                  on_error="raise")

    # ---- stage 2.5: the edge question --------------------------------------

    def test_edge_proposed_at_high_confidence_without_touching_actions(self):
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("supports", 0.9)}))
        self.assertEqual(len(decision.edges), 3)  # one decision per pair
        proposed = [e for e in decision.edges if e.action == "proposed"]
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0].label, "supports")
        self.assertEqual(proposed[0].src, self.a)
        self.assertEqual(proposed[0].dst, self.b)
        self.assertGreaterEqual(proposed[0].p, 0.80)
        # The edge plane never changes record actions.
        self.assertEqual({e.action for e in decision.entries}, {ADMIT})
        self.assertFalse(decision.degraded)

    def test_edge_review_below_threshold(self):
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("contradicts", 0.6)}))
        reviewed = [e for e in decision.edges if e.action == "review"]
        self.assertEqual(len(reviewed), 1)
        self.assertEqual(reviewed[0].label, "contradicts")

    def test_edge_none_below_half_and_for_unrelated(self):
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("supports", 0.4),
                                    (TEXTS["clm_a"], TEXTS["clm_c"]): ("unrelated", 0.95)}))
        actions = {(e.src, e.dst): e.action for e in decision.edges}
        self.assertEqual(actions[(self.a, self.b)], "none")
        self.assertEqual(actions[(self.a, self.c)], "none")
        self.assertEqual(actions[(self.b, self.c)], "none")  # default unrelated

    def test_edge_failure_marks_degraded_and_proposes_nothing(self):
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             fail_edges={(TEXTS["clm_a"], TEXTS["clm_b"])}),
            on_error="review")
        self.assertTrue(decision.degraded)
        self.assertEqual([e for e in decision.edges
                          if (e.src, e.dst) == (self.a, self.b)], [])

    def test_edges_survive_the_log_round_trip(self):
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("supersedes", 0.95)}))
        restored = Judgment.from_dict(decision.to_dict())
        self.assertEqual(restored.edges, list(decision.edges))
        self.assertEqual(restored.edges[0].label, "supersedes")
        # the direction pass orients the supersedes edge (src→dst = src newer)
        proposed = [e for e in restored.edges if e.action == "proposed"]
        self.assertEqual(proposed[0].direction, "src→dst")

    # ---- stage 2.5 cascade: conflict vs succession -------------------------

    def test_cascade_recovers_a_stated_replacement(self):
        """contradicts argmax + confident replacement -> supersedes proposal."""
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("contradicts", 0.9)},
                             replacement={(TEXTS["clm_a"], TEXTS["clm_b"]): 0.95}))
        hit = [e for e in decision.edges
               if (e.src, e.dst) == (self.a, self.b)][0]
        self.assertEqual(hit.label, "supersedes")
        self.assertEqual(hit.action, "proposed")
        self.assertEqual(hit.via, "cascade")
        self.assertEqual(hit.p, 0.95)
        self.assertEqual(hit.direction, "src→dst")
        self.assertFalse(decision.degraded)

    def test_cascade_review_band_holds_the_pair(self):
        """0.50-0.79 p_yes: not confident enough to repair, not a clean conflict."""
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("contradicts", 0.9)},
                             replacement={(TEXTS["clm_a"], TEXTS["clm_b"]): 0.63}))
        hit = [e for e in decision.edges
               if (e.src, e.dst) == (self.a, self.b)][0]
        self.assertEqual(hit.label, "contradicts")
        self.assertEqual(hit.action, "review")
        self.assertEqual(hit.via, "cascade-review")

    def test_cascade_conflict_stands_below_half(self):
        """p_yes < 0.50: the conflict stands with the single-question banding."""
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("contradicts", 0.9)},
                             replacement={(TEXTS["clm_a"], TEXTS["clm_b"]): 0.1}))
        hit = [e for e in decision.edges
               if (e.src, e.dst) == (self.a, self.b)][0]
        self.assertEqual(hit.label, "contradicts")
        self.assertEqual(hit.action, "proposed")
        self.assertEqual(hit.via, "single-question")

    def test_replacement_failure_holds_the_conflicted_pair(self):
        """A suspected conflict that might be a replacement must become neither
        edge when the disambiguation does not run cleanly."""
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("contradicts", 0.9)},
                             fail_replacement={(TEXTS["clm_a"], TEXTS["clm_b"])}),
            on_error="review")
        hit = [e for e in decision.edges
               if (e.src, e.dst) == (self.a, self.b)][0]
        self.assertEqual(hit.label, "contradicts")
        self.assertEqual(hit.action, "review")
        self.assertEqual(hit.via, "cascade")
        self.assertTrue(decision.degraded)

    def test_direction_failure_holds_a_supersedes_proposal(self):
        """A directed edge without a direction is malformed: hold, don't emit."""
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("supersedes", 0.95)},
                             fail_direction={(TEXTS["clm_a"], TEXTS["clm_b"])}),
            on_error="review")
        hit = [e for e in decision.edges
               if (e.src, e.dst) == (self.a, self.b)][0]
        self.assertEqual(hit.label, "supersedes")
        self.assertEqual(hit.action, "review")
        self.assertIsNone(hit.direction)
        self.assertTrue(decision.degraded)

    def test_direction_b_side_makes_dst_the_newer(self):
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all, {},
                             edges={(TEXTS["clm_a"], TEXTS["clm_b"]): ("supersedes", 0.95)},
                             direction={(TEXTS["clm_a"], TEXTS["clm_b"]): "B"}))
        hit = [e for e in decision.edges
               if (e.src, e.dst) == (self.a, self.b)][0]
        self.assertEqual(hit.direction, "dst→src")

    def test_governing_promotes_a_clean_review(self):
        admit = {self.a: (ADMIT, 0.9), self.b: (REVIEW, 0.2),
                 self.c: (ADMIT, 0.9)}
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(admit, {}, governing=(self.c, 0.95)))
        by_id = {e.record_id: e for e in decision.entries}
        self.assertEqual(by_id[self.c].action, ADMIT)
        self.assertTrue(by_id[self.c].governing)

    def test_conflicted_record_is_never_promoted(self):
        decision = judge(
            "t", self.records, model="jev-test",
            caller=fake_core(self.admit_all,
                             {(TEXTS["clm_a"], TEXTS["clm_b"]): "contradiction",
                              (TEXTS["clm_a"], TEXTS["clm_c"]): "unrelated",
                              (TEXTS["clm_b"], TEXTS["clm_c"]): "unrelated"},
                             governing=(self.a, 0.99)))
        by_id = {e.record_id: e for e in decision.entries}
        self.assertEqual(by_id[self.a].action, REVIEW)
        self.assertTrue(by_id[self.a].conflicted)
        self.assertTrue(by_id[self.a].governing)

    def test_thin_margin_admit_forces_review(self):
        """argmax says admit, but the top-two gap is inside the noise band
        measured on the borderline pair (borderline-stability.json)."""
        def caller(state, questions):
            if "governing" in questions:
                return {"model": "jev-test",
                        "answers": {"governing": {"type": "choice",
                                                  "choice": "none",
                                                  "confidence": 0.9}}, "usage": {}}
            if "edge" in questions:
                # delegate to the default fake: a confident unrelated edge
                return fake_core({}, {})(state, questions)
            if "relation" in questions:
                return {"model": "jev-test",
                        "answers": {"relation": {
                            "type": "choice", "choice": "complementary",
                            "confidence": 0.9,
                            "probabilities": {"complementary": 0.9,
                                              "contradiction": 0.05,
                                              "unrelated": 0.05}}},
                        "usage": {}}
            rid = state.split("CLAIM:\n- ", 1)[1].split(":", 1)[0]
            return {"model": "jev-test",
                    "answers": {"admit": {"type": "choice", "choice": ADMIT,
                                          "confidence": 0.5,
                                          "probabilities": {"admit": 0.45,
                                                            "review": 0.40,
                                                            "exclude": 0.15}}},
                    "usage": {}}
        decision = judge("t", self.records, model="jev-test", caller=caller)
        self.assertEqual({e.action for e in decision.entries}, {REVIEW})
        self.assertTrue(all(e.low_margin for e in decision.entries))

    def test_thin_margin_pair_is_uncertain_not_conflict(self):
        def caller(state, questions):
            if "edge" in questions:
                return fake_core({}, {})(state, questions)
            if "relation" in questions:
                return {"model": "jev-test",
                        "answers": {"relation": {
                            "type": "choice", "choice": "contradiction",
                            "confidence": 0.55,
                            "probabilities": {"contradiction": 0.45,
                                              "complementary": 0.40,
                                              "unrelated": 0.15}}},
                        "usage": {}}
            if "governing" in questions:
                return {"model": "jev-test",
                        "answers": {"governing": {"type": "choice",
                                                  "choice": "none",
                                                  "confidence": 0.9}}, "usage": {}}
            rid = state.split("CLAIM:\n- ", 1)[1].split(":", 1)[0]
            return {"model": "jev-test",
                    "answers": {"admit": {"type": "choice", "choice": ADMIT,
                                          "confidence": 0.9,
                                          "probabilities": {"admit": 0.9,
                                                            "review": 0.05,
                                                            "exclude": 0.05}}},
                    "usage": {}}
        decision = judge("t", self.records, model="jev-test", caller=caller)
        self.assertEqual(decision.conflicts, [])
        self.assertEqual(len(decision.uncertain_pairs), 3)
        self.assertEqual({e.action for e in decision.entries}, {REVIEW})
        self.assertFalse(any(e.conflicted for e in decision.entries))
        self.assertTrue(all(e.low_margin for e in decision.entries))

    def test_excluded_records_are_paired_with_admitted(self):
        calls = []
        admit = {self.a: (ADMIT, 0.9), self.b: (ADMIT, 0.9),
                 self.c: (EXCLUDE, 0.1)}
        judge("t", self.records, model="jev-test",
              caller=fake_core(admit, {(TEXTS["clm_a"], TEXTS["clm_b"]): "unrelated"},
                               calls=calls))
        # 3 admits + 3 relation pairs + 3 edge pairs + governing
        self.assertEqual(len(calls), 3 + 3 + 3 + 1)

    def test_conflict_is_found_when_one_side_would_be_excluded(self):
        """Stage 1 excludes relevance, not truth: an excluded record can still
        contradict an admitted one, and that conflict must surface."""
        records = make_records([
            "All new services must emit structured logs.",
            "New services must not emit structured logs.",
        ])
        decision = judge(
            "t", records, model="jev-test",
            caller=fake_core(
                {records[0]["record_id"]: (ADMIT, 0.9),
                 records[1]["record_id"]: (EXCLUDE, 0.1)},
                {(records[0]["text"], records[1]["text"]): "contradiction"}))
        self.assertEqual(decision.conflicts,
                         [[records[0]["record_id"], records[1]["record_id"]]])
        self.assertTrue(all(e.action == REVIEW for e in decision.entries))
        self.assertTrue(all(e.conflicted for e in decision.entries))

    def test_more_than_six_records_rejected(self):
        records = make_records([f"r{i}" for i in range(7)])
        with self.assertRaises(ValueError):
            judge("t", records, model="jev-test",
                  caller=fake_core({r["record_id"]: (ADMIT, 0.9)
                                    for r in records}, {}))

    def test_degraded_decisions_are_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Cache(Path(tmp) / "cache.jsonl")
            calls = []
            failing = fake_core(self.admit_all, {},
                                fail_pairs={(TEXTS["clm_a"], TEXTS["clm_b"])},
                                calls=calls)
            first = judge("t", self.records, model="jev-test",
                          caller=failing, cache=cache, on_error="review")
            self.assertTrue(first.degraded)
            second = judge("t", self.records, model="jev-test",
                           caller=failing, cache=cache, on_error="review")
            self.assertFalse(second.cached)
            self.assertGreater(len(calls), 0)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.records = make_records([TEXTS["clm_a"], TEXTS["clm_b"], TEXTS["clm_c"]])
        self.a, self.b, self.c = (r["record_id"] for r in self.records)

    def test_second_identical_call_is_served_from_cache(self):
        calls = []
        cache = Cache(Path(self.tmp.name) / "cache.jsonl")
        caller = fake_core({rid: (ADMIT, 0.9)
                            for rid in (self.a, self.b, self.c)},
                           {(TEXTS["clm_a"], TEXTS["clm_b"]): "unrelated",
                            (TEXTS["clm_a"], TEXTS["clm_c"]): "unrelated",
                            (TEXTS["clm_b"], TEXTS["clm_c"]): "unrelated"},
                           calls=calls)
        first = judge("write an adapter", self.records, model="jev-test",
                      caller=caller, cache=cache)
        fresh_calls = len(calls)
        second = judge("write an adapter", self.records, model="jev-test",
                       caller=caller, cache=cache)
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(len(calls), fresh_calls)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_different_task_misses(self):
        cache = Cache(Path(self.tmp.name) / "cache.jsonl")
        caller = fake_core({rid: (ADMIT, 0.9)
                            for rid in (self.a, self.b, self.c)}, {})
        first = judge("task one", self.records, model="jev-test",
                      caller=caller, cache=cache)
        second = judge("task two", self.records, model="jev-test",
                       caller=caller, cache=cache)
        self.assertFalse(first.cached)
        self.assertFalse(second.cached)


class LogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "judgments.jsonl"
        self.records = make_records([TEXTS["clm_a"], TEXTS["clm_b"], TEXTS["clm_c"]])

    def test_chain_seals_and_verifies(self):
        for task in ("t1", "t2"):
            judgment = judge(task, self.records, model="jev-test",
                             caller=fake_core({r["record_id"]: (ADMIT, 0.9)
                                               for r in self.records}, {}))
            log.append_judgment(self.path, judgment.to_dict())
        rows = log.read(self.path)
        self.assertEqual(rows[0]["prev_hash"], "0" * 64)
        self.assertEqual(rows[1]["prev_hash"], rows[0]["judgment_hash"])
        self.assertEqual(log.verify(self.path), 2)

    def test_tampering_is_detected(self):
        judgment = judge("t", self.records, model="jev-test",
                         caller=fake_core({r["record_id"]: (ADMIT, 0.9)
                                           for r in self.records}, {}))
        log.append_judgment(self.path, judgment.to_dict())
        rows = self.path.read_text(encoding="utf-8").splitlines()
        row = json.loads(rows[0])
        row["task"] = "tampered"
        rows[0] = json.dumps(row, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        self.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            log.verify(self.path)

    def test_empty_log_verifies_to_zero(self):
        self.assertEqual(log.verify(self.path), 0)


if __name__ == "__main__":
    unittest.main()