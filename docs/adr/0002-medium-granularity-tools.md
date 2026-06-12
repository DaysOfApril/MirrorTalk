# ADR-002: 中粒度工具设计

**日期**: 2026-06-10  
**状态**: 已采纳  
**决策者**: 用户  

---

## 背景

Agent 需要检索聊天记录和知识库。原 CipherTalk 暴露了三个检索工具（`search_messages`、`semantic_search`、`recall`），LLM 需要在关键词搜索、语义搜索、记忆搜索之间做选择，经常选错，需要在 prompt 中反复强调选错后的回退策略。

MirrorTalk 需要更简洁的工具面。

## 方案对比

### 方案 A：细粒度（3 个工具）
`search_messages`（关键词 FTS）、`semantic_search`（语义向量）、`recall`（知识库检索）。LLM 决策负担重。

### 方案 B：中粒度（2 个工具）✓
`search_messages`（搜聊天原文）和 `recall`（搜知识库）。每个工具内部自动做"关键词 + 向量 → RRF 融合 → Rerank"混合检索。LLM 只需判断"聊天还是知识库"。

### 方案 C：粗粒度（1 个工具）
单一 `search_memory`，内部同时搜聊天和知识库，返回融合结果。缺点：丢失聊天记录的时间线索和知识库的置信度线索——两者是本质不同的数据类型。

## 决策

**采纳方案 B：中粒度。**

工具集：
- `search_messages(query, time_range)` → 返回 `[{time, sender, excerpt, anchor}]`
- `recall(query)` → 返回 `[{content, confidence, importance, source_type}]`

两个工具内部均自动做混合检索（关键词 + 向量 → RRF → Rerank）。

## 影响

- LLM 只需做"该查聊天还是查知识库"这个简单判断，大幅降低选错概率
- 工具 description 更短，节省 system prompt token
- 聊天记录和知识库的返回格式各保留核心字段，不丢失信息
- 关于"语义搜索"的选型逻辑从 prompt 中移除，推给工具内部自动处理
