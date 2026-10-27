<picture>
  <source media="(prefers-color-scheme: dark) and (prefers-reduced-motion: no-preference)" srcset="assets/brand/hero-dark.svg">
  <source media="(prefers-reduced-motion: no-preference)" srcset="assets/brand/hero-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/hero-dark-static.svg">
  <img src="assets/brand/hero-light-static.svg" alt="ClaimLedger. Your work continues. The decision ledger for AI agents." width="100%">
</picture>

# ClaimLedger · 台账

**AI Agent 的决定台账。** 决策只记录一次，保留状态与出处，过期结论永不冒充现状——全部本地运行，零第三方依赖、零网络调用、零模型密钥。

曾用名 **CarryTrace / chat-distiller**；兼容入口与既有数据目录（`~/.chat-distiller`，包名 `chat_distiller`）均保留。

> 检索命中 ≠ 结论现行；冲突已记录 ≠ 争议已收场；引用存在 ≠ 结论正确。

[![测试](https://github.com/Anhao1314/ClaimLedger/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Anhao1314/ClaimLedger/actions/workflows/tests.yml)
[![验证证据](https://github.com/Anhao1314/ClaimLedger/actions/workflows/evidence.yml/badge.svg?branch=main)](https://github.com/Anhao1314/ClaimLedger/actions/workflows/evidence.yml)

[问题](#problem) · [方法](#method) · [效果](#results) · [演示](#demo) · [思路](#design) · [使用指南](#quick-start) · [发布版本](https://github.com/Anhao1314/ClaimLedger/releases/latest) · [English](README.md)

<a id="demo"></a>
## 60 秒上手演示

**演示跑的是真引擎，不是录屏。** 一条项目时间线，直接调用与 CLI、MCP 服务相同的 `ClaimStore`——合成的 Atlas API 项目写入一次性临时存储。

```bash
python -m pip install -e .
claim demo        # 打开 http://127.0.0.1:8765
```

<img src="assets/demo/claimledger-demo.gif" alt="八帧走查真实运行的演示：台账、冲突拒写、预算简报、状态盲检索、证据包、审计、基准证据与取代链" width="820">

- **记录** 一条与 PostgreSQL 声明重叠的决策：写入被拒绝，内联冲突卡让你二选一——替代旧的或记为有争议，绝不静默合并。
- **拉低预算**：条目逐条被省略，并**如实计数**省略了多少。
- **时间切换** 把整条时间线重建到任意时刻——九月三十日、迁移发生之前，当时账本认为什么算数。
- **开发者抽屉** 收纳原始简报 wire、状态盲 vs 状态感知检索、RAG 证据包与安全工具，一步可达。

不需要模型密钥、不联网、不装数据库。演示绝不碰你的真实账本——除非你显式用 `--store --write` 绑定。

[产品落地页](https://anhao1314.github.io/ClaimLedger/) · [演示指南](docs/demo.md) · [界面重构笔记](docs/demo-redesign.zh-CN.md)

<a id="problem"></a>
## 一、问题：AI Agent 的失忆症

AI 编程助手像个绝顶聪明但每天失忆的新员工。长期协作时，你会反复遇到三种事故：

1. **新会话从零开始。** 上周吵了半小时定下的架构决定、约定"不许动 API v1"的约束，新会话里全没了，Agent 重新踩你踩过的坑。
2. **过期结论复活。** 你们从 SQLite 迁到了 PostgreSQL，但旧会话记录还在——任何"把历史聊天喂回去"的方案都会把旧决定当现行事实捞出来。
3. **争议被悄悄闭环。** 没吵完的问题（"超时到底是谁的锅"）两边发言都躺在记录里，检索出来一半一半，Agent 自己挑一个当结论，编造闭环。

<img src="assets/demo/search.png" alt="演示中的状态盲检索：已过期的 SQLite 决策排到了现行 PostgreSQL 声明前面" width="760">

*故意展示的失败模式：关掉状态过滤，过期结论排到第一。*

**为什么现有方案不够：** 人工维护的 AGENTS.md 会腐烂——文件里写的永远"现行"，过期的规则没人敢删；向量检索语义强，但黑箱、无状态，过期结论照样自信返回；云端记忆不可审计、不可迁移。缺的是同一个东西：**一条"什么还算数"的生命周期。**

<a id="method"></a>
## 二、方法：一本只增不删的决定台账

一条声明（claim）= 一段独立可懂的结论 + 状态 + 溯源。围绕它：两种写入、三种读法、一台闭环状态机。

```
决策发生 ──record──▶  声明库 claims.jsonl（唯一权威）
                        │  状态机：现行 / 已替代 / 有争议
                        │  （替代链；争议经 resolve 收场，不再悬置）
                        ├──brief──▶  开工简报（字节预算；--at 可重建任意过去时刻）
                        ├──wiki ──▶  主题知识页（版本化，引用可查）
                        └──search─▶  长尾检索（词法 + 状态过滤）
record --depends-on …  硬依赖边；前提坍塌时，依赖者自动进入"待复审"
```

- **`record`——写入即声明。** 新声明与现行声明冲突时**写入被拒绝**；必须显式"替代旧的"或"标成有争议"。矛盾在有人在场时摊开。
- **`resolve`——争议收场，不再腐烂。** 维持异议、撤回、或以一条新决定收场——每种结局都保持替代链有效、可审计。
- **`brief`——读取即简报。** 确定性渲染，字节预算是硬契约——用了多少字节、漏了几条，都是可验证的数字。
- **`--at`——重建任意时刻。** 声明带现实生效窗口与系统时间戳，账本能回答"当时认为什么算数"。
- **`--depends-on`——依赖会回溯。** 前提坍塌时，依赖者在简报中以"待复审"浮出，而不是冒充定论。
- **分层赌注：** 确定性的代码管结构与完整性，语义判断留给 Agent 和人。代码保证"引用可查、状态如实、装得下"，不判断真假。

<img src="assets/demo/conflict.png" alt="演示中冲突写入被拒绝，由人显式选择替代或记为有争议" width="760">

*冲突写入在触碰存储前停下——由人选择解决方式。*

<img src="assets/demo/brief.png" alt="演示中 512 字节的简报：省略 12 条，且省略数量写在包里" width="760">

*拉低预算，看条目逐条被省略——并如实计数。*

全部本地：单文件 JSONL、零依赖、无常驻进程；换工具换模型，知识不跟着厂商走。

<a id="results"></a>
## 三、效果：可重放的证据

**过期结论不再冒充现状**（24 条查询的检索基准，40 个合成会话）：

| 方法 | Recall@1 | Recall@5 | MRR@5 | stale-hit@5 |
| --- | ---: | ---: | ---: | ---: |
| 原始转录词面检索 | 0.4167 | 0.9583 | 0.6528 | 0.5417 |
| 结构化记忆 | 0.5417 | **1.0000** | 0.7604 | 0.5000 |
| 结构化 + 状态感知 | **0.7083** | 0.9167 | **0.7931** | 0.0000 |

状态过滤把检索结果里的过期命中从 **54% 压到 0**——这正是"不拿过期结论当现状"的量化形态。代价同样如实：状态排序在这组数据中使 Recall@5 从 1.0000 降至 0.9167。[逐例结果与意图切片](benchmarks/benchmark-results.md)。

**结构安全检查**（CompileBench：四个主题、十二张人工编写的原子卡片、零模型调用。这是工程检查，不是语义准确率）：

| 检查项目 | 实际结果 |
| --- | ---: |
| 无效提案被拒绝，且未创建编译状态 | 16 / 16 |
| 完整 UTF-8 恢复包字节预算检查 | 16 / 16 |
| 关闭新鲜度检查后仍返回旧页 | 4 / 4 |
| 启用新鲜度检查后仍返回旧页 | 0 / 4 |
| 更新后保留知识身份与旧版的主题 | 4 / 4 |

带有真实摘录的错误综合仍可能通过结构校验，引用不证明结论被来源支持。[结果与局限](benchmarks/wiki/results.md)。

同一次实跑中，同一个问题的四种结局——命中现行、放行历史、诚实未命中、预算不足（实际 CLI 输出的投影，非模型评测）：

![四种检索结局的实跑投影](assets/recovery-demo.svg)

**工程效果：** 421 个测试跑在 macOS 与 Linux CI 上；下面"使用指南"中的每条命令都被 CI 实际执行并核对输出；六个 `verify_*` 工具在隔离安装环境验证发行完整性；零第三方依赖。

<a id="design"></a>
## 四、解题思路：三把钥匙

"上下文 + 记忆"不是一个问题。把它拆成三个互不相同的子问题，每一层交给与它性质匹配的机制，而不是指望"更聪明的检索"包打天下：

- **信（时变性）——用状态机解，不用智能解。** 记忆系统的死法不是遗忘，而是自信地端出过期结论。现行/已替代/有争议 + `superseded_by` 链，把"什么还算数"变成确定性可校验的事实。
- **写（惯性）——用现场捕获解，不用仪式解。** 事后读转录重建决策注定滞后易漏；决策现场一条 `record` 成本趋近于零。最好的读优化是让写入变便宜。
- **读（多样性）——用分层解，不用单一解。** 接续工作要"现状通告"（简报），高频问题要"综合好的页"（Wiki），长尾问题才需要检索。三种出口共享同一个声明库与字节预算。

**单一权威：** 声明库是唯一真相；Wiki 页、简报、导出都是可丢弃、可重建的视图。凡是允许两份真相的设计，最终都会用工程偿还一致性债务。

**v2：治理式记忆** 补上了自己的三个开口——争议可收场（`resolve`）、时间是双轴的（`--at` 重建"当时认为什么"）、前提可回溯（`--depends-on`）。完整理论（TMS 谱系、CoALA 定位）、含被否方案的决策记录与竞品审计见 [v2 设计文档](docs/design-v2.zh-CN.md)；对旧架构的逐条诊断（含 file:line 证据）见[重构设计文档](docs/refactor-design.md)。

**同样重要的是拒绝清单：** 不内置向量库、不做全自动写入、不做常驻进程、不做云同步。

<img src="assets/demo/chain.png" alt="演示中展开的已替代声明：记录于 09/12，出处与原话保留，被 PostgreSQL 声明替代" width="760">

*已过期不等于删除：旧声明保留原话，并指向取代它的声明。*

**RAG 是可选的证据层，不是权威。** 每条证据都必须解析到已存储的 claim，并接受同一套状态策略；索引是派生、可重建的。[RAG 适配指南](docs/rag.md)。

<a id="quick-start"></a>
## 五、使用指南

### 1. 安装

使用有本地 Shell 权限的 Agent 和 Python 3.9+。从本仓库安装（PyPI 发布名为 `claim-ledger`）：

```bash
git clone https://github.com/Anhao1314/ClaimLedger.git
cd ClaimLedger
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

### 2. 接入你的 Agent（两条路，可同时）

**MCP（推荐）**——让 Claude Code / ZCode 把台账当工具用：`claim_brief`（支持 as-of `at`）、`claim_record`（支持 `depends_on` 与生效窗口）、`claim_resolve`、`claim_claims`、`claim_recall`、`claim_suggest`：

```bash
claude mcp add claim-ledger -- claim mcp --store /你的项目/.claim-ledger/claims.jsonl
```

**Skill 安装**——让宿主 Agent 学会"开工先取简报、决策当场记录"：

```bash
claim skill install --host claude --scope user    # Codex 用 --host codex，两家都装用 --host both
```

### 3. 日常命令

```bash
claim init                                                  # 在当前目录创建 .claim-ledger/claims.jsonl
claim record "数据库统一使用 PostgreSQL" --topic database   # 决策当场记一条
claim record "冻结迁移窗口" --topic ops --scope production  # 限定生效范围
claim brief                                                  # 开工前的现状简报
claim claims --status all                                    # 翻台账
```

`claim init` 是幂等的：已有数据的账本会被拒绝，并把接入 Agent 的确切命令打印出来。Claim 还可带 `--scope`（决策适用的范围，互不相交的范围可共存）和 `--expires-at`（可选 UTC 截止时间；过期后不再算作现行，简报如实计入 time_expired，不改写历史）。

**冲突怎么处理**：如果 `record` 报 `possible conflict with current claim(s): clm_xxx`，二选一——

```bash
claim record "数据库统一使用 PostgreSQL" --topic database --supersedes clm_xxx   # 替代旧结论
claim record "超时问题责任仍有分歧" --topic ops --dispute                        # 记为有争议
```

**争议怎么收场**：已记录的争议自带它反对的对象，一条命令收场——

```bash
claim resolve clm_xxx --sustain     # 异议胜出：成为现行并替代其目标
claim resolve clm_xxx --withdraw    # 撤回异议，回到原现行决定
claim resolve clm_xxx --text "最终决定，独立可懂"       # 一条新决定取代双方
```

一次实跑看 v2 生命周期——前提坍塌，依赖它的决定浮出为"待复审"而不是冒充定论：

<!-- verify:v2 -->
```bash
export V2_DIR="$(mktemp -d)"
claim init --store "$V2_DIR/claims.jsonl" > /dev/null
claim record "The platform team owns PostgreSQL long-term" --topic database --store "$V2_DIR/claims.jsonl"
PREMISE=$(claim claims --store "$V2_DIR/claims.jsonl" | grep -o 'clm_[a-f0-9]*' | head -1)
claim record "Use PostgreSQL 16 for all storage" --topic database --depends-on "$PREMISE" --store "$V2_DIR/claims.jsonl"
claim record "The platform team disbands" --topic database --supersedes "$PREMISE" --store "$V2_DIR/claims.jsonl"
claim brief --store "$V2_DIR/claims.jsonl" | grep -q unmotivated && echo "dependent flagged for review"
```

**问"当时我们认为什么"**：每条声明带现实生效窗口（`--valid-from/--valid-to`，允许回溯补记）与系统时间戳，账本可以重建自己任意过去时刻——

```bash
claim record "预发环境用 SQLite" --topic database --valid-from 2026-09-01T00:00:00Z --valid-to 2026-10-01T00:00:00Z
claim brief --at 2026-10-15T00:00:00Z            # 十月十五日当时什么算数（以账本自身历史为准）
claim claims --status current --at 2026-10-15T00:00:00Z
```

### 4. 从任意聊天来源导入历史

Context Gateway 把既有会话历史变成干净转录和评审计划——支持豆包、通用 JSONL 和 Claude Code 会话：

```bash
claim connect generic --input talks.jsonl   # 或：claim connect claude-code
claim sync                                  # 只读暂存 + 评审计划
claim context "数据库迁移"                  # 蒸馏前即可词法检索
```

JSONL 契约：每行一个对象，含 `session_id`、`role`（`user`/`assistant`/`tool`/`system`）、`content`、`timestamp`（带时区的 ISO 8601）。[Gateway 指南](docs/context-gateway.md)。

### 5. 亲手跑一遍完整引擎

下面的示例使用旧入口 `chat-distiller`（永久兼容）。生命周期演示会创建新的临时目录，不使用个人知识库；示例从 SQLite 改为 PostgreSQL，但不会连接或迁移真实数据库。

<!-- verify:lifecycle -->
```bash
export WIKI_DEMO_PARENT="$(mktemp -d)"
python tools/wiki_demo.py --out "$WIKI_DEMO_PARENT/run"
```

<!-- verify:lifecycle-expected -->
```json
{
  "ok": true,
  "model_calls": 0,
  "commands_executed": 16
}
```

16 步命令、12 项检查使用人工编写的输入、预写综合与摘录式刷新，不调用模型。[演示源码](tools/wiki_demo.py) · [结果凭据](examples/wiki/lifecycle.expected.json)。

![ 合成生命周期，不是模型评测](assets/wiki-lifecycle.zh-CN.svg)

### 6. 记忆与 Wiki 手动教程

在仓库中使用已安装 CLI。下面定义的 `DEMO_DIR` 也供 SDK 与摄入示例使用。卡片是合成数据；绝不能用新身份初始化覆盖已有知识库。

<!-- verify:quickstart -->
```bash
export DEMO_DIR="$(mktemp -d)"
mkdir "$DEMO_DIR/vault"
chat-distiller migrate --mode init --distill examples/recovery/distill.json --out "$DEMO_DIR/memory.json"
chat-distiller render --distill "$DEMO_DIR/memory.json" --vault "$DEMO_DIR/vault"
chat-distiller recover --vault "$DEMO_DIR/vault" --query database --max-bytes 4096 > "$DEMO_DIR/recovery.json"
python -m json.tool "$DEMO_DIR/recovery.json"
```

<!-- verify:expected -->
```json
{
  "status": "ready",
  "requires_review": true,
  "used_bytes": 1398,
  "budget_bytes": 4096
}
```

`ready` 只表示记录装得下，不表示结论正确或任务完成。未解决的超时争议仍需要复核。预算计算完整 UTF-8 JSON 字节数，不是 token。

<!-- verify:wiki -->
```bash
chat-distiller wiki prepare --vault "$DEMO_DIR/vault" --topic database --query database > "$DEMO_DIR/proposal.json"
chat-distiller wiki compile --vault "$DEMO_DIR/vault" --proposal "$DEMO_DIR/proposal.json"
chat-distiller wiki compile --vault "$DEMO_DIR/vault" --proposal "$DEMO_DIR/proposal.json" --apply
chat-distiller wiki recover --vault "$DEMO_DIR/vault" --query database --max-bytes 8192 > "$DEMO_DIR/knowledge.json"
chat-distiller wiki export --vault "$DEMO_DIR/vault" --out "$DEMO_DIR/wiki-view"
```

`prepare` 生成摘录草稿，宿主负责语义综合；`compile` 默认预览，只有 `--apply` 才发布。包括无关修改在内的源变化都会使旧页失效；重编译同一主题会保留身份与旧版本。Markdown 导出是时点快照，不是第二份权威。[Wiki 指南](docs/knowledge-wiki.md) · [摄入](docs/ingestion.md)。

### 7. Python API

<!-- verify:sdk -->
```python
import os
from pathlib import Path
from chat_distiller import ClaimStore, KnowledgeStore, MemoryStore, serialize_packet

vault = Path(os.environ["DEMO_DIR"]) / "vault"
memory = MemoryStore(vault)
wiki = KnowledgeStore(vault)

hits = memory.search("database")
page = wiki.get("database")
packet = wiki.recover("database", max_bytes=8192)
wire = serialize_packet(packet)
assert len(wire.encode("utf-8")) == packet["used_bytes"] <= 8192
print(packet["status"], len(packet["knowledge"]), packet["requires_review"])
```

`MemoryStore` 只读；`KnowledgeStore.compile(..., apply=True)` 才显式发布；`ClaimStore` 是新声明库（`record` / `brief` / `claims`）。三者都不调用模型。

### 8. 多 Agent 并发、备份与删除

写入会获取跨进程写锁；超过超时时间会明确返回 `ClaimStoreBusy`，不会静默覆盖较新的版本。

```bash
claim backup --store /path/to/claims.jsonl
claim restore --from /path/to/backups/claims-....jsonl --store /path/to/claims.jsonl --yes
claim redact clm_... --store /path/to/claims.jsonl --yes
claim delete clm_... --store /path/to/claims.jsonl --cascade --yes
```

备份是可校验的规范快照与 manifest。脱敏会保留不含正文的墓碑和取代链；删除会移除记录，被引用时必须加 `--cascade`。两者默认写入审计记录和改动前的明文备份，可用 `--no-backup` 关闭；脱敏后的 Claim 不再进入简报和 RAG 证据。[数据安全](docs/data-safety.md)。

<a id="limits"></a>
## 六、能力边界，不藏在口号里

- 这是以 Skill 与 MCP 暴露的本地记忆与知识组件——**不是自主 Agent，也不是真伪检测器**。
- 台账自身的检索是**词法检索**，不是向量搜索。可选的 RAG adapter 可以提供原文片段，但每条证据都必须解析到 claim，并接受同一套状态策略。
- 语义复核仍由宿主或人完成；冲突检测只能摊开疑似，**不能判定语义矛盾**。
- scope 是结构性标签，不是强制的环境隔离；expiry 是对可选时间戳的读取期政策，**不是自动删除**。
- `--at` 重建的是账本当时**记录了什么**——不是对"现实世界当时是什么"的宣称。
- 不提供托管 Web UI：本地 `claim demo` 只是同一存储上的一次性单用户视图。不内置模型服务、不提供通用压缩钩子、不做跨机同步。
- 记忆正文是不可信数据：不能绕过损坏检查，不可提交私人会话，恢复包里的内容是资料不是指令。
- 旧多文件渲染器不是跨层事务。

[架构](docs/architecture.md) · [设计与致谢](docs/wiki-design.md)。

## 七、文档与贡献

| 我想… | 阅读 |
| --- | --- |
| 看完整文档地图 | [Documentation](docs/README.md) |
| 理解 v2 治理式记忆的设计、决策与竞品审计 | [v2 设计文档](docs/design-v2.zh-CN.md) |
| 运行交互式演示 | [演示指南](docs/demo.md) · [界面重构笔记](docs/demo-redesign.zh-CN.md) · [产品落地页](https://anhao1314.github.io/ClaimLedger/) |
| 融合 RAG 或向量检索 | [RAG 证据适配](docs/rag.md) · [状态过滤基准](benchmarks/rag/results.md) · [演示证据索引](examples/rag/evidence.jsonl) |
| 多 Agent 并发写入、备份、脱敏或删除 | [数据安全](docs/data-safety.md) |
| 接入一个数据来源 | [Context Gateway](docs/context-gateway.md) · [摄入与迁移](docs/ingestion.md) |
| 在宿主 Agent 中执行蒸馏 | [高级宿主工作流](SKILL.md) · [蒸馏规则](references/distillation-schema.md) |
| 复核设计、验证与迁移 | [重构设计](docs/refactor-design.md) · [验证台账](docs/verification.md) · [Skill 指南](docs/skill-first.md) · [Changelog](CHANGELOG.md) |

公开问题请提供合成复现材料，不要提交私人会话或凭据。[Contributing](CONTRIBUTING.md)

```bash
python -m unittest discover -s tests -v
python tools/build_brand_assets.py --check
python tools/verify_docs.py
```

## License

[MIT](LICENSE).