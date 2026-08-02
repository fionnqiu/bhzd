"""FastAPI 应用工厂（蓝图 §2.1/§17 Wave1）。

router 注册的容错策略：Wave1 只有地基，routers/* 在 Wave2 才逐个落地，
因此每个模块的 import+include 都包在 try/except ImportError 里——缺哪个
记一条告警继续，保证地基阶段应用始终可启动；Wave4 集成时全部就位后
这些告警自然消失。
"""

from __future__ import annotations

import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, db as db_module
from .config import get_config
from .errors import register_error_handlers
from .security import create_password_encryption_material

logger = logging.getLogger(__name__)

# 蓝图 §2.1 约定的全部 router 模块（每个暴露 APIRouter 实例名 `router`）
ROUTER_MODULES = [
    "auth",
    "runs",
    "confirmations",
    "presets",
    "graph",
    "tasks",
    "diagnostics",
    "profile",
    "rag_query",
    "rag_admin",
    "teacher",
    "admin",
    "notifications",
    "events",
]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # 启动时应用迁移：保证库结构与代码版本一致（幂等，重复启动无副作用）
    config = get_config()
    # Validate before opening the database so an incomplete production profile
    # cannot partially migrate data and then expose development-only fallbacks.
    config.validate_runtime_configuration()
    conn = db_module.connect(config.resolved_database_path)
    try:
        applied = db_module.apply_migrations(conn)
        if applied:
            logger.info("已应用数据库迁移: %s", ", ".join(applied))
    finally:
        conn.close()
    yield


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    config = get_config()
    app = FastAPI(title="标航智导 API", version=__version__, lifespan=_lifespan)
    # One app owns one key pair.  The auth router reads this state so a public
    # key fetched by the browser always maps to the decrypting application.
    app.state.password_encryption = create_password_encryption_material()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origin_list,
        allow_credentials=True,  # 会话走 cookie，必须放行凭据
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    for name in ROUTER_MODULES:
        try:
            module = importlib.import_module(f"bhzd_py.routers.{name}")
            app.include_router(module.router)
        except ImportError:
            # Wave2 才会逐个补齐；缺失仅告警，不阻断地基启动
            logger.warning("router 模块 bhzd_py.routers.%s 尚未就绪，已跳过注册", name)
    return app


# uvicorn 直接引用入口（bhzd_py.app:app）
app = create_app()
