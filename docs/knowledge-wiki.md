# Knowledge Wiki 0.3.0

将已有原子记忆编译成有引用、有版本、可失效的主题知识页。吸收 LLM Wiki 的持续维护思想，
不引入第二套事实权威，不改变原来的 v2 记忆格式。

**先记住边界：软件检查引用、字面摘录、范围和状态，不检查归纳是否正确。**
`prepare` 生成的是确定性摘录草稿；真正的综合写作由宿主 Agent 或人完成。
不需要模型密钥，也没有隐藏的远程模型调用。

## 从已安装版本开始

在仓库中创建并激活虚拟环境，运行 `python -m pip install .`。从旧版本更新时，应在更新仓库后重新安装。
当前包的 `chat-distiller --version` 应显示 `0.10.0`；Knowledge Wiki 本身在 0.3.0 引入。尚未发布 PyPI，不能把同名索引包当作本项目已验证版本。

已有 v2 vault 可以直接使用。首次体验先按 [README](../README.md#quick-start) 生成临时演示记忆，
不要把新身份覆盖到真实知识库。接着复用该教程里的 `DEMO_DIR`：

```bash
chat-distiller wiki prepare --vault "$DEMO_DIR/vault" --topic database --query database > "$DEMO_DIR/proposal.json"
chat-distiller wiki compile --vault "$DEMO_DIR/vault" --proposal "$DEMO_DIR/proposal.json"
chat-distiller wiki compile --vault "$DEMO_DIR/vault" --proposal "$DEMO_DIR/proposal.json" --apply
chat-distiller wiki search --vault "$DEMO_DIR/vault" --query database
chat-distiller wiki recover --vault "$DEMO_DIR/vault" --query database --max-bytes 8192
chat-distiller wiki export --vault "$DEMO_DIR/vault" --out "$DEMO_DIR/wiki-view"
```

第二条只是校验，不落库。第三条才发布。第一次准备的草稿逐条摘录记忆，适合验证流程；
在第二条之前，可以让宿主把草稿整理成综合知识页，遵循 [提案契约](../references/knowledge-schema.md)。
不要修改快照指纹、查询或范围来掩盖过期信息和争议。

导出目录中有 `index.md`、知识页、`log.md` 和最后写入的 `manifest.json`。
可以用普通 Markdown 阅读器或 Obsidian 打开。导出是某次时点的静态视图，不会自动同步；
检索从经过校验的结构化状态读取，不从导出的 Markdown 读取。

## 一次跑完整的可检查演示

从仓库根目录、已经安装本包的 Python 环境运行：

```bash
DEMO_PARENT="$(mktemp -d)"
python tools/wiki_demo.py --out "$DEMO_PARENT/run"
```

脚本通过真实 CLI 执行 16 个步骤：原子记忆准备、知识草稿、宿主撰写的综合提案、只读校验、发布、
当前/历史检索、有界恢复、导出、源记忆更新、旧页失效、原子记忆回退、重新编译、旧版本检查、再次导出。
输出目录保留每一步原始 JSON、可修改的提案、两个 Wiki 导出和验证总结。

综合示例内容位于 [synthesis.json](../examples/wiki/synthesis.json)，是开发过程中编写的合成演示。
脚本不调用模型；它演示宿主提供提案的接口，不测量模型自动综合能力。刷新阶段使用确定性摘录草稿。

## Python 接口

```python
from chat_distiller import KnowledgeStore, serialize_packet

wiki = KnowledgeStore("/absolute/path/to/existing-vault")
proposal = wiki.prepare("database", "database", title="Database architecture")
preview = wiki.compile(proposal)  # 只读验证
receipt = wiki.compile(proposal, apply=True)  # 明确发布
page = wiki.get("database")
hits = wiki.search("database")
packet = wiki.recover("database", max_bytes=8192)
assert len(serialize_packet(packet).encode("utf-8")) == packet["used_bytes"] <= 8192
health = wiki.status()
```

同一 `topic` 只对应一个稳定 `kn_` 身份，修改标题不改变身份。不同 topic 之间不自动做语义去重。
内容完全相同的重复提交返回 `no_change`，不增加日志和版本。其他更新增加页版本和全局 Wiki 修订号。

## 维护知识，而不是不断追加摘要

原子记忆发生变化后：

```bash
chat-distiller wiki status --vault /path/to/vault
chat-distiller wiki prepare --vault /path/to/vault --topic database --query database > proposal.json
# 宿主读取草稿、已有页和相关来源，更新综合结论并保留未决事项。
chat-distiller wiki compile --vault /path/to/vault --proposal proposal.json
chat-distiller wiki compile --vault /path/to/vault --proposal proposal.json --apply
```

`prepare` 保留该主题已有且仍有效的依赖范围，并纳入查询匹配的新记忆和显式替代目标。
每条选中记忆都必须在至少一条 claim 中出现；已过期或有争议的支持不能标成 current。
同一范围内的多条记忆可以合并为一条综合 claim，但必须保留它们各自的引用。

需要历史调查时，`search/recover --intent historical` 允许历史 claim；默认当前模式排除历史 claim，保留争议。
**知识页 stale 与 claim historical 是两种状态**：前者表示这份综合没有按最新输入复查，后者表示一条被明确标记的历史记忆。
历史查询也不会默认启用 stale 页。检查旧页必须显式执行：

```bash
chat-distiller wiki get --vault /path/to/vault --topic database --revision 1 --allow-stale
```

旧版中保留当时的提案和支持记忆快照。这是留存当时发布的结果，不是从原始对话重新运行 LLM 得到完全相同的总结。

## 新鲜度与正确性

每页记录完整原子源快照的 SHA-256。任何源变化，包括新增、不相关内容更新和状态变化，都会使旧页 stale。
这样不会遗漏“新加入的矛盾没有出现在旧依赖列表里”的情形，但代价是无关变动也会要求复查。
`status` 区分已引用依赖变化和源变化待复查；本版不宣称精细的语义依赖失效分析。

默认知识检索排除 stale 页。分层恢复尝试新鲜主题页，装不下或没有新鲜页时可回退到原子记忆，并报告排除/省略情况。
原子回退不保证某主题的全部争议都已覆盖。`ready` 仍只表示有资料装得下，不表示答案正确或任务已完成。

即使声称火星上有数据库，只要附有真实存在的记忆摘录并标注 synthesis，结构校验仍可能通过。
测试专门保留了这个反例。所有 synthesis/inference 都保持 `requires_review`，引用不是事实证明。
字面摘录核对的是原子卡片正文，不是自动核对所有原始转录；进一步追溯须由宿主读取来源。

## 存储、故障与边界

新增状态位于 `<vault>/对话沉淀/.chat-distiller/wiki/state.json`。页版本、稳定身份、依赖快照和编译日志
共同保存在一个带校验和的 JSON 中，同目录临时文件刷盘后替换该文件。Markdown 不是第二份权威。

发布使用独占 `writer.lock` 和乐观修订号校验。旧提案不能覆盖新页；不会自动偷取遗留锁。
中途进程退出可能留下锁和临时文件。必须先确认没有写入进程，再备份并检查状态；不要在活跃写入时移除锁。
已有 Wiki 目录缺失 `state.json` 会报错，不会自动重置为空库。

替换前失败保留旧权威文件；替换后目录同步或锁清理失败会抛出 `CommitUncertainError`，CLI 标明
`commit_may_have_succeeded`。先检查版本，再决定重试。不要把这类错误当作“肯定没写入”。

这是编译状态单文件的发布协议，不是跨原子记忆 renderer 和 Wiki 的事务。更新原子记忆和编译 Wiki 应串行执行。
已验证异常和进程终止注入，没有做硬件断电测试；不防御恶意文件系统竞争、伪造全套哈希或网络文件系统异常。

单提案最多 100 张卡片、100 条 claim、2 MiB；整库权威快照上限 64 MiB。超出限制会拒绝，
不是大规模数据库或无限历史归档。引擎不自动执行知识里的命令，也不提供提示注入防御。

## 实验与来源

[调研与设计决定](wiki-design.md) · [提案契约](../references/knowledge-schema.md) ·
[逐项工程实验](../benchmarks/wiki/results.md) · [原始实验 JSON](../benchmarks/wiki/results.json)。

旧的检索 benchmark 保持不变。新的 CompileBench 只验证生命周期、引用和预算行为，不能解释为真实用户效果、
LongMemEval 成绩或模型综合准确率。当前交付没有 MCP、向量搜索、Web 管理端或原生会话自动抓取。
