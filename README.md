# MirrorTalk

**AI 虚拟好友对话与用户替身系统**

上传真实聊天记录 → LLM 提取人格画像 → 构建双 AI Agent → 「虚拟好友」可与之对话、「用户替身」可替你回复消息。

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (React 19)                  │
│  好友聊天 │ 替身回复 │ 数据导入 │ 画像管理 │ 知识库 │ 设置 │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP / Streaming
┌──────────────────────▼──────────────────────────────────────┐
│                   FastAPI Backend                            │
│  ┌─────────┐  ┌──────────┐  ┌────────────┐  ┌───────────┐ │
│  │好友图    │  │替身图    │  │编排 Agent  │  │A/B 实验   │ │
│  │(Agent)  │  │(Agent)   │  │(Orchestr.)│  │中间件     │ │
│  └────┬────┘  └────┬─────┘  └─────┬──────┘  └───────────┘ │
│       └────────────┼──────────────┘                         │
│               ┌────▼────┐                                    │
│               │共享服务层│                                    │
│               └────┬────┘                                    │
│  ┌───────┐ ┌──────┐ ┌───────┐ ┌─────┐ ┌───────┐ ┌──────┐  │
│  │Memory │ │RAG   │ │Safety │ │LLM  │ │Embed  │ │Rerank│  │
│  │Service│ │Graph │ │Guard  │ │Router│ │Service│ │Service│  │
│  └───────┘ └──────┘ └───────┘ └─────┘ └───────┘ └──────┘  │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                    数据层                                      │
│  SQLite (结构化数据) │ ChromaDB (向量数据库) │ 本地文件系统   │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心功能

### 1. 双 Agent 对话
采用 **双 Agent 独立图架构**（[ADR-001](./docs/adr/0001-dual-agent-architecture.md)）：

| Agent | 用途 | 工具 |
|-------|------|------|
| **虚拟好友图** (`friend_graph`) | 与 AI 虚拟好友自由对话 | 加载好友风格、查询知识库好友相关事实 |
| **用户替身图** (`persona_graph`) | 替用户回复真实好友的消息 | 加载用户替身画像、`update_profile`、`query_profile` |

两个 Agent 共享基础设施（memory service、embedding、rerank），但图结构、system prompt、工具集各自独立，保证信息边界天然隔离。

### 2. 人格画像提取
支持从真实聊天记录中自动提取用户/好友的人格画像：

- **风格标签**（personality traits, tone, catchphrases, emoji usage, sentence style）
- **大五人格 OCEAN**（开放性、尽责性、外向性、宜人性、神经质）
- **多数共识聚合**（[ADR-004](./docs/adr/0004-majority-consensus-aggregation.md)）：多个替身间的聚合采用算术平均 + 多数保留规则
- **深度画像** (`deep_profile`)：对特定话题进行更细致的画像分析

### 3. RAG 知识库
- **混合检索**：向量相似度 + 全文搜索 (FTS) 的 RRF 融合排序
- **Agentic RAG**：LLM 自主规划查询路径（query decomposition + 子查询合并）
- **Graph RAG**：实体关系图增强检索
- **HyDE**：假设性文档嵌入增强检索
- **多模态文档摄入**：支持 PDF、DOCX、TXT 等格式

### 4. LLM 多 Provider 支持
支持多种 LLM Provider，可动态切换：

| Provider | 配置方式 |
|----------|----------|
| OpenAI | API Key + Base URL |
| DeepSeek | API Key |
| Qwen (通义千问) | API Key |
| Ollama | 本地端点 |
| Custom | 任意 OpenAI 兼容 API |

### 5. Embedding & Rerank
**本地优先、混合云端**策略（[ADR-005](./docs/adr/0005-local-first-hybrid-cloud.md)）：

- **本地默认**：`BAAI/bge-m3` (Embedding) + `BAAI/bge-reranker-v2-m3` (Rerank)
- **云端回退**：自动降级到用户配置的 Provider
- 聊天内容完全不出机器（本地模式）

### 6. 安全与治理
- **安全护栏** (`safety.py`, `guards.py`, `tool_policy.py`)：内容审核、敏感词过滤
- **A/B 实验** (`experiment.py`)：基于确定性哈希的分流，支持多变体实验
- **速率限制**：基于 slowapi 的全局限流
- **Review 机制** (`review.py`)：对生成内容进行质量审查

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React 19 + TypeScript + Vite 6 + Tailwind CSS 4 + React Router 7 | 现代化 SPA |
| **后端** | FastAPI + Python 3.11+ | 异步高性能 API |
| **Agent 框架** | LangGraph + LangChain Core | 双 Agent 有状态图 |
| **LLM SDK** | OpenAI SDK + Anthropic SDK + Google GenAI SDK | 多 Provider |
| **向量数据库** | ChromaDB 0.6+ | 本地向量存储 |
| **结构化存储** | SQLite | 对话、配置、画像 |
| **Embedding** | Sentence Transformers (BGE) | 本地/云端回退 |
| **Rerank** | FlagEmbedding (BGE Reranker) | 本地/云端回退 |
| **文档解析** | PyMuPDF + python-docx | PDF/DOCX 摄入 |
| **容器化** | Docker Compose | 一键部署 |

---

## 快速开始

### 前置要求

- Python >= 3.11
- Node.js >= 18
- (可选) Docker + Docker Compose

### 本地开发

#### 1. 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # Linux/Mac

pip install -e .
pip install -e ".[local]"  # 如需本地 Embedding/Rerank 模型

# 配置环境变量（可选，也可在 Web 设置页面配置）
# 设置 .env 文件或系统变量，见 backend/app/config.py
# MIRRORTALK_LLM_PROVIDER=qwen
# MIRRORTALK_LLM_API_KEY=your_key

python -m app.main
```

后端启动于 `http://localhost:8000`，API 文档访问 `http://localhost:8000/docs`。

#### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

前端启动于 `http://localhost:5173`。

#### 3. 使用 Docker Compose

```bash
docker compose up -d
```

- 后端：`http://localhost:8000`
- 前端：`http://localhost:3000`

### 首次使用流程

1. 打开前端 → 进入「设置」配置 LLM API Key（支持 OpenAI / DeepSeek / Qwen / Ollama）
2. 进入「数据导入」上传聊天记录（JSON/TXT 格式）
3. 系统自动提取人格画像，在「画像管理」中查看
4. 在「好友聊天」中选择虚拟好友开始对话
5. 在「替身回复」中让 AI 替身帮你回复真实好友

---

## 项目结构

```
MirrorTalk/
├── backend/
│   ├── app/
│   │   ├── agents/           # LangGraph Agent 定义
│   │   │   ├── friend_graph.py    # 虚拟好友图
│   │   │   ├── persona_graph.py   # 用户替身图
│   │   │   └── orchestrator.py    # 编排 Agent
│   │   ├── api/
│   │   │   └── routes.py          # FastAPI 路由
│   │   ├── models/               # Pydantic 数据模型
│   │   ├── pipelines/
│   │   │   ├── profile_builder.py # 画像构建流水线
│   │   │   └── deep_profile.py    # 深度画像
│   │   ├── services/
│   │   │   ├── cache.py           # 响应缓存
│   │   │   ├── chunking.py        # 文档分块
│   │   │   ├── compaction.py      # 记忆压缩
│   │   │   ├── database.py        # SQLite 数据库
│   │   │   ├── document_parser.py # 文档解析
│   │   │   ├── embedding.py       # Embedding 服务
│   │   │   ├── experiment.py      # A/B 实验系统
│   │   │   ├── external_tools.py  # 外部工具
│   │   │   ├── graph_rag.py       # Graph RAG
│   │   │   ├── guards.py          # 安全护栏
│   │   │   ├── hyde.py            # HyDE 检索增强
│   │   │   ├── memory.py          # 记忆管理
│   │   │   ├── model_router.py    # LLM 模型路由
│   │   │   ├── planner.py         # RAG 查询规划
│   │   │   ├── provider.py        # LLM Provider 管理
│   │   │   ├── rerank.py          # Rerank 服务
│   │   │   ├── review.py          # 内容审查
│   │   │   ├── safety.py          # 安全策略
│   │   │   ├── semantic_cache.py  # 语义缓存
│   │   │   ├── stream_parser.py   # 聊天记录解析
│   │   │   └── tool_policy.py     # 工具调用策略
│   │   ├── config.py              # 配置项
│   │   └── main.py                # 入口
│   ├── data/                      # 运行时数据
│   │   ├── chroma/                # ChromaDB 持久化
│   │   ├── tmp/                   # 临时文件
│   │   └── uploads/               # 上传文件
│   ├── tests/                     # 测试
│   ├── scripts/                   # 工具脚本
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── ChatPanel.tsx      # 好友聊天页
│   │   │   ├── FriendChat.tsx     # 好友对话组件
│   │   │   ├── PersonaReply.tsx   # 替身回复页
│   │   │   ├── PersonaManage.tsx  # 画像管理页
│   │   │   ├── DataImport.tsx     # 数据导入页
│   │   │   ├── KnowledgeBase.tsx  # 知识库页
│   │   │   ├── DeepProfile.tsx    # 深度画像页
│   │   │   └── SettingsPage.tsx   # 设置页
│   │   ├── components/            # 通用组件
│   │   ├── lib/utils.ts           # 工具函数
│   │   ├── App.tsx                # 主应用 + 路由
│   │   ├── index.css              # 样式 (Tailwind)
│   │   └── main.tsx               # 入口
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── Dockerfile
├── docs/
│   ├── adr/                       # 架构决策记录
│   │   ├── 0001-dual-agent-architecture.md
│   │   ├── 0002-medium-granularity-tools.md
│   │   ├── 0003-tags-first-ocean-secondary.md
│   │   ├── 0004-majority-consensus-aggregation.md
│   │   └── 0005-local-first-hybrid-cloud.md
│   ├── CONTEXT.md                 # 项目上下文
│   └── INTERVIEW_GUIDE.md         # 面试指南
├── scripts/                       # 部署/运维脚本
├── docker-compose.yml             # Docker 编排
├── .gitignore
└── LICENSE                        # MIT
```

---

## API 概览

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/chat` | POST | 发送消息给虚拟好友 |
| `/api/persona-reply` | POST | 获取替身回复建议 |
| `/api/personas` | GET | 获取画像列表 |
| `/api/conversations` | GET | 获取对话历史 |
| `/api/import/upload` | POST | 上传聊天记录文件 |
| `/api/tasks/{task_id}` | GET | 查询导入任务状态 |
| `/api/providers` | GET | 列出可用 LLM Provider |
| `/api/providers/{id}/models` | GET | 获取 Provider 模型列表 |
| `/api/health` | GET | 健康检查 |
| `/api/config` | GET/POST | 读写配置 |
| `/api/knowledge` | GET/POST | 知识库管理 |
| `/api/experiments` | GET/POST | A/B 实验管理 |

---

## 架构决策记录

本项目使用 ADR（Architecture Decision Record）记录关键架构决策：

- **[ADR-001](./docs/adr/0001-dual-agent-architecture.md)**：双 Agent 独立图架构 — 虚拟好友 vs 用户替身
- **[ADR-002](./docs/adr/0002-medium-granularity-tools.md)**：中等粒度工具设计 — 平衡原子性与通用性
- **[ADR-003](./docs/adr/0003-tags-first-ocean-secondary.md)**：标签优先、OCEAN 为辅的画像方案
- **[ADR-004](./docs/adr/0004-majority-consensus-aggregation.md)**：多数共识聚合 — 综合替身生成策略
- **[ADR-005](./docs/adr/0005-local-first-hybrid-cloud.md)**：本地优先、混合云端的 Embedding/Rerank 策略

---

## 测试

```bash
cd backend
pytest                            # 运行全部测试
pytest tests/test_cache.py        # 缓存测试
pytest tests/test_chunking.py     # 分块测试
pytest tests/test_memory.py       # 记忆测试
pytest tests/test_safety.py       # 安全护栏测试
pytest tests/test_guards.py       # 守卫测试
```

---

## License

MIT License — 详见 [LICENSE](./LICENSE)。

Copyright (c) 2026 DaysOfApril
