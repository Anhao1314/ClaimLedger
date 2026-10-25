# ClaimLedger v2 框架设计：治理式记忆（Governed Memory）

状态：设计稿 v1（2026-10-25）。本文档是 v2 改造的唯一设计蓝本，实施分阶段见文末。

## 0. 定位

**一句话**：机器可以提案，状态机负责摊开，拍板权和审计留给拍板者。

- **不做"又一个记忆系统"，做任意记忆系统之上的治理层。** 记忆引擎（Hindsight、deja-vu、agent-memory……）负责"记住"；本框架负责"**什么才算数**"。claim 层是权威，belief 层可对接任意记忆引擎的产出——可插拔，不对抗。
- CoALA 坐标系：受治理的**语义记忆**库 + 字节预算的**工作记忆**装载器（brief 即 loader）。
- 思想谱系：Doyle 1979 的 TMS（真值维护）——记录理由、依赖导向回溯——把其中不可解的"自动算子"替换为**人类/宿主显式拍板**，即"人裁决的 TMS"。
- 与既有系统的差异：主流记忆框架全部由机器自动裁决记忆变更；本框架的空白地带是**治理层**——冲突拒绝写入、显式拍板、全程可审计。竞品核查（2026-10，见 §12）确认此定位未被占据。

## 1. 设计原则（继承与修订）

继承（不动摇）：

1. **单一权威**：`claims.jsonl` 只增不删，是唯一真相；brief / wiki / 索引 / 导出全部是可丢弃、可重建的视图。
2. **确定性核心**：核心不调模型、不联网、零第三方依赖；结构完整性（引用可查、状态如实、预算可验证）由代码保证。
3. **字节预算硬契约**：读取侧的预算是可验证数字；v2 新增**注意力预算**（评审队列也有预算与过期）。
4. **本地所有权**：单文件、无常驻进程、数据不跟厂商走。

修订（v2 的立场变化）：

5. 旧立场"拒绝语义" → 新立场"**语义可提案，不可拍板**"。向量与 LLM 允许进入**提案层**，其输出永远是带溯源的提案或标记，不是权威写入。
6. 旧立场"零自动写入" → 新立场"**自动捕获进信念层，拍板进决定层**"。自动与安全不再对立，而是分层授权。

## 2. 三层认知写入（核心新增）

```
belief 信念层      自动、零门槛、冲突合法、机器可写
   │  propose（语义/词法批量，发生在 sync 时，不在 record 时）
   ▼
proposal 提案层    机器起草的候选操作，带证据与理由，有过期时间
   │  ratify（人 / 显式授权的宿主拍板，一次确认）
   ▼
claim 决定层       冲突拒写、状态治理、全程审计（现状保持）
```

### 2.1 belief（信念）

- **谁写**：双通道捕获——**会话边界自动**（sync 时把转录中的观察批量落入 belief 层，采纳 agent-memory 的现实主义：不等 agent 记得去记）+ **决策时刻手动**（宿主 agent 随手 `belief_append`）。Context Gateway 暂存的转录片段同样落此层。
- **保证**：只做 schema 校验，不做任何冲突检查——两个 agent 持相左观点是正常状态，不是异常。
- **用途**：`claim context` 检索的证据来源；提案层的数据原料。**永不进入 brief**。
- **生命周期**：可被 consolidation（见 §7）有损综合；被提案引用后标记 `consumed_by`。

```json
{
  "id": "blf_9f2c",
  "layer": "belief",
  "agent": "codex",
  "content": "用户说：先在预发环境试 PG，跑一周再定",
  "source": {"connector": "doubao", "session": "s_123", "turn": 41},
  "recorded_at": "2026-10-25T03:12:00Z",
  "confidence": 0.6,
  "consumed_by": []
}
```

### 2.2 proposal（提案）

- **谁写**：提案生成器（批量、sync 时运行）。生成器有两个实现档位：**词法档**（零模型，复用现有 find_conflicts 的批量版本）与**语义档**（可选插件：向量相似 + LLM 判定，输出仅限提案）。
- **操作空间**（借鉴 Mem0 的四操作，但全部降格为提案）：`ADD` / `SUPERSEDE` / `DISPUTE` / `MERGE`。
- **硬规则**：提案**永不自动应用**；每条提案带 `expires_at`（默认 14 天）——评审队列遵守注意力预算，过期提案进审计归档而非静默堆积。
- **溯源**：记录生成器身份（模型 id / 词法版本）、置信度、证据 belief ids。

```json
{
  "id": "prp_4a71",
  "layer": "proposal",
  "action": "SUPERSEDE",
  "target": ["clm_873e"],
  "draft": {"text": "数据库改为预发验证一周后再定，当前仍用 SQLite", "topic": "database"},
  "evidence": ["blf_9f2c", "blf_88d1"],
  "rationale": "两条信念显示 PG 决定被推迟，与现行声明冲突",
  "generated_by": {"generator": "lexical-v1", "confidence": 0.71},
  "status": "pending",
  "expires_at": "2026-11-08T00:00:00Z"
}
```

### 2.3 claim（决定）

保持 v1 语义（冲突拒写、显式替代/争议），数据模型升级见 §3。

### 2.4 信任分级（接入配置）

- 默认：`ratify` 只属于人。
- 可选：宿主 agent 经显式信任配置获得 ratify 权（power user 场景），但**每次 ratify 写审计条目**（谁、依据哪条提案、何时）。
- MCP 工具面新增：`belief_append`（永远安全）、`claim_propose`（永远安全）、`claim_ratify` / `claim_resolve`（受信任分级控制）。agent 获得安全写入通道后，"写入纪律"从假设变成架构属性。

## 3. 声明数据模型 v2

在 v1 字段（text / topic / tags / status / supersedes / source / quote / session / scope）之上：

### 3.1 双时间轴（借鉴 Zep/Graphiti，四时间戳）

| 字段 | 含义 | 轴 |
|---|---|---|
| `valid_from` | 现实世界生效起点 | 有效轴 |
| `valid_to` | 现实世界失效点（开放 = null） | 有效轴 |
| `recorded_at` | 系统录入时间 | 录入轴 |
| `expired_at` | 记录退役时间（= superseded 发生时刻） | 录入轴 |

- 旧 `expires_at` 语义保留为"读取期策略"，等价于 `valid_to` 的懒声明。
- **点时查询**：`claim brief --at 2026-03-01` 回答"三月一日当时什么算数"；`--now`（默认）回答"现在什么算数"。两条轴分开，"当时认为的"与"事实上当时的"不再混为一谈。

### 3.2 双层边

| 边 | 生成 | 用途 | 触发 |
|---|---|---|---|
| `depends_on`（硬依赖） | 人拍板 | 前提坍塌回溯 | 依赖目标被替代/过期 → 本条**派生标记** `unmotivated`（待复审） |
| `related_to`（软关联） | 机器提案、人确认（或低信任自动） | 检索增益（A-Mem 式结构召回） | 无副作用 |

关键设计决策：`unmotivated` **是派生标记而非存储状态**——能从依赖边推导的事实不落盘，贯彻单一权威。派生标记在 brief 中以"待复审"区块出现，不冒充现行。

### 3.3 状态机 2.0

```
             record/ratify
   (草稿) ────────────────▶ current 现行
                              │ ▲        │ supersede
                    dispute   │ │resolve │
                              ▼ │        ▼
                        disputed ◀──▶ superseded 已过期
                       有争议
```

- 存储状态仍只有三个：`current` / `disputed` / `superseded`（保持简单）。
- **新增闭合转移** `resolve`（v1 的最大缺口）：争议可收场为三种结局——
  - `claim resolve <dispute_group> --supersede clm_x`（一方胜出）；
  - `--synthesize "综合结论…"`（生成一条新现行声明，引用全部立场）；
  - `--withdraw`（争议撤销，恢复原状）。
- 争议带结构：同一 `dispute_group` 的成员互为立场，每个立场可挂 belief 证据与归属人。

### 3.4 完整示例

```json
{
  "id": "clm_45e9",
  "schema_version": 2,
  "text": "数据库改用 SQLite，PostgreSQL 方案废弃",
  "topic": "database",
  "status": "current",
  "valid_from": "2026-10-20T00:00:00Z",
  "valid_to": null,
  "recorded_at": "2026-10-24T15:09:18Z",
  "expired_at": null,
  "supersedes": ["clm_873e"],
  "depends_on": ["clm_11aa"],
  "related_to": ["clm_77bc"],
  "scope": "all",
  "source": {"connector": "claude-code", "session": "s_42", "quote": "…"}
}
```

## 4. 检索：状态进排序，退出门禁

- v1 的 current-only 硬过滤造成 Recall@5 1.00→0.92 的回归；v2 改为加权排序：

```
score(q, c) = lexical(q, c) × w_status(c | intent) × w_recency(c) × w_link(c)
```

- `intent`（now / then / at T）：宿主模型可给提示，否则用词法时间标记启发式；默认 now。
- `w_status`（intent=now）：current 1.0，disputed 0.6，superseded 0.2；intent=then：全 1.0，仅按有效区间过滤。
- `w_link`：从现行声明经 `related_to` / `depends_on` 可达者加成（结构召回）。
- 状态感知从"过滤"升级为"感知状态的排序"——目标：stale-hit 仍为 0，Recall@5 回到 1.0。

## 5. 语义服务契约（可选插件，永不当权威）

| 服务 | 输入 | 输出 | 禁止 |
|---|---|---|---|
| 冲突疑似 | 新信念 × 现行声明 | SUPERSEDE/DISPUTE 提案 | 直接写入 claim 层 |
| 关联建议 | 信念/声明 | related_to 提案 | 直接建边 |
| 依赖建议 | 信念/声明 | depends_on 提案 | 直接建边 |
| 简报润色 | 已渲染 brief | 自然语言版本（渲染产物） | 改动任何数据 |

契约条款：所有输出带生成器溯源与置信度；核心分发包**不含**任何插件，零依赖发行不受影响；插件的全部产物是提案/标记，可整体丢弃重建。

## 6. 记忆层级与注意力预算

- **热层**：current + disputed（brief 候选）。
- **温层**：superseded（检索可达，默认低权重）。
- **冷层（v2 后期）**：consolidation——把大量信念/旧声明有损综合为"季度综述"声明，**综合本身也是提案**，人拍板后生效；保留溯源链（综述声明 depends_on 全部原料 id 的压缩集）。
- **注意力预算**：待审提案队列有字节与条数上限；超限触发"最老过期"策略并入审计——人的注意力被当作和上下文一样稀缺、需要预算的资源。

## 7. 评测契约（v2 的合格线）

1. **LongMemEval-S 切片突袭**（进行中）：**只报 KU / temporal / abstention 三个切片**，不进总分榜——总分战场已是 95%+ 的检索竞赛（deja-vu 公开 97.2% R@5），而这三块是状态策略的主场：检索型选手的索引里新旧答案并存、无人被失效，天然吃亏。叙事是"我们是唯一让过期答案**结构上**无法冒充现状的"。
2. **下游任务 A/B**：同一多会话任务，有无台账两条件——任务成功率、token 成本、**旧错误复活率**（终指标，对应系统的存在理由）。
3. **同切片竞品**：Mem0 / Letta / Zep 至少一家，同数据可比；总分对照直接引 deja-vu 公布数据。
4. 所有数字可复现：fixture 哈希 + 命令清单入 CI（沿用现有 evidence 工作流）。

## 8. 兼容与迁移

- **schema v1 → v2**：纯增量字段，v1 记录以默认值升级（`valid_from = recorded_at`，`valid_to = null`）；迁移是可校验的单向变换，写审计。
- 全部旧入口不变：`claim record/brief/claims/search/recall`、MCP、Skill、demo、`~/.chat-distiller`。
- 新增命令面：`claim belief` / `claim propose` / `claim review`（评审队列）/ `claim resolve` / `claim brief --at <T>`。
- demo 新叙事：**"换 Agent 续作"**作为主流程（豆包 → Codex 实景），术语中文化（现行/已替代/有争议/待复审/简报）。

## 9. 修订后的拒绝清单

仍拒绝：claim 层自动写入；语义输出当权威；两份真相；常驻进程与云同步（协议兼容的第三方同步器除外，主仓不做）。
不再拒绝：向量与 LLM（限定于提案层与渲染层）；有损综合（以提案 + 溯源压缩的方式引入）。

## 10. 实施阶段

| 阶段 | 内容 | 依赖模型 | 预期产出 |
|---|---|---|---|
| A 理论闭环 | dispute resolve、双时间字段、depends_on、派生标记、`--at` 点时查询 | 否 | 状态机闭合；temporal 类查询可答 |
| B 分层写入 | belief 层、提案层、词法档生成器、信任分级、MCP 新工具 | 否（词法档） | agent 获得安全写入通道 |
| C 检索升级 | 加权排序、intent、结构召回 | 可选 | Recall@5 回归消除验证 |
| D 评测 | LongMemEval 跑数、K2 端到端 A/B、竞品切片 | 是（评测用） | 可复现数字三组 |
| E 记忆层级 | consolidation、注意力预算、冷层 | 可选 | 规模化路径 |

阶段 A、B 均可零模型完成——理论的完整性不依赖任何模型，这是确定性核心立场的直接推论，也是本设计最重要的可验证声明。

## 11. 关键设计决策记录（ADR 摘要）

| 决策 | 选择 | 被否方案 | 理由 |
|---|---|---|---|
| 写入分层 | belief/proposal/claim 三层 | 单层自动（Mem0）或单层人审（v1） | Mem0 生产退缩证明全自动裁决贵且不稳；v1 证明纯人审靠自觉 |
| 时间模型 | 四时间戳双轴 | 单 created_at | Zep 生产验证；temporal 查询的必要条件 |
| unmotivated | 派生标记 | 存储状态 | 单一权威：能推导的不落盘 |
| 边分两层 | 硬依赖 + 软关联 | 单一语义链接 | 回溯需要可信赖的硬边，检索受益于廉价的软边 |
| 语义档位 | 词法档先行、语义档可选 | 直接上语义档 | 词法档让阶段 B 零模型可用，语义档变成增益而非前提 |
| 状态机 | 保持三态 + resolve 转移 | 扩展更多状态 | 状态越少越可验证；复杂性放进转移和派生标记 |

## 12. 竞品格局（2026-10 GitHub 核查）

| 项目 | 星数 | 定位 | 对本设计的意义 |
|---|---:|---|---|
| Hindsight（vectorize-io） | 53.5k | 仿生记忆：事实/经历/带置信度的信念/反思，从人类 approved/rejected 反馈学习，云级规模 | "信念带置信度"与 belief 层同构、反馈学习与 ratify 相邻——但反馈是学习信号，记忆仍归机器；无冲突拒写与状态生命周期 |
| OpenViking（volcengine） | 40.7k | 自进化上下文数据库，统一记忆+RAG+技能 | 平台级全家桶，全自动方向，无治理 |
| TencentDB-Agent-Memory | 29.9k | 团队级记忆中枢 | 团队/云端方向 |
| agent-memory（tigerless-labs） | 4.7k | Markdown 单一真相 + SQLite 可删缓存；会话边界自动写入；sleep-time 整合与遗忘 | 工程审美最接近（本地、零 key、多 agent）；其捕获触发（会话边界）与整合（阶段 E）已被本设计吸收；无治理 |
| deja-vu | 1.3k | 跨 coding agent 记忆，索引会话历史；公布 LongMemEval-S 97.2% R@5 | 使用场景重叠（跨 agent 续作）；证明总分榜已卷死，评测必须走切片突袭 |
| decision-ledger（Dupflo 等） | ≤6 | 决策时记录"能否守住立场"的 skill 实验 | 痛点被独立重复发现但无人做出引擎；定位真空的证据 |

**结论**：治理定位（冲突拒写 + 人拍板 + 状态生命周期 + 点时查询 + 依赖回溯 + 审计）未被任何严肃项目占据；周边能力（自动捕获、信念层、整合遗忘）已多家收敛，属 table stakes，不构成差异化。
