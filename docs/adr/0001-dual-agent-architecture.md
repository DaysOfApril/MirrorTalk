# ADR-001: 双 Agent 独立图架构

**日期**: 2026-06-10  
**状态**: 已采纳  
**决策者**: 用户  

---

## 背景

MirrorTalk 涉及两个对话场景：
1. 用户直接与虚拟好友聊天
2. 替用户回复真实好友的消息

这两个场景的角色、权限、工具集、人格加载逻辑均不相同。

## 方案对比

### 方案 A：单 Agent 双向
一个 Agent 同时扮演两个角色，通过 context 切换身份。优点：简单、共享记忆。缺点：角色混淆风险高、风格污染、调试困难、虚拟好友不该看到用户画像。

### 方案 B：双 Agent 独立图 ✓
两个独立的 LangGraph StateGraph，各司其职。共享基础设施（memory service、embedding、rerank），但图结构、system prompt、工具集各自独立。FastAPI 层负责路由。

## 决策

**采纳方案 B：双 Agent 独立图。**

两个 Agent：
- **虚拟好友图** (`friend_graph`)：加载好友风格标签、有权访问知识库中的好友相关事实
- **用户替身图** (`persona_graph`)：加载用户替身画像 + 综合替身、有权访问全量知识库、独享 `update_profile` 和 `query_profile` 工具

## 影响

- 每个 Agent 的图结构简单清晰，面试展示易于理解
- 信息边界天然隔离：虚拟好友看不到用户画像
- 前端两个独立页面，各自路由到对应 Agent 图
- 共享服务（memory、embedding、rerank）抽为公共模块
