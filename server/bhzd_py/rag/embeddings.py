"""嵌入计算：provider 嵌入优先，本地哈希嵌入兜底（蓝图 §1/§2.1）。

为什么必须永不为 provider 失败抛错：PRD-06 §11 要求离线/演示/测试全链路可跑，
嵌入 provider 未配置、连接失败或返回异常时，必须能退回确定性本地嵌入
（rag/local_embed.py，512 维词袋）。因此本模块对 provider 的一切异常都
静默降级，只在结果里如实报告实际使用的模型名。

与 agent 域的接口约定：provider 嵌入通过懒加载
`bhzd_py.agent.providers.embed_texts(texts) -> list[list[float]] | None` 获取
（async 函数，内部自行按 get_config() 建库连接查找 role='embedding' 的启用
provider；未配置/失败返回 None）。选择顺序：启用的 'embedding' provider
→ 任何失败/None 时降级本地哈希嵌入。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sqlite3
import struct
import threading
from typing import Any, Coroutine

from .local_embed import EMBEDDING_MODEL, embed_text

logger = logging.getLogger(__name__)


def run_coro_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """在同步上下文里执行一个协程并返回其结果。

    为什么需要它：嵌入/重排管线（pipeline、seed、检索）是纯同步代码，而
    provider 层（agent.providers）是 async。两种调用现场都必须支持：

    - 当前线程**没有**运行中的事件循环（seed 脚本、pipeline 同步执行、
      单元测试）：直接用 `asyncio.Runner` 开一个短生命周期事件循环跑完
      即关闭，避免反复 new_event_loop 泄漏。
    - 当前线程**已在**事件循环里（FastAPI async 端点，例如上传接口触发
      的同步管线经线程池执行时仍可能身处循环线程）：此时 `asyncio.run`
      会直接 RuntimeError，也不能阻塞等待本循环上的任务（死锁）。于是
      在独立工作线程里新建事件循环执行并 join 回收结果/异常——协程对象
      本身不绑定循环，跨线程 await 是安全的。

    线程内抛出的异常会带回调用线程重新抛出，由调用方决定降级策略。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 无运行中循环：本分线程直接开一个短生命周期循环跑完
        with asyncio.Runner() as runner:
            return runner.run(coro)
    # 已在运行中的事件循环内：新线程 + 新循环执行，join 等待结果
    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            with asyncio.Runner() as runner:
                box["result"] = runner.run(coro)
        except BaseException as exc:  # 异常必须带回主线程，否则被线程吞掉
            box["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    worker.join()
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _pack_vector(values) -> bytes | None:
    """把 provider 返回的浮点列表打包为 float32 BLOB；bytes 原样返回。"""
    if isinstance(values, (bytes, bytearray)):
        return bytes(values)
    try:
        floats = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    return struct.pack(f"<{len(floats)}f", *floats)


def _try_provider_embeddings(db: sqlite3.Connection, texts: list[str]) -> tuple[list[bytes], str] | None:
    """尝试走 provider 嵌入；任何不可用迹象都返回 None（调用方降级本地）。

    先用调用方传入的 db 查 role='embedding' 的启用 provider 行：既完成
    "未配置即跳过"的选择，也拿到真实的嵌入模型名（记录到 rag_chunks.
    embedding_model，召回测试台据此展示）。embed_texts 是 async 且内部
    自行建连调用，本同步管线通过 run_coro_sync 桥接执行。
    """
    try:
        from ..agent import providers  # 懒加载：避免 rag 域硬依赖 agent 域
    except Exception:
        return None
    try:
        row = providers.get_enabled_provider(db, "embedding")
    except Exception:
        return None  # provider_configs 表缺失等异常环境：按未配置处理
    if row is None:
        return None
    embed_texts = getattr(providers, "embed_texts", None)
    if embed_texts is None:
        return None
    try:
        result = embed_texts(texts)
        if inspect.iscoroutine(result):
            result = run_coro_sync(result)  # 同步管线桥接 async provider（见函数 docstring）
    except Exception as exc:
        logger.warning("provider 嵌入失败，降级本地嵌入：%s", exc)
        return None
    if not result or len(result) != len(texts):
        return None
    packed = [_pack_vector(item) for item in result]
    if any(blob is None for blob in packed):
        return None
    # 记录真实模型名：provider 行上的 model 即实际调用的嵌入模型
    return list(packed), str(row["model"])


def embed_chunks(db: sqlite3.Connection, texts: list[str]) -> tuple[list[bytes], str]:
    """为一批文本计算嵌入，返回 (打包好的向量 BLOB 列表, 实际模型名)。

    永不因 provider 故障抛错：provider 不可用 → 每 chunk 走本地哈希嵌入。
    """
    if not texts:
        return [], EMBEDDING_MODEL
    provided = _try_provider_embeddings(db, texts)
    if provided is not None:
        return provided
    return [embed_text(t) for t in texts], EMBEDDING_MODEL
