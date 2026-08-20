"""FastAPI 应用工厂。

All listed routers are now production requirements.  Import failures must stop
startup rather than silently turn an API domain into health-check-hidden 404s.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from threading import Thread
from types import ModuleType

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, db as db_module
from .agent.recovery import recover_interrupted_runs
from .config import get_config
from .errors import register_error_handlers
from .rag import pipeline as rag_pipeline
from .retention import prune_expired_records
from .routers import (
    admin,
    auth,
    confirmations,
    diagnostics,
    events,
    graph,
    notifications,
    presets,
    profile,
    rag_admin,
    rag_query,
    runs,
    tasks,
    teacher,
    teacher_agent,
)
from .security import create_password_encryption_material

logger = logging.getLogger(__name__)

# Each module exposes an ``APIRouter`` named ``router``.  Keeping this explicit
# makes a missing dependency an immediate startup error instead of a partial API.
ROUTER_MODULES: tuple[ModuleType, ...] = (
    auth,
    runs,
    confirmations,
    presets,
    graph,
    tasks,
    diagnostics,
    profile,
    rag_query,
    rag_admin,
    teacher,
    teacher_agent,
    admin,
    notifications,
    events,
)


def _start_startup_maintenance(config, *, resume_rag_jobs: bool) -> None:
    """Resume durable RAG work and optionally prune one bounded retention batch.

    The request-independent worker owns a fresh SQLite connection because the
    lifespan connection closes before the app starts serving traffic.  It is a
    daemon by design: shutdown may interrupt it, but queued RAG jobs and old
    records remain durable and will be retried on the next enabled startup.
    """

    def run() -> None:
        maintenance_conn = db_module.connect(config.resolved_database_path)
        try:
            if resume_rag_jobs:
                summary = rag_pipeline.run_pending(maintenance_conn, config)
                logger.info(
                    "启动时恢复 RAG 队列: executed=%d, failed=%d",
                    summary["executed"],
                    summary["failed"],
                )
            if config.retention_enabled:
                deleted = prune_expired_records(
                    maintenance_conn, batch_size=config.retention_batch_size
                )
                deleted_total = sum(deleted.values())
                if deleted_total:
                    logger.info("启动时完成保留策略清理: deleted=%s", deleted)
        except Exception:
            # Startup must stay available when a best-effort maintenance pass
            # fails; the next restart can safely retry durable queued work.
            logger.exception("启动维护任务失败")
        finally:
            maintenance_conn.close()

    Thread(target=run, name="bhzd-startup-maintenance", daemon=True).start()


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
        recovery = recover_interrupted_runs(conn)
        if recovery.total:
            logger.warning(
                "启动时恢复 Agent 运行: failed=%d, replayed_terminal=%d, expired_confirmations=%d",
                recovery.failed_running,
                recovery.replayed_terminal,
                recovery.expired_confirmations,
            )
        # A RAG worker can stop between its durable claim and completion.  Put
        # only those interrupted claims back before checking whether startup
        # maintenance is needed; successful stages keep their artifacts.
        recovered_rag_jobs = rag_pipeline.recover_interrupted_jobs(conn)
        if recovered_rag_jobs:
            logger.warning("启动时重新排队中断的 RAG 任务: %d", recovered_rag_jobs)
        # Content workers are detached from request lifecycles.  Reclaim rows
        # left in ``generating`` after a process crash before this connection
        # closes, then let the shared Agent loop finish them asynchronously.
        from .tools.task_tools import recover_interrupted_task_content

        recovered_content_tasks = recover_interrupted_task_content(conn)
        if recovered_content_tasks:
            logger.warning(
                "startup recovered interrupted learning-content tasks: %d",
                len(recovered_content_tasks),
            )
        # Grading workers use the same process-level loop as content workers;
        # reclaim pending/grading submissions left by a stopped process before
        # traffic resumes so a learner never needs to resubmit an answer.
        recovered_grade_submissions = tasks.recover_interrupted_submission_grading(conn)
        if recovered_grade_submissions:
            logger.warning(
                "startup recovered interrupted grading submissions: %d",
                len(recovered_grade_submissions),
            )
        # Queue rows survive a process crash.  The bounded daemon below resumes
        # them after the lifespan connection is released, so 202 never depends
        # solely on the original BackgroundTasks worker remaining alive.
        queued_rag_jobs = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM rag_jobs WHERE status = 'queued')"
        ).fetchone()[0]
    finally:
        conn.close()
    if queued_rag_jobs or config.retention_enabled:
        _start_startup_maintenance(config, resume_rag_jobs=bool(queued_rag_jobs))
    yield


def _register_routers(
    app: FastAPI, modules: tuple[ModuleType, ...] | None = None
) -> None:
    """Register every required router and deliberately propagate import failures.

    The former Wave1 fallback concealed dependency regressions behind a healthy
    ``/api/health`` response.  A required router is part of application startup,
    so its failure must be visible to the process supervisor and deployment.
    """

    for module in ROUTER_MODULES if modules is None else modules:
        app.include_router(module.router)


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

    _register_routers(app)
    return app


# uvicorn 直接引用入口（bhzd_py.app:app）
app = create_app()
