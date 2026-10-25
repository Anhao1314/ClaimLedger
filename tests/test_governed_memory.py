"""Governed memory Phase A: bitemporal claims, dependency backtracking, dispute closure."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chat_distiller import ClaimStore, ClaimStoreError
from chat_distiller.claims import find_unmotivated, status_at


def moment(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def iso(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class GovernedMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_path = Path(self.tmp.name) / "claims.jsonl"
        self.store = ClaimStore(self.store_path)

    def write_raw(self, *claims):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(
            "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in claims), encoding="utf-8")

    @staticmethod
    def raw_claim(claim_id, text, *, status="现行", created_at, updated_at=None,
                  superseded_by=None, **extra):
        claim = {"claim_id": claim_id, "text": text, "status": status, "topic": "database",
                 "tags": [], "created_at": created_at,
                 "updated_at": updated_at or created_at,
                 "superseded_by": superseded_by, "source": None, "quote": None,
                 "session_hint": None}
        claim.update(extra)
        return claim

    def brief_ids(self, packet, section):
        return [entry["claim_id"] for entry in packet.get(section, [])]

    # ---------------------------------------------------------------- bitemporal

    def test_point_in_time_brief_reconstructs_supersession(self):
        self.write_raw(
            self.raw_claim("clm_a000000000000001", "数据库统一使用 SQLite",
                           created_at="2026-01-01T00:00:00Z",
                           status="已过期", updated_at="2026-02-01T00:00:00Z",
                           superseded_by="clm_b000000000000002"),
            self.raw_claim("clm_b000000000000002", "数据库统一使用 PostgreSQL",
                           created_at="2026-02-01T00:00:00Z"))
        january = self.store.brief(at="2026-01-15T00:00:00Z")
        self.assertEqual(january["at"], "2026-01-15T00:00:00Z")
        self.assertEqual(january["counts"]["current"], 1)
        self.assertEqual(self.brief_ids(january, "recently_superseded"), [])
        march = self.store.brief(at="2026-03-01T00:00:00Z")
        self.assertEqual(march["counts"]["current"], 1)
        self.assertEqual(march["counts"]["superseded"], 1)
        self.assertIn("clm_b000000000000002",
                      [c["claim_id"] for b in march["topics"] for c in b["claims"]])
        self.assertEqual(self.brief_ids(march, "recently_superseded"),
                         ["clm_a000000000000001"])

    def test_scheduled_decision_is_not_current_until_valid_from(self):
        self.write_raw(self.raw_claim(
            "clm_c000000000000003", "十一月起新域名生效",
            created_at="2026-10-01T00:00:00Z", valid_from="2026-11-01T00:00:00Z"))
        live = self.store.brief()
        self.assertEqual(live["counts"]["current"], 0)
        after = self.store.brief(at="2026-11-02T00:00:00Z")
        self.assertEqual(after["counts"]["current"], 1)
        self.assertEqual(status_at(self.store.claims(status="all")[0], moment("2026-10-15T00:00:00Z")),
                         None)

    def test_retroactive_valid_to_hides_claim_from_live_view(self):
        # Recorded on April 1st about a March decision: the window had already
        # closed, so the claim never counts as current on the live view, and an
        # as-of query inside March cannot see it either — it had not been
        # recorded yet. As-of answers what the ledger believed then.
        self.write_raw(self.raw_claim(
            "clm_d000000000000004", "三月起接口由网关接管",
            created_at="2026-04-01T00:00:00Z", valid_from="2026-03-01T00:00:00Z",
            valid_to="2026-03-20T00:00:00Z"))
        live = self.store.brief()
        self.assertEqual(live["counts"]["current"], 0)
        before_record = self.store.brief(at="2026-03-10T00:00:00Z")
        self.assertEqual(before_record["counts"]["current"], 0)
        after_record = self.store.brief(at="2026-04-05T00:00:00Z")
        self.assertEqual(after_record["counts"]["superseded"], 1)
        self.assertEqual(after_record["counts"]["current"], 0)

    def test_record_rejects_inverted_validity_window(self):
        with self.assertRaisesRegex(ClaimStoreError, "valid_from"):
            self.store.record("窗口倒置", valid_from="2026-05-01T00:00:00Z",
                              valid_to="2026-04-01T00:00:00Z")
        with self.assertRaisesRegex(ClaimStoreError, "valid_from"):
            self.store.record("格式错误", valid_from="2026-05-01")

    def test_claims_at_requires_explicit_status(self):
        self.store.record("数据库统一使用 SQLite")
        with self.assertRaisesRegex(ClaimStoreError, "--at requires"):
            self.store.claims(status="all", at="2026-01-01T00:00:00Z")
        rows = self.store.claims(status="current", at="2999-01-01T00:00:00Z")
        self.assertEqual(len(rows), 1)

    # ------------------------------------------------------- depends_on / unmotivated

    def test_fallen_premise_flags_dependent_as_unmotivated(self):
        premise = self.store.record("团队长期维护 PostgreSQL")["recorded"]
        decision = self.store.record(
            "数据库统一使用 PostgreSQL", topic="database",
            depends_on=[premise["claim_id"]])["recorded"]
        live = self.store.brief()
        self.assertEqual(live["counts"]["current"], 2)
        self.assertNotIn("unmotivated", live["counts"])
        self.store.record("团队解散，PostgreSQL 无人维护", topic="database",
                          supersedes=premise["claim_id"])
        flagged = self.store.brief()
        self.assertEqual(flagged["counts"]["current"], 1)
        self.assertEqual(flagged["counts"]["unmotivated"], 1)
        self.assertEqual(self.brief_ids(flagged, "unmotivated"), [decision["claim_id"]])
        self.assertEqual(flagged["unmotivated"][0]["broken_dependencies"],
                         [premise["claim_id"]])
        topics = {c["claim_id"] for b in flagged["topics"] for c in b["claims"]}
        self.assertNotIn(decision["claim_id"], topics)

    def test_dependency_references_are_validated(self):
        with self.assertRaisesRegex(ClaimStoreError, "not found"):
            self.store.record("悬空依赖", depends_on=["clm_ffffffffffffffff"])
        # A row can only self-reference through raw writes; reading refuses it.
        self.write_raw(self.raw_claim("clm_e000000000000005", "自引用",
                                      created_at="2026-01-01T00:00:00Z",
                                      depends_on=["clm_e000000000000005"]))
        with self.assertRaisesRegex(ClaimStoreError, "itself"):
            self.store.claims(status="all")
        self.write_raw(self.raw_claim("clm_e000000000000006", "悬空",
                                      created_at="2026-01-01T00:00:00Z",
                                      depends_on=["clm_ffffffffffffffff"]))
        with self.assertRaisesRegex(ClaimStoreError, "dangling"):
            self.store.claims(status="all")

    def test_unmotivated_respects_topic_filter(self):
        premise = self.store.record("前提", topic="ops")["recorded"]
        self.store.record("受影响决定", topic="database", depends_on=[premise["claim_id"]])
        self.store.record("新前提替代旧的", topic="ops", supersedes=premise["claim_id"])
        scoped = self.store.brief(topic="database")
        self.assertEqual(scoped["counts"].get("unmotivated", 0), 1)
        other = self.store.brief(topic="ops")
        self.assertEqual(other["counts"].get("unmotivated", 0), 0)

    # ------------------------------------------------------------- dispute closure

    def test_resolve_sustain_promotes_the_objection(self):
        standing = self.store.record("数据库统一使用 SQLite")["recorded"]
        dispute = self.store.record("数据库统一使用 PostgreSQL", dispute=True)["recorded"]
        self.assertEqual(dispute["disputes"], [standing["claim_id"]])
        result = self.store.resolve(dispute["claim_id"], outcome="sustain")
        self.assertTrue(result["promoted"])
        rows = {r["claim_id"]: r for r in self.store.claims(status="all")}
        self.assertEqual(rows[dispute["claim_id"]]["status"], "现行")
        self.assertNotIn("disputes", rows[dispute["claim_id"]])
        self.assertEqual(rows[standing["claim_id"]]["status"], "已过期")
        self.assertEqual(rows[standing["claim_id"]]["superseded_by"], dispute["claim_id"])
        self.assertEqual(self.store.brief()["counts"]["disputed"], 0)

    def test_resolve_withdraw_retracts_the_objection(self):
        standing = self.store.record("数据库统一使用 SQLite")["recorded"]
        dispute = self.store.record("数据库统一使用 PostgreSQL", dispute=True)["recorded"]
        self.store.resolve(dispute["claim_id"], outcome="withdraw")
        rows = {r["claim_id"]: r for r in self.store.claims(status="all")}
        self.assertEqual(rows[standing["claim_id"]]["status"], "现行")
        self.assertEqual(rows[dispute["claim_id"]]["status"], "已过期")
        self.assertEqual(rows[dispute["claim_id"]]["superseded_by"], standing["claim_id"])

    def test_resolve_supersede_records_a_new_decision(self):
        standing = self.store.record("数据库统一使用 SQLite")["recorded"]
        dispute = self.store.record("数据库统一使用 PostgreSQL", dispute=True)["recorded"]
        result = self.store.resolve(
            dispute["claim_id"], outcome="supersede",
            text="数据库分库：分析用 PostgreSQL，业务用 SQLite", topic="database")
        decision = result["recorded"]
        rows = {r["claim_id"]: r for r in self.store.claims(status="all")}
        self.assertEqual(rows[decision["claim_id"]]["status"], "现行")
        for retired in (standing["claim_id"], dispute["claim_id"]):
            self.assertEqual(rows[retired]["status"], "已过期")
            self.assertEqual(rows[retired]["superseded_by"], decision["claim_id"])

    def test_resolve_refuses_invalid_transitions(self):
        standing = self.store.record("数据库统一使用 SQLite")["recorded"]
        dispute = self.store.record("数据库统一使用 PostgreSQL", dispute=True)["recorded"]
        with self.assertRaisesRegex(ClaimStoreError, "not disputed"):
            self.store.resolve(standing["claim_id"], outcome="withdraw")
        with self.assertRaisesRegex(ClaimStoreError, "outcome"):
            self.store.resolve(dispute["claim_id"], outcome="coin-flip")
        with self.assertRaisesRegex(ClaimStoreError, "requires the new decision text"):
            self.store.resolve(dispute["claim_id"], outcome="supersede")

    def test_resolve_withdraw_without_standing_target_is_refused(self):
        dispute = self.store.record("接口超时责任仍未定", topic="ops", dispute=True)["recorded"]
        with self.assertRaisesRegex(ClaimStoreError, "no standing claim"):
            self.store.resolve(dispute["claim_id"], outcome="withdraw")

    def test_sustain_surfaces_leftover_conflicts(self):
        standing = self.store.record("缓存统一使用 Redis 集群")["recorded"]
        other = self.store.record("缓存由单机 Redis 提供", topic="cache",
                                  scope="production")["recorded"]
        dispute = self.store.record("缓存统一使用 Redis 集群多副本",
                                    topic="cache", dispute=True)["recorded"]
        # The dispute conflicts with the standing claim only; the scoped sibling
        # stays untouched and sustaining must not smuggle a second conflict in.
        self.store.resolve(dispute["claim_id"], outcome="sustain")
        rows = {r["claim_id"]: r for r in self.store.claims(status="all")}
        self.assertEqual(rows[other["claim_id"]]["status"], "现行")
        self.assertEqual(rows[standing["claim_id"]]["status"], "已过期")

    def test_dispute_visible_only_before_resolution_point(self):
        self.write_raw(
            self.raw_claim("clm_f000000000000006", "数据库统一使用 SQLite",
                           created_at="2026-01-01T00:00:00Z"),
            self.raw_claim("clm_1000000000000070", "数据库统一使用 PostgreSQL",
                           created_at="2026-02-01T00:00:00Z", status="有争议",
                           updated_at="2026-02-01T00:00:00Z",
                           disputes=["clm_f000000000000006"]))
        during = self.store.brief(at="2026-02-15T00:00:00Z")
        self.assertEqual(during["counts"]["disputed"], 1)
        # Close the dispute by hand at a known instant, then look back past it.
        rows = self.store._read()
        dispute_row = next(r for r in rows if r["claim_id"] == "clm_1000000000000070")
        dispute_row["status"] = "已过期"
        dispute_row["superseded_by"] = "clm_f000000000000006"
        dispute_row["superseded_at"] = "2026-03-01T00:00:00Z"
        dispute_row["updated_at"] = "2026-03-01T00:00:00Z"
        dispute_row.pop("disputes")
        self.store._write(rows)
        after = self.store.brief(at="2026-03-15T00:00:00Z")
        self.assertEqual(after["counts"]["disputed"], 0)
        self.assertEqual(after["counts"]["current"], 1)

    # ------------------------------------------------------------------ CLI wiring

    def test_cli_resolve_and_point_in_time_brief(self):
        from chat_distiller.claims_cli import main
        standing = self.store.record("数据库统一使用 SQLite")["recorded"]
        dispute = self.store.record("数据库统一使用 PostgreSQL", dispute=True)["recorded"]
        self.assertEqual(
            main(["resolve", dispute["claim_id"], "--sustain", "--store", str(self.store_path)]), 0)
        code = main(["brief", "--at", "2999-01-01T00:00:00Z", "--store", str(self.store_path)])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
