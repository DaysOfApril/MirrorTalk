# MirrorTalk Backend Dockerfile
# 分层构建：依赖层（缓存友好）→ 代码层

FROM python:3.12-slim

WORKDIR /app

# ---- 系统依赖 ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Python 依赖层（利用 Docker cache）----
COPY backend/pyproject.toml .
RUN pip install --no-cache-dir -e .[local] && \
    pip install slowapi

# ---- 代码层 ----
COPY backend/ .

# ---- 模型缓存目录（volume mount）----
RUN mkdir -p /app/data /root/.cache

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
