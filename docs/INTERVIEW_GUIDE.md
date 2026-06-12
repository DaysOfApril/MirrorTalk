# MirrorTalk — 面试全案

> 一份文档覆盖面试官对项目的所有追问。从数据到上线，从架构设计到工程细节。
> 项目定位：AI 虚拟好友系统（RAG + Agent + 全栈落地）

---

## 一、项目概览

### 一句话
上传真实聊天记录 → LLM 提取人格画像 → 构建双 AI Agent →「虚拟好友」可与之对话、「用户替身」可替你回复消息。支持多模态文档摄入、A/B 实验、Agentic RAG 查询规划。

### 两个核心场景

| 场景 | 页面 | 原理 | 交互 |
|------|------|------|------|
| 好友聊天 | /friend-chat | 用真实好友的聊天记录构建其 AI 分身，用户与之对话 | 输入框 → SSE 流式回复 |
| 替身回复 | /persona-reply | 用"你在好友面前的发言"构建你的分身 → 粘贴好友消息 → AI 以你的口吻回复 | 粘贴消息，一键复制 |

### 为什么值得讲

- **有真实痛点**：解决"朋友去世后怎么办"、"社恐不知道怎么回消息"
- **技术栈完整**：RAG + Agent + LLM + 向量DB + 流式，全部落地
- **工程深度够**：双 Agent 隔离、多层安全、混合检索、A/B 实验、Agentic RAG —— 面试官最爱追问的点全在里面

---

## 二、技术栈

| 层 | 技术 | 用途 |
|----|------|------|
| 框架 | FastAPI + LangGraph + LangChain | API 服务 + Agent 状态机编排 |
| LLM | OpenAI / DeepSeek / Qwen (Provider 工厂) | 对话生成、画像提取、查询规划 |
| Embedding | BGE-M3 (本地 SentenceTransformers) / text-embedding-3-small (云端) | 文本向量化 |
| 向量 DB | ChromaDB (本地持久化, cosine 度量) | 语义相似搜索 |
| 结构化 DB | SQLite + FTS5 + WAL 模式 | 关键词检索 + 持久化 + 全文索引 |
| Rerank | BGE-reranker-v2-m3 (本地 FlagEmbedding) / 云端 API | 检索结果精排 |
| 分块 | 自研 TextChunker（递归字符 + token 计数 + 父-子块追溯） | 文档分块 |
| 安全 | 三层 Guard（正则 L1 + Embedding L3 + LLM Review） | 注入检测、身份泄露防护、人设一致性 |
| 流式 | SSE (Server-Sent Events) + astream_events | 逐 token 打字机效果 |
| 前端 | React + Vite + TypeScript + React Router | 六页面 SPA |
| 测试 | pytest (20 个测试、独立临时DB) | 记忆/安全/分块/缓存/死循环检测 |
| 实验 | 一致性哈希 A/B 分流 + SQLite 事件采集 | 流量实验、转化率对标 |

---

## 三、全链路数据流

### Flow 1: 上传文档 → 画像构建 → 向量化索引

`
用户
  │ POST /api/personas/import { persona_id, name, messages[] }
  ▼
routes.py:import_persona()
  │
  ▼
profile_builder.py (三步 Pipeline)
  │
  ├─ Step 1: extract_atomic_facts()   → LLM 批量 (batch=50) 提取原子事实
  │    输出: [{type: "profile|fact|relationship", content}] → SQLite memory_items
  │
  ├─ Step 2: extract_style()          → LLM 分析 5 维度
  │    personality / catchphrases / sentence_style / emoji_style / tone
  │    → personas.style_json
  │
  └─ Step 3: estimate_ocean()         → 从标签推测大五人格
        (开放性/尽责性/外向性/宜人性/神经质)
        → personas.ocean_json
  │
  ▼ 返回给前端「画像构建完成」
  │
  ⏳ 异步 embed_texts_and_index()
     ├─ embed_texts() → BGE-M3 / OpenAI
     └─ ChromaDB.upsert(ids, embeddings, metadatas, documents)
`

### Flow 1.5: 多模态文档摄入（新增）

`
POST /api/documents/upload { file, persona_id }
  → tmp 存储
  → document_parser.parse_document() 按扩展名分发:
     ├─ .txt/.md  → 直接读取
     ├─ .pdf      → PyMuPDF(fitz) / pdfplumber 回退
     ├─ .docx     → python-docx
     └─ .png/.jpg → easyocr 本地OCR / LLM Vision 回退
  → TextChunker.chunk_text()  递归字符分块
  → insert_memory()           → SQLite + FTS5 全文索引
  → embed_texts_and_index()   → ChromaDB 向量索引
  → 绑定 persona_id           → knowledge_persona 关联系
  → 清理临时文件
`

### Flow 2: 发送消息 → 收到回复（Agentic RAG 版本）

`
用户输入消息
  │ POST /api/chat/friend/stream (SSE)
  ▼
routes.py:chat_friend_stream()
  │ 1. 加载好友画像
  │ 2. 创建/续用对话
  │ 3. 语义缓存查找 (cache_lookup) → HIT 直接返回
  ▼
friend_graph.astream_events()
  │
  ├─ ★ planner_node（新增 Agentic RAG）
  │   plan_query(): LLM 分析意图 → 四种策略:
  │   ├─ direct      : 问候/闲聊，跳过检索
  │   ├─ single      : 单事实查询，agent 工具调用
  │   ├─ multi_hop   : 复杂 → 拆子查询 → 去重聚合 → 注入上下文
  │   └─ reflection  : 先搜后追问
  │
  ├─ agent_node (LLM 推理 + Tool Calling)
  │   System Prompt = 人设注入 + 工具列表
  │   LLM 决定: 直接回复 或 调用工具
  │
  ├─ should_continue (路由)
  │   ├─ 有 tool_calls + 死循环检测(连续3次相同指纹) → guard
  │   ├─ 有 tool_calls → tools
  │   └─ 无 tool_calls → guard
  │
  ├─ tools_node (工具执行)
  │   ├─ recall    : 混合检索 (FTS5 + Vector → RRF → Rerank)
  │   ├─ remember  : 写入新记忆
  │   ├─ query_sql : SQL 查询 (需先 unlock)
  │   └─ 超时保护 + 指纹追踪 + SQL 门控
  │
  ├─ guard_node (三层安全)
  │   ├─ L1: Prompt Injection 检测
  │   ├─ L1: 输出安全 (身份泄露 + 角色崩坏)
  │   └─ L3: Persona 一致性 (embedding 相似度比对)
  │
  ├─ review_node (LLM 回答审核)
  │   检查: Hallucination / 身份泄露 / 风格匹配
  │   不通过 → 追加修正说明
  │
  └─ END
      ⬇️ SSE 流式逐 token:
      data: 你
      data: 好
      data: 啊
      data: {"type":"end","data":{"conversation_id":"xxx","reply":"你好啊"}}
      ⬇️ 写入语义缓存 (cache_store)
`

---

## 四、核心模块详解

### 4.1 混合检索: FTS5 + Vector → RRF → Rerank

**文件**: services/memory.py

`
recall(query)
  ├─ _fts_search()          SQLite FTS5 MATCH (附带 LIKE 降级)
  ├─ _vector_search()       ChromaDB query (cosine, source 权限过滤)
  ├─ _rrf_fusion()          Reciprocal Rank Fusion
  │    score = Σ wᵢ × 1/(k + rankᵢ + 1)
  │    参数 rrf_k=60, rrf_weight_fts=1.0, rrf_weight_vector=1.0
  └─ _rerank_items()        BGE-reranker-v2-m3 / 云端 API
       失败降级 → RRF 分数排序截断
`

**面试话术**："我用的是 RRF 融合而非简单的 concatenation 取 top-K。好处是不需要调分数归一化，两个异构信号直接按排名融合。k=60 偏保守，适合长尾记忆场景。Rerank 失败时自动降级到 RRF 分数截断，不丢查询。"

### 4.2 分块策略: TextChunker

**文件**: services/chunking.py

`
三层设计:
  1. 段落级粗切 → 按空行切分，保留完整语义段落作为父块
  2. 递归字符分块 → 超长段落用分隔符优先级 [\n\n, \n, 。, ., !, ?, ，, ,] 递归切割
  3. 语义边界检测 → 预留 embedding 相似度检测语义漂移点

关键特性:
  - token 计数 (tiktoken cl100k_base)，非字符数
  - 父-子块追溯: chunk_to_parent[i] → 检索后可用 get_parent_context() 补全
  - 默认 chunk_size=512 tokens, overlap=50
`

**面试话术**："分块不只是 langchain 的 RecursiveCharacterTextSplitter，我加了两层：一是 token 计数而非字符数，适配不同模型的真实上下文窗口；二是父-子块追溯——检索命中子块后可以回溯到父块拿到完整段落，解决 chunk 割裂语义的问题。"

### 4.3 双 Agent 架构

| Agent | 文件 | 工具 | 权限 |
|-------|------|------|------|
| 虚拟好友 (friend) | gents/friend_graph.py | recall, remember, query_sql | 只看 friend_speech + shared + external_file |
| 用户替身 (persona) | gents/persona_graph.py | recall, remember, query_profile, update_profile, query_sql | 所有 source |

`
两者共享:
  - 同一个 LangGraph 拓扑: planner → agent → tools ↔ agent → guard → review → END
  - 同一个工具门控机制: query_sql 需先用 recall/remember 解锁
  - 同一个安全检测: 三层 Guard + LLM Review
  - 同一个上下文压缩: compress_messages() 保留最近 4 轮
`

**面试话术**："为什么是双 Agent 而不是一个 Agent 切换 System Prompt？因为数据隔离。虚拟好友只能访问好友说过的话和共享知识，替身 Agent 能看到用户自己的发言和画像。权限在 recall 检索的 where 条件里硬控，不是靠 Prompt 提示。"

### 4.4 三层安全体系

**文件**: services/safety.py + services/review.py

`
L1: 零成本正则层
  ├─ 注入检测: ignore.*instruction / forget.*prompt / base64|hex|rot13
  ├─ 输出安全: 身份泄露关键词 (pinyin 编码防误杀)、角色崩坏模式
  └─ 扣分机制: 身份泄露 -0.4, 角色崩坏 -0.2, 过短 -0.2, 过长 -0.1
      passed = penalties < 0.5

L2: LLM 审核层 (review_node)
  ├─ 结构化的审核 Prompt: Hallucination / identity_leak / style_mismatch / missing_citation
  └─ 不通过 → build_correction() 追加修正说明

L3: Embedding 一致性
  ├─ score_consistency(): 回复向量 vs 人设标签向量 cosine 相似度
  └─ threshold=0.70 (可 calibration)
`

**Agent 运行态保护** (services/guards.py):
- **死循环检测**: 连续 3 次相同工具调用指纹（MD5(name+args)）→ 强制 guard
- **工具超时**: recall 60s / query_sql 120s / default 60s
- **SQL 门控**: query_sql 需先执行 recall/remember 才能使用（防越权）

**面试话术**："安全设计是纵深防御思路：第一层正则几乎是零延迟，命中高风险直接阻断；第二层 LLM review 做 semantic 级别审核；第三层用 embedding 做无监督的一致性评分。生产环境的话，L3 embedding 可以在标注集上做 calibration 找个最优 threshold。"

### 4.5 语义缓存

**文件**: services/semantic_cache.py (ChromaDB 持久化) + services/cache.py (内存快速查找)

`
两层设计:
  内存层 (cache.py):
    - cosine 相似度 ≥ 0.95 → 直接返回
    - TTL 3600s, 内存 dict
    - 适合高频相同/相似问题

  持久层 (semantic_cache.py):
    - ChromaDB collection "semantic_cache"
    - 跨进程重启不丢
    - persona_id 维度隔离
`

**面试话术**："语义缓存不是简单的 exact match，而是用 embedding 相似度做 fuzzy dedup。'今天天气怎么样'和'今天天气如何'能被同一缓存命中，省一次 LLM 调用。"

### 4.6 多模态 RAG

**文件**: services/document_parser.py

`
支持格式: TXT / MD / PDF / DOCX / PNG / JPG

解析分发:
  PDF  → PyMuPDF(fitz) 主线 / pdfplumber 回退
  DOCX → python-docx
  图片 → easyocr 本地OCR 主线 / LLM Vision (GPT-4o) 回退

摄入管线:
  parse → chunk → insert_memory → embed_texts_and_index → bind persona
`

### 4.7 测试体系

`
tests/
├── conftest.py          # 独立临时DB + monkeypatch settings
├── test_memory.py       # 记忆写入 + FTS5 检索
├── test_safety.py       # 注入检测 + 输出安全 + 角色崩坏扣分
├── test_guards.py       # 死循环检测 + 工具指纹 + 超时配置
├── test_chunking.py     # 分块策略 + 父-子块追溯
└── test_cache.py        # 语义缓存读写 + 清空

20 个测试, 1.07s 全量通过
`

### 4.8 A/B 实验体系

**文件**: services/experiment.py + main.py (中间件)

`
分流策略:
  MD5(experiment_id + user_id) → 一致性哈希 → 同一用户始终同一变体

中间件注入:
  X-User-Id / X-Experiment-Id 请求头
    → ExperimentMiddleware (BaseHTTPMiddleware)
    → request.state.experiment_variant

指标采集:
  ExperimentEvent → experiment_events 表
    impression / conversion / latency
  GET /api/experiments/{id}/stats → 分组转化率 + 平均延迟
`

### 4.9 Agentic RAG：查询规划

**文件**: services/planner.py

`
planner_node (friend_graph 新入口节点)
  plan_query(): LLM 分析意图 → 四种策略:
  ├─ direct     → 问候/闲聊，跳过检索
  ├─ single     → 单事实查询
  ├─ multi_hop  → 拆多条子查询 → 去重 → 聚合 → 注入上下文
  └─ reflection → 先搜后追问

新 Graph 拓扑:
  entry → planner → agent → tools ↔ agent → guard → review → END

容错: 规划器异常 → 降级为 single 策略
`

### 4.11 HyDE 查询改写（新增）

检索前增强:
  recall(query, use_hyde=True) → generate_hypothetical_doc(query)
  LLM 生成"假想完美回答文档"（100-200字陈述句）
  → 用假设文档 embedding 替代原始 query embedding → 命中原始 query 搜不到的记忆
  容错: HyDE 生成失败 → 自动降级为原始 query

**面试话术**："HyDE 解决 query-document embedding 分布不一致问题——用户口语化短 query 和知识库陈述句 chunk 语义距离远。先生成假设文档做桥梁，recall 能提升 10-15%。"

### 4.12 Health Check（新增）

GET /api/health → 三依赖探测: SQLite SELECT 1 / ChromaDB count / LLM ping
全部 ok → 200，任一挂 → 503 degraded

### 4.13 Rate Limiting（新增）

slowapi 分层限流: /chat/stream 10/min, /personas/import 3/min, /documents/upload 5/min, /providers 60/min
中间件注入 main.py，内存后端可切 Redis

### 4.14 Docker 一键部署（新增）

docker-compose.yml: backend + frontend nginx 反向代理
volume 持久化 SQLite/ChromaDB + BGE 模型缓存
healthcheck 依赖检测，depends_on service_healthy

### 4.15 多轮对话摘要压缩（新增）

升级前: sliding window → 超窗口信息永久丢失
升级后: should_summarize() 触发判断 → summarize_messages() LLM 增量摘要 → build_summary_context() 注入 agent_node
效果: "花生过敏"在 20 轮后仍能被 Agent 记住

### 4.16 Model Router（新增）

classify_query_complexity(): 简单问候 → v4-flash, 推理关键词/长query → v4-pro
agent_node 自动注入: provider_cfg.model = get_model_for_query(user_input)

### 4.17 流式 Guard（新增）

SSE 每 25 token → check_output_safety(reply_buffer)
passed → 继续 / failed → yield "[回复已中断]" + break
只跑 L1 正则（零延迟），L2 LLM 审核仍走 guard_node



### 4.18 外部工具集成（新增）

Agent 可调用 5 种真实世界工具：
  web_search    → DuckDuckGo 免费搜索（无需 API key）
  get_weather   → wttr.in 天气查询（免费）
  calculate     → AST 安全数学求值（支持 +-*/() 幂运算）
  fetch_webpage → httpx + BeautifulSoup 网页内容抓取
  get_datetime  → 当前时间 / 日期计算（now/tomorrow/+3d）

工具注册在 tools/__init__.py，friend_graph + persona_graph 双 Agent 均可调用。
安全设计: calculate 用 AST 白名单运算符，fetch_webpage 限制 http/https 协议。

### 4.19 本地 LLM 部署：Ollama（新增）

Provider 注册表新增 ollama:
  base_url: http://localhost:11434/v1
  可用模型: llama3.2, qwen2.5:7b, deepseek-r1:8b, mistral
  optional_api_key: true（本地无需 key）

用户在前端 Settings 中选择 ollama → 自动切到本地模型。
适合面试展示: 断网也能跑，私有化部署零成本。

### 4.20 GraphRAG 知识图谱（新增）

graph_rag.py:
  extract_triples()      → LLM 抽取 (head, relation, tail) 三元组
  add_triples_to_graph() → networkx 无向图存储
  graph_search()         → BFS 图遍历检索（max_hops 可配置）
  build_graph_from_memories() → 批量从知识库构建图谱

集成到 recall(): FTS5 + Vector + Graph 三重检索
API: POST /api/graph/build → GET /api/graph/stats → POST /api/graph/search

**面试话术**: "GraphRAG 解决传统 RAG 只能做语义相似匹配、无法做多跳推理的问题。
比如用户问'张三喜欢什么'，传统 RAG 搜'张三 喜欢'可能找不到；
GraphRAG 先抽实体→'张三'节点 BFS 两跳→发现'张三-喜欢-冰美式'边，直接返回。"

### 4.21 多智能体协作（新增）

agents/orchestrator.py:
  decompose_node    → LLM 分析用户意图，决定调用哪些 Agent
  exec_friend_node  → friend agent 视角回复
  exec_persona_node → persona agent 视角回复
  merge_node        → 合并双 Agent 输出为整合回复

LangGraph 拓扑:
  entry → decompose → friend_agent | persona_agent → merge → END

API: POST /api/chat/collaborative/stream
场景: "帮我从我和张三两个角度分析这件事" → 双 Agent 并行 → 合并


### 4.10 Observability & 离线评测

`
链路追踪:
  recall() → uuid4.hex[:12] → trace_id
  → RecallResult.trace_id + 日志 (query_preview, mode, k, weights)

用户反馈:
  POST /api/feedback { trace_id, thumbs, rating, clicked_ids }
  → retrieval_feedback 表

指标 API:
  GET /api/metrics/retrieval  → rerank 成功率 + total_calls
  反馈统计: thumbs_up_rate, avg_rating

离线评测:
  scripts/eval_retrieval.py
  → data/eval/queries.json
  → MRR / Recall@1/3/5/10 / NDCG@5/10
  → data/eval/latest_result.json
`

---

## 五、可配置参数一览

| 参数 | 默认值 | 位置 | 面试话术 |
|------|-------|------|---------|
| chunk_size: 512 | token | TextChunker | "适配大多数 LLM 上下文窗口" |
| chunk_overlap: 50 | token | TextChunker | "保留跨块语义连续性" |
| rf_k: 60 | 排名宽容度 | config.py | "中等偏保守，可在 eval 上扫描最优" |
| rf_weight_fts: 1.0 | 关键词权重 | config.py | "专有名词多时调高，语义搜索多时调低" |
| rf_weight_vector: 1.0 | 向量权重 | config.py | "与 FTS 权重互补调整" |
| persona_consistency_threshold: 0.70 | cosine | safety.score_consistency | "可在标注集上 calibration" |
| cache_similarity_threshold: 0.95 | cosine | cache.py | "过高则命中少，过低则误命中" |
| dead_loop_threshold: 3 | 连续相同指纹 | guards.py | "3次够了，再多浪费 token" |
| max_rounds: 4 | 保留对话轮数 | compaction.py | "控制上下文窗口" |
| etrieval_metrics_log_interval: 100 | 调用次数 | config.py | "生产环境可调大" |

---

## 六、典型面试问题与回答模板

### Q1: "这个项目的难点是什么？"

答三个：
1. **混合检索的延迟与精度平衡**：FTS + Vector → RRF → Rerank 三层，每层可独立降级。Rerank 宕了走 RRF 截断，Vector 宕了走纯关键词。设计哲学是"永不阻断查询"。
2. **用户数据安全与 Agent 行为控制**：双 Agent 数据隔离（where 条件硬控而非 Prompt 软控）+ 三层 Guard 纵深防御 + LLM Review 兜底。
3. **检索延迟控制在流式可用范围内**：本地 BGE-M3 → cosine 距离 → FlagEmbedding Reranker 全本地链路，避免网络 IO 抖动。

### Q2: "如果数据量大了怎么办？"

水平扩展：
- SQLite → PostgreSQL (pgvector 原生向量支持)
- ChromaDB → Qdrant / Milvus (分布式向量集群)
- FTS5 → ElasticSearch (分布式倒排索引)

垂直优化：
- 离线评测脚本做 RRF/Rerank 参数扫描
- 业务 SQL 参数化，通过 database.py 集中管理迁移
- 语义缓存命中率高的话，能吃掉大量重复查询

### Q3: "这个项目有什么可量化的指标？"

| 维度 | 指标 |
|------|------|
| RAG 质量 | MRR / Recall@1,3,5,10 / NDCG@5,10 |
| Agent 行为 | Rerank 成功率 / Guard 拦截率 |
| 用户满意度 | Thumbs up rate / Avg rating (1-5) |
| 工程 | P50/P95 延迟 / Token 消耗 / 缓存命中率 |
| 实验 | A/B 分组转化率 / 显著性检验 |

### Q4: "你做的改进中哪个最有价值？"

推荐讲 **Agentic RAG 查询规划** 或 **混合检索降级体系**：

"Agentic RAG 让 LLM 在检索前先做意图分析，复杂问题自动分解为 multi-hop。降级策略确保规划器宕了也不影响可用性。面试官想看的是你有没有让系统'可规划、可降级、可度量'的意识，而不是只堆功能。"

### Q5: "为什么用 LangGraph 而不是手写 Agent 循环？"

"LangGraph 的优势：1) 状态管理内置 add_messages reducer 自动合并；2) 可视化拓扑让面试时一张图说清楚流程；3) astream_events 原生支持逐 token SSE。手写循环也能做，但 LangGraph 的 conditional edge 和 state schema 让复杂 Agent 拓扑更可维护。"

### Q6: "安全性你是怎么考虑的？"

"纵深防御三层：L1 正则零延迟阻断高风险；L2 LLM 做语义审核；L3 embedding 做无监督一致性评分。不是靠一个层解决所有问题。另外工具层面的 SQL 门控和死循环检测是 Agent 特有的安全考量——普通 RAG 不需要，但 Agent 有了工具调用就必须有。"

---

## 七、如果你还想加技术点

面试官如果问"你觉得还可以加什么"，以下是可直接落地的方向：

| 方向 | 具体做法 | 面试价值 |
|------|---------|---------|
| **LangSmith / LangFuse tracing** | 全链路 token 消耗 + 延迟监控 | 生产可观测性 |
| **Query Rewrite** | 检索前用 LLM 改写用户 query（HyDE / Step-Back） | RAG 深度优化 |
| **多轮对话记忆压缩** | 用 LLM 定期做对话摘要替代 sliding window | 长对话上下文管理 |
| **Model Router** | 简单问题用小模型，复杂问题用大模型 | 降成本 |
| **Human-in-the-loop** | LangGraph interrupt 机制，敏感操作等人工确认 | 安全可控 |
| **流式 Token 级别的 Guard** | 不等完整回复就做安全检测 | 低延迟安全 |
| **知识图谱增强** | Neo4j + GraphRAG 做实体关系推理 | 复杂推理场景 |
| **Grading Eval** | LLM-as-judge 对回复质量自动打分 | 持续评估 |

---

## 八、文件结构

`
docker-compose.yml                # ★ 一键部署
├── backend/
│   ├── Dockerfile                # ★ 后端容器
├── frontend/
│   ├── Dockerfile                # ★ 前端容器
│   ├── nginx.conf                # ★ nginx 配置
├── 
├── app/
│   ├── agents/
│   │   ├── friend_graph.py        # 虚拟好友 LangGraph (planner→agent→tools→guard→review)
│   │   └── persona_graph.py       # 用户替身 LangGraph
│   ├── api/
│   │   └── routes.py              # 全部 REST + SSE 端点
│   ├── models/
│   │   └── __init__.py            # 20+ 个 Pydantic BaseModel
│   ├── pipelines/
│   │   └── profile_builder.py     # 三步画像构建 Pipeline
│   ├── services/
│   │   ├── cache.py               # 语义缓存（内存层）
│   │   ├── chunking.py            # TextChunker 分块策略
│   │   ├── compaction.py          # 上下文压缩
│   │   ├── database.py            # SQLite + FTS5 + schema
│   │   ├── document_parser.py     # ★ 多模态文档解析
│   │   ├── embedding.py           # 向量化 (本地BGE-M3 / 云端)
│   │   ├── experiment.py          # ★ A/B 实验分流 + 指标
│   │   ├── guards.py              # 死循环检测 + 工具超时
│   │   ├── memory.py              # 混合检索核心
│   │   ├── planner.py             # ★ Agentic RAG 查询规划
│   │   ├── provider.py            # LLM Provider 工厂
│   │   ├── rerank.py              # Rerank (本地 / 云端)
│   │   ├── review.py              # LLM 回答审核
│   │   ├── safety.py              # 三层安全 Guard
│   │   ├── hyde.py                # ★ HyDE 查询改写
│   │   ├── model_router.py        # ★ Model Router (deepseek-v4-flash/pro)
│   │   ├── semantic_cache.py      # 语义缓存（持久层）
│   │   └── tool_policy.py         # SQL 门控策略
│   ├── tools/
│   │   └── __init__.py            # recall/remember/query_profile/update_profile/query_sql
│   ├── config.py                  # 全部可配置参数
│   └── main.py                    # FastAPI 入口 + 实验中间件
├── tests/                         # ★ pytest 20 测试
│   ├── conftest.py
│   ├── test_cache.py
│   ├── test_chunking.py
│   ├── test_guards.py
│   ├── test_memory.py
│   └── test_safety.py
├── scripts/
│   └── eval_retrieval.py          # 离线评测 MRR/Recall/NDCG
└── data/
    └── eval/
        └── queries.json           # 标注数据集
`

---

## 九、20 秒电梯演讲

"MirrorTalk 是一个 AI 虚拟好友系统。上传你和朋友的微信聊天记录，LLM 会提取人格画像，然后你可以和这个 AI 分身对话——它用朋友的口吻回复你。反过来，你也可以让 AI 学习你的说话风格，替你回复别人。

技术上用了 LangGraph 编排双 Agent、FTS5+ChromaDB 混合检索、RRF 融合+Rerank 精排、三层安全纵深防御。最近加了 Agentic RAG 查询规划和 A/B 实验框架。全栈自己写的，后端 FastAPI + 前端 React，20 个测试通过。"



