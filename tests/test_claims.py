"""Claim store: in-situ capture, explicit conflict resolution, budgeted briefs."""
import json
import tempfile
import unittest
from pathlib import Path

from chat_distiller import ClaimStore, ClaimStoreError


class ClaimStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_path = Path(self.tmp.name) / "claims.jsonl"
        self.store = ClaimStore(self.store_path)

    def write_raw(self, *claims):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(
            "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in claims), encoding="utf-8")

    def test_record_creates_store_with_valid_receipt(self):
        result = self.store.record("数据库统一使用 PostgreSQL", topic="database", tags=["storage"])
        self.assertTrue(result["ok"])
        claim = result["recorded"]
        self.assertEqual(claim["status"], "现行")
        self.assertTrue(claim["claim_id"].startswith("clm_"))
        self.assertEqual(len(claim["claim_id"]), 4 + 16)
        self.assertIsNone(claim["superseded_by"])
        self.assertTrue(self.store_path.is_file())
        rows = self.store._read()
        self.assertEqual([r["claim_id"] for r in rows], [claim["claim_id"]])

    def test_record_normalizes_whitespace_and_rejects_bad_topic(self):
        result = self.store.record("  API   v1 保持冻结  ")
        self.assertEqual(result["recorded"]["text"], "API v1 保持冻结")
        with self.assertRaisesRegex(ClaimStoreError, "topic"):
            self.store.record("another", topic="Bad Topic")

    def test_duplicate_text_is_refused(self):
        self.store.record("部署脚本不再写入生产数据库")
        with self.assertRaisesRegex(ClaimStoreError, "identical claim"):
            self.store.record("部署脚本不再写入生产数据库")

    def test_conflict_requires_explicit_resolution(self):
        first = self.store.record("数据库统一使用 SQLite")["recorded"]
        with self.assertRaisesRegex(ClaimStoreError, "possible conflict") as ctx:
            self.store.record("数据库统一使用 PostgreSQL")
        self.assertIn(first["claim_id"], str(ctx.exception))
        disputed = self.store.record("数据库统一使用 PostgreSQL", dispute=True)
        self.assertEqual(disputed["recorded"]["status"], "有争议")
        self.assertEqual(disputed["conflicts_with"], [first["claim_id"]])
        rows = self.store.claims()
        statuses = {r["claim_id"]: r["status"] for r in rows}
        self.assertEqual(statuses[first["claim_id"]], "现行")

    def test_unrelated_claims_do_not_conflict(self):
        self.store.record("数据库统一使用 PostgreSQL", topic="database")
        result = self.store.record("前端组件迁移到 React 18", topic="frontend")
        self.assertEqual(result["conflicts_with"], [])
        self.assertEqual(result["recorded"]["status"], "现行")

    def test_supersede_transitions_target_and_rejects_bad_targets(self):
        old = self.store.record("数据库统一使用 SQLite")["recorded"]
        result = self.store.record("数据库统一使用 PostgreSQL", supersedes=old["claim_id"])
        self.assertEqual(result["superseded"], old["claim_id"])
        rows = {r["claim_id"]: r for r in self.store.claims(status="all")}
        self.assertEqual(rows[old["claim_id"]]["status"], "已过期")
        self.assertEqual(rows[old["claim_id"]]["superseded_by"], result["recorded"]["claim_id"])
        self.assertEqual(rows[result["recorded"]["claim_id"]]["status"], "现行")
        with self.assertRaisesRegex(ClaimStoreError, "not found"):
            self.store.record("x", supersedes="clm_" + "0" * 16)
        with self.assertRaisesRegex(ClaimStoreError, "already superseded"):
            self.store.record("数据库改回 SQLite", supersedes=old["claim_id"])

    def test_supersede_multiple_detected_conflicts_at_once(self):
        base = self.store.record("Placeholder decision", topic="database")["recorded"]
        old_a = dict(base, claim_id="clm_" + "a" * 16, text="Use SQLite for all storage")
        old_b = dict(base, claim_id="clm_" + "b" * 16, text="Use SQLite for all production storage")
        self.write_raw(old_a, old_b)
        result = self.store.record(
            "Use SQLite for all storage in production",
            topic="database", supersedes=[old_a["claim_id"], old_b["claim_id"]])
        self.assertEqual(result["superseded_claims"], [old_a["claim_id"], old_b["claim_id"]])
        rows = {row["claim_id"]: row for row in self.store.claims(status="all")}
        for old in (old_a, old_b):
            self.assertEqual(rows[old["claim_id"]]["status"], "已过期")
            self.assertEqual(rows[old["claim_id"]]["superseded_by"], result["recorded"]["claim_id"])

    def test_partial_conflict_supersede_is_refused(self):
        base = self.store.record("Placeholder decision", topic="database")["recorded"]
        old_a = dict(base, claim_id="clm_" + "a" * 16, text="Use SQLite for all storage")
        old_b = dict(base, claim_id="clm_" + "b" * 16, text="Use SQLite for all production storage")
        self.write_raw(old_a, old_b)
        with self.assertRaisesRegex(ClaimStoreError, "unresolved conflict"):
            self.store.record(
                "Use SQLite for all storage in production",
                topic="database", supersedes=[old_a["claim_id"]])
        # The refused write must leave both current claims untouched.
        rows = {row["claim_id"]: row for row in self.store.claims(status="all")}
        self.assertEqual(rows[old_a["claim_id"]]["status"], "现行")
        self.assertEqual(rows[old_b["claim_id"]]["status"], "现行")

    def test_english_status_aliases_are_accepted(self):
        current = self.store.record("Alias current")["recorded"]
        self.store.record("Alias disputed", dispute=True)
        self.assertEqual([row["claim_id"] for row in self.store.claims(status="current")],
                         [current["claim_id"]])
        self.assertEqual(len(self.store.claims(status="disputed")), 1)
        self.assertEqual(len(self.store.claims(status="all")), 2)

    def test_brief_orders_disputes_first_and_respects_status(self):
        current = self.store.record("API v1 保持冻结")["recorded"]
        old = self.store.record("数据库统一使用 SQLite")["recorded"]
        self.store.record("数据库统一使用 PostgreSQL", supersedes=old["claim_id"])
        self.store.record("缓存层选型仍有分歧", dispute=True)
        packet = self.store.brief()
        self.assertEqual(packet["status"], "ready")
        self.assertEqual(packet["counts"]["current"], 2)
        self.assertEqual([d["text"] for d in packet["disputed"]], ["缓存层选型仍有分歧"])
        self.assertEqual(len(packet["topics"]), 1)
        self.assertIn(current["claim_id"], [c["claim_id"] for c in packet["topics"][0]["claims"]])
        self.assertNotIn(old["claim_id"], [c["claim_id"] for c in packet["topics"][0]["claims"]])
        superseded = packet["recently_superseded"]
        self.assertEqual([s["claim_id"] for s in superseded], [old["claim_id"]])
        self.assertEqual(superseded[0]["superseded_by"],
                         [r for r in self.store.claims() if r["text"] == "数据库统一使用 PostgreSQL"][0]["claim_id"])

    def test_brief_byte_contract_holds(self):
        from chat_distiller import serialize_packet
        fixture = [
            ("认证服务改用短令牌加刷新机制", "auth"),
            ("构建产物只保留最近五个版本", "build"),
            ("日志采样率固定为百分之一", "logging"),
            ("所有对外接口必须带幂等键", "api"),
            ("数据库迁移一律先在影子库演练", "database"),
            ("前端路由已切换到懒加载", "frontend"),
            ("部署窗口固定在每周二上午", "deploy"),
            ("缓存键必须带上租户前缀", "cache"),
            ("错误码表由平台组统一维护", "errors"),
            ("测试覆盖率门槛设为百分之八十", "testing"),
            ("消息队列改用至少一次投递", "queue"),
            ("配置中心为唯一配置来源", "config"),
            ("生产环境禁止直接查库排障", "ops"),
            ("文档更新随代码合并同一请求", "docs"),
            ("服务间调用默认携带追踪头", "tracing"),
            ("定时任务统一注册到调度平台", "scheduler"),
            ("新依赖引入需要安全评审", "deps"),
            ("回滚脚本每月演练一次", "rollback"),
            ("告警阈值按季节动态调整", "alerting"),
            ("网关层统一限流为千次每秒", "gateway"),
            ("图片资源走对象存储加分发网", "media"),
            ("代码评审至少一名资深成员", "review"),
            ("灰度发布按小步递增放量", "release"),
            ("本地开发统一使用容器编排", "dev-env"),
            ("密钥轮换周期缩短到九十天", "security"),
            ("搜索索引每晚全量重建一次", "search"),
            ("客户端最低支持版本提升", "client"),
            ("数据备份保留三十五天", "backup"),
            ("多语言文案由翻译平台同步", "i18n"),
            ("性能基线每季度重测一次", "perf"),
        ]
        for text, topic in fixture:
            self.store.record(text, topic=topic)
        packet = self.store.brief(max_bytes=8192)
        wire = serialize_packet(packet)
        self.assertEqual(len(wire.encode("utf-8")), packet["used_bytes"])
        self.assertLessEqual(packet["used_bytes"], packet["budget_bytes"])
        self.assertTrue(packet["topics"])
        tight = self.store.brief(max_bytes=500)
        tight_wire = serialize_packet(tight)
        self.assertEqual(len(tight_wire.encode("utf-8")), tight["used_bytes"])
        self.assertLessEqual(tight["used_bytes"], 500)
        self.assertIn(tight["status"], ("ready", "budget_exhausted", "empty"))

    def test_empty_store_brief_is_empty_and_topic_filter_works(self):
        packet = self.store.brief()
        self.assertEqual(packet["status"], "empty")
        self.store.record("后端接口的速率限制为每秒一百次", topic="backend")
        self.store.record("前端路由已切换到懒加载", topic="frontend")
        filtered = self.store.brief(topic="backend")
        topics = [b["topic"] for b in filtered["topics"]]
        self.assertEqual(topics, ["backend"])

    def test_corrupt_store_refuses_service_with_line_number(self):
        self.store.record("正常的声明")
        with self.store.path.open("a", encoding="utf-8") as handle:
            handle.write("{not json}\n")
        with self.assertRaisesRegex(ClaimStoreError, "line 2"):
            self.store.claims()
        with self.assertRaisesRegex(ClaimStoreError, "line 2"):
            self.store.brief()

    def test_invalid_status_and_broken_relations_refuse_service(self):
        base = self.store.record("基础声明")["recorded"]
        broken = dict(base, status="已废弃")
        self.write_raw(broken)
        with self.assertRaisesRegex(ClaimStoreError, "unknown status"):
            self.store.claims()
        expired_no_successor = dict(base, status="已过期", superseded_by=None)
        self.write_raw(expired_no_successor)
        with self.assertRaisesRegex(ClaimStoreError, "without successor"):
            self.store.claims()
        dangling = dict(base, status="已过期", superseded_by="clm_" + "f" * 16)
        self.write_raw(dangling)
        with self.assertRaisesRegex(ClaimStoreError, "dangling"):
            self.store.claims()

    def test_supersession_cycle_refuses_service(self):
        a = self.store.record("声明甲")["recorded"]
        b = self.store.record("声明乙", supersedes=a["claim_id"])["recorded"]
        rows = self.store.claims(status="all")
        # 乙 already supersedes 甲; forge 甲 superseding 乙 in turn -> cycle.
        forged = [dict(r, status="已过期",
                       superseded_by=(b["claim_id"] if r["claim_id"] == a["claim_id"] else a["claim_id"]))
                  for r in rows]
        self.write_raw(*forged)
        with self.assertRaisesRegex(ClaimStoreError, "cycle"):
            self.store.claims()

    def test_claims_listing_filters(self):
        self.store.record("部署流水线必须先跑集成测试", topic="backend", tags=["api"])
        disputed = self.store.record("缓存上限的数值仍有分歧", topic="backend", dispute=True)["recorded"]
        self.store.record("前端组件迁移到 React 18", topic="frontend")
        self.assertEqual(len(self.store.claims(status="现行")), 2)
        self.assertEqual(len(self.store.claims(status="all", topic="backend")), 2)
        self.assertEqual([c["claim_id"] for c in self.store.claims(status="有争议")],
                         [disputed["claim_id"]])
        self.assertEqual([c["claim_id"] for c in self.store.claims(status="all", query="前端")][0],
                         [c for c in self.store.claims(status="all") if c["topic"] == "frontend"][0]["claim_id"])

    def test_scope_narrows_conflicts_and_filters_briefs(self):
        prod = self.store.record("数据库统一使用 SQLite", topic="database",
                                 scope="production")["recorded"]
        # Same words in a disjoint scope: no conflict, both current.
        staging_result = self.store.record("数据库统一使用 PostgreSQL", topic="database",
                                           scope="staging")
        staging = staging_result["recorded"]
        self.assertEqual(staging_result["conflicts_with"], [])
        # An all-scope decision overlaps every scope, so this is refused.
        with self.assertRaisesRegex(ClaimStoreError, "possible conflict"):
            self.store.record("数据库统一改用 SQLite", topic="database")
        packet = self.store.brief(scope="production")
        self.assertEqual(packet["scope"], "production")
        self.assertEqual([c["claim_id"] for b in packet["topics"] for c in b["claims"]],
                         [prod["claim_id"]])
        everything = self.store.brief()
        self.assertEqual(everything["counts"]["current"], 2)
        rows = self.store.claims(scope="staging")
        self.assertEqual([r["claim_id"] for r in rows], [staging["claim_id"]])

    def test_time_expiry_keeps_the_chain_and_counts_honestly(self):
        from datetime import datetime, timedelta, timezone
        soon = (datetime.now(timezone.utc) + timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        later = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.store.record("会过期的决定", expires_at=soon)
        kept = self.store.record("仍有效的决定", expires_at=later)["recorded"]
        packet = self.store.brief()
        self.assertEqual(packet["counts"]["time_expired"], 0)
        # Before the deadline both are current; claims() mirrors that by default.
        self.assertEqual(len(self.store.claims(status="现行")), 2)
        with self.assertRaisesRegex(ClaimStoreError, "future"):
            self.store.record("回写过去的决定", expires_at="2020-01-01T00:00:00Z")
        with self.assertRaisesRegex(ClaimStoreError, "expires_at"):
            self.store.record("格式错误的决定", expires_at="tomorrow")
        import time as time_module
        time_module.sleep(2.2)
        packet = self.store.brief()
        self.assertEqual(packet["counts"]["time_expired"], 1)
        self.assertEqual(packet["counts"]["current"], 1)
        rows = self.store.claims(status="现行", include_time_expired=False)
        self.assertEqual([r["claim_id"] for r in rows], [kept["claim_id"]])
        # Expiry is a read-time policy: the row keeps its stored status.
        stored = {r["claim_id"]: r for r in self.store._read()}
        expired = [r for r in stored.values() if r["text"] == "会过期的决定"][0]
        self.assertEqual(expired["status"], "现行")
        self.assertIsNone(expired["superseded_by"])
        self.assertIn("expires_at", expired)
        # Time-expired claims no longer trigger conflicts or the duplicate guard.
        renewed = self.store.record("会过期的决定", topic="general")
        self.assertEqual(renewed["conflicts_with"], [])

    def test_scope_and_expiry_validation(self):
        with self.assertRaisesRegex(ClaimStoreError, "scope"):
            self.store.record("范围非法", scope="Production")
        self.assertEqual(self.store.record("默认范围")["recorded"]["scope"], "all")

    def test_default_store_path_and_missing_parent(self):
        store = ClaimStore(Path(self.tmp.name) / "deep" / "nested" / "claims.jsonl")
        store.record("嵌套目录也会创建")
        self.assertTrue((Path(self.tmp.name) / "deep" / "nested" / "claims.jsonl").is_file())

    def test_cli_record_and_brief_end_to_end(self):
        from chat_distiller import claims_cli as claims_module
        rc = claims_module.main(["record", "CLI 端到端声明", "--store", str(self.store_path), "--json"])
        self.assertEqual(rc, 0)
        rc = claims_module.main(["brief", "--store", str(self.store_path), "--compact"])
        self.assertEqual(rc, 0)
        rc = claims_module.main(["record", "CLI 端到端声明", "--store", str(self.store_path)])
        self.assertEqual(rc, 1)

    def test_cli_scope_and_expiry_flags(self):
        import io
        import contextlib
        from chat_distiller import claims_cli as claims_module
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = claims_module.main([
                "record", "生产库统一 PostgreSQL", "--store", str(self.store_path),
                "--scope", "production", "--json"])
        self.assertEqual(rc, 0)
        receipt = json.loads(buffer.getvalue())
        self.assertEqual(receipt["recorded"]["scope"], "production")
        rows = self.store.claims(scope="production")
        self.assertEqual(rows[0]["text"], "生产库统一 PostgreSQL")
        rows = self.store.claims(scope="staging")
        self.assertEqual(rows, [])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = claims_module.main(["brief", "--store", str(self.store_path), "--scope", "staging"])
        self.assertEqual(rc, 0)
        packet = json.loads(buffer.getvalue())
        self.assertEqual(packet["scope"], "staging")
        self.assertEqual(packet["counts"]["current"], 0)


if __name__ == "__main__":
    unittest.main()
