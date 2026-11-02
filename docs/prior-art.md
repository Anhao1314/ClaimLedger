# 文献核查：这个方向已经被占满

**日期** 2026-11-02
**方法** arXiv API 检索，关键词：agent memory + conflict / belief revision / knowledge conflict / superseded / stale / revocation / provenance / write governance。
**目的** 判断 ClaimLedger 的命题是否已经被回答。

---

## 1. 决定性的一篇

**Revoked but Still Authoritative: An Empirical Study of Revocation Enforcement in Agent-Memory Systems**
arXiv **2609.08258** · 2026-09-08

> 5 个记忆系统 × 9 个策略场景 × 9 个模型 × 6 种防御条件。
> 结论：没有任何系统默认执行撤销。只要撤销标签对检索层可见，失效事实就会被返回、排在替代事实之前，并让 agent 执行不安全动作。

本仓库原来的核心主张是“检索命中 ≠ 当前结论”。这句话在这里被以严格得多的方式证明了：那篇论文测到的是**动作层**，本仓库测的是检索指标，而且零模型调用。

## 2. 覆盖了设计稿全部方向的四篇

| 论文 | arXiv | 日期 | 覆盖 |
|---|---|---|---|
| Governed Persistent Memory (GPM) | 2608.12476 | 2026-08-12 | 可审计双时间轴状态机、source-bound admission、conflict isolation、retraction 后不可复活、fail-closed、3,600 例冻结基准 |
| MemTX | 2607.23929 | 2026-07-27 | “一次记忆写入不是一次信念提交”、写入分级、validate-and-commit、级联修复 |
| Revoked but Still Authoritative | 2609.08258 | 2026-09-08 | 撤销标签可见时仍不执行；9 模型 × 9 场景；测到动作层 |
| Memory, Know Your PLACE | 2610.25179 | 2026-10-18 | write-side state certification + read-side authorization |

逐条对照：

| 本仓库的概念 | 已被谁做 |
|---|---|
| 双时间轴 | GPM “auditable bitemporal state-transition model” |
| 三态状态机 | GPM “derived lifecycle state” |
| 冲突拒写 / fail-closed | GPM “conflict isolation” + “fail-closed release” |
| supersede 链不可复活 | GPM “non-revival after retraction or deletion” |
| `--at` 时点重建 + digest | GPM “exact claim closure over a fresh view at one verified head” |
| belief → claim 分层 | MemTX “a memory write is not a belief commit” |
| 写时治理 vs 读时守卫 | PLACE “write-side state certification + read-side authorization” |
| 多主体共享记忆 | GateMem（arXiv:2606.18829） |

## 3. 同一子领域的其余工作

| arXiv | 日期 | 内容 |
|---|---|---|
| 2605.06527 | 2026-05-07 | STALE：agent 能否知道记忆已失效 |
| 2606.27472 | 2026-06-25 | Supersede：memory-update gap |
| 2609.03340 | 2026-09-03 | Fresh Memory, Stale Plans：derivation currency |
| 2610.22209 | 2026-10-15 | Beyond Downstream QA：记忆评测不该只看 QA |
| 2607.02579 | 2026-06-30 | When Not to Write Memory |
| 2606.18829 | 2026-06-17 | GateMem：多主体记忆治理基准 |

## 4. 时间线

```
2026-05  STALE
2026-06  GateMem / Supersede / When Not to Write Memory
2026-07  MemTX
2026-08  GPM（本仓库设计稿的超集）
2026-09  Revoked but Still Authoritative
2026-09-13  ClaimLedger 建库          ← 晚于上述全部
2026-10  PLACE / Beyond Downstream QA
2026-10-25  v2 设计稿（§12 声称定位未被占据）
```

## 5. 为什么 §12 的结论是错的

`design-v2.zh-CN.md` §12 做的是 GitHub 核查：星数、产品定位。它回答“有没有人做成了产品”，没有回答“有没有人做完了研究”。

**检索面选错了。** 在研究相邻的方向上，先验知识在论文里。

## 6. 判定

研究命题终止，仓库降级为工程实现。见 [DECISION.md](DECISION.md)。

[返回 README](../README.md)