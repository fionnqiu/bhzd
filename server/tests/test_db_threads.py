"""db.connect 的跨线程可用性回归测试。

背景（为什么有这个测试）：FastAPI 同步生成器依赖 deps.get_db 在 anyio 线程池
建连，async 端点在事件循环线程使用、依赖清理又可能落到另一个线程池线程。
sqlite3 默认 check_same_thread=True 会在真实 uvicorn 下间歇抛
ProgrammingError → 前端看到"服务器开小差了"（500）。TestClient 单门户线程
掩盖了该问题，172 项测试全绿时真实服务器仍会中招，故此处显式锁定跨线程行为。
"""

from __future__ import annotations

import threading

from bhzd_py import db as db_module


def test_connection_usable_across_threads(tmp_path):
    """同一线程创建的连接可在另一线程使用并关闭（请求生命周期内访问串行）。"""
    conn = db_module.connect(str(tmp_path / "t.sqlite"))
    conn.execute("CREATE TABLE t (id INTEGER)")
    errors: list[Exception] = []

    def work() -> None:
        try:
            conn.execute("INSERT INTO t VALUES (1)")
            conn.commit()
            conn.close()
        except Exception as exc:  # noqa: BLE001 - 测试需要捕获一切跨线程异常
            errors.append(exc)

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert not errors, f"跨线程使用连接失败: {errors}"


def test_concurrent_requests_use_independent_connections(tmp_path):
    """每请求独立连接在 WAL 下可并行读写（多会话并发场景的底线保障）。"""
    path = str(tmp_path / "t.sqlite")
    conn = db_module.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()

    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            c = db_module.connect(path)
            c.execute("INSERT INTO t VALUES (?)", (n,))
            c.commit()
            c.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"并发独立连接写入失败: {errors}"
    check = db_module.connect(path)
    assert check.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 8
    check.close()
