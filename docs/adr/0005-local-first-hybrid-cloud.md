# ADR-005: 本地优先、混合云端

**日期**: 2026-06-10  
**状态**: 已采纳  
**决策者**: 用户  

---

## 背景

MirrorTalk 的 Embedding 和 Rerank 服务需要向量化和重排序能力。两种路线：纯本地模型 vs 纯云端 API。

原 CipherTalk 由于 Node.js 生态限制，Embedding 和 Rerank 均依赖外部 API Key。Python 生态支持本地运行。

## 方案对比

### 纯云端
Embedding 走 OpenAI/SiliconFlow API，Rerank 走 Cohere/Jina API。  
优点：零模型下载、启动快。缺点：按量计费、聊天内容上传云端。

### 纯本地
`sentence-transformers` + `FlagEmbedding` 本地推理。  
优点：零费用、零隐私泄露、离线可用。缺点：首次需下载 ~3GB 模型，内存占用 4-6GB。

### 本地优先、混合云端 ✓
启动时尝试加载本地模型。成功 → 全本地。失败（显存不足、模型下载中断）→ 自动降级到用户配置的云端 Provider。

## 决策

**采纳本地优先、混合云端。**

本地默认模型：
- Embedding: `BAAI/bge-m3`（via `sentence-transformers`，2GB）
- Rerank: `BAAI/bge-reranker-v2-m3`（via `FlagEmbedding`，1GB）

云端回退：统一走 Provider 模式配置（和 LLM 共用同一套 Provider）。

## 影响

- 用户不需要配置 Embedding API Key（本地默认可用）
- 首次启动需下载模型的等待提示
- 本地模式运行后聊天内容完全不出机器
- 性能：本地 bge-m3 在 MPS/CUDA 上比云端 API 更快
- 面试亮点：全本地向量化 + 灵活降级策略
