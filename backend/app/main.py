# MirrorTalk Backend - 入口
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import settings
from app.services.database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MirrorTalk 启动中...")
    init_db()
    logger.info("数据库初始化完成")
    yield
    logger.info("MirrorTalk 关闭")



# A/B 实验分流中间件
from app.services.experiment import get_experiment, record_event, ExperimentEvent
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import time

class ExperimentMiddleware(BaseHTTPMiddleware):
    """"A/B 实验分流中间件：给每个请求打上实验标签"""
    async def dispatch(self, request: Request, call_next):
        # 从请求头或 query 中提取 user_id
        user_id = request.headers.get("X-User-Id") or request.query_params.get("user_id") or "anonymous"
        exp_id = request.headers.get("X-Experiment-Id") or ""

        variant_name = "control"
        if exp_id:
            exp = get_experiment(exp_id)
            if exp and exp.enabled:
                variant = exp.assign_variant(user_id)
                variant_name = variant.name
                # 注入配置到 request.state
                request.state.experiment_variant = variant
                request.state.experiment_id = exp_id

        start = time.time()
        response = await call_next(request)
        elapsed_ms = (time.time() - start) * 1000

        # 记录曝光事件
        if exp_id and get_experiment(exp_id):
            record_event(ExperimentEvent(
                experiment_id=exp_id,
                variant_name=variant_name,
                user_id=user_id,
                event_type="latency",
                value=elapsed_ms,
            ))

        response.headers["X-Experiment-Variant"] = variant_name
        return response

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(
    title="MirrorTalk",
    description="AI 虚拟好友对话与用户替身系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(ExperimentMiddleware)

app.include_router(router, prefix="/api")

# 生产环境 mount 前端产物
import os
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


def main():
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)


if __name__ == "__main__":
    main()



