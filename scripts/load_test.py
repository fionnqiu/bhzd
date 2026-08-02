"""性能与并发压测（完整版 PRD §15.2：NF9/NF10/NF11/NF14）。

用法：python scripts/load_test.py
做法：独立临时库 + 真实 uvicorn 子进程（端口 8899，测完自动回收），
12 个并发学生会话（会话直接建库——压的是并发会话处理能力，不是登录接口；
登录限流 NF5 是独立验收项，不走登录路径避免互相干扰）。
指标口径：
- NF9  首屏关键 API（session/presets/tasks/graph overview）p95 ≤ 3s
- NF10 Agent 首事件（POST /api/runs → SSE 首帧）p95 ≤ 2s（模板合成离线口径）
- NF11 RAG 召回（/api/rag/query 端到端，含模板生成）p95 ≤ 1s
- NF14 12 并发学生各自完成 运行+问答+图谱+任务 全序列，成功率 ≥ 100%（10+ 教学会话）
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"
STUDENTS = 12

sys.path.insert(0, str(REPO / "server"))
from bhzd_py import db as db_module  # noqa: E402
from bhzd_py.config import reset_config_cache  # noqa: E402
from bhzd_py.security import generate_token, hash_token  # noqa: E402
from bhzd_py.seed.loader import run_seed  # noqa: E402

results: dict[str, list[float]] = {}
failures: list[str] = []
_lock = threading.Lock()


@contextmanager
def isolated_runtime() -> Iterator[None]:
    """Run against disposable paths without leaking test config into a caller process."""
    env_names = ("BHZD_DATABASE_PATH", "BHZD_UPLOAD_DIR")
    original_environment = {name: os.environ.get(name) for name in env_names}
    with tempfile.TemporaryDirectory(prefix="bhzd-load-") as temporary_root:
        root = Path(temporary_root)
        # The load run must never seed the developer's persistent var/ database or uploads.
        os.environ["BHZD_DATABASE_PATH"] = str(root / "load.sqlite")
        os.environ["BHZD_UPLOAD_DIR"] = str(root / "uploads")
        reset_config_cache()
        try:
            yield
        finally:
            # Restoring both values and the cached settings keeps repeated in-process calls isolated.
            for name, value in original_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            reset_config_cache()


def record(metric: str, seconds: float) -> None:
    with _lock:
        results.setdefault(metric, []).append(seconds)


def make_load_users() -> list[tuple[str, str]]:
    """直接建 12 个学生 + 会话（返回 (email, cookie_token)），绕过登录限流。"""
    conn = db_module.connect(os.environ["BHZD_DATABASE_PATH"])
    now = db_module.utc_now_iso()
    users = []
    for i in range(STUDENTS):
        uid = uuid.uuid4().hex
        email = f"load{i}@demo.bhzd"
        conn.execute(
            "INSERT INTO users (id, email, name, role, status, email_verified_at, created_at, updated_at) "
            "VALUES (?, ?, ?, 'student', 'active', ?, ?, ?)",
            (uid, email, f"压测学生{i}", now, now, now),
        )
        token, csrf = generate_token(), generate_token()
        conn.execute(
            "INSERT INTO user_sessions (id, user_id, token_hash, csrf_token_hash, csrf_token, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, uid, hash_token(token), hash_token(csrf), csrf,
             now, "2099-01-01T00:00:00+00:00"),
        )
        users.append((email, token, csrf))
    conn.commit()
    conn.close()
    return users


def wait_health(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("backend not ready")


def student_flow(email: str, token: str, csrf: str) -> None:
    """单个学生的完整教学会话序列，逐项记录耗时。"""
    c = httpx.Client(
        base_url=BASE,
        cookies={"bhzd_session": token},
        headers={"x-csrf-token": csrf},
        timeout=30,
    )
    try:
        # NF9：首屏关键 API
        for path, name in [("/api/auth/session", "nf9.session"), ("/api/presets", "nf9.presets"),
                           ("/api/tasks", "nf9.tasks"), ("/api/graph/overview", "nf9.graph")]:
            t0 = time.perf_counter()
            r = c.get(path)
            dt = time.perf_counter() - t0
            if r.status_code != 200:
                failures.append(f"{email} {name} http {r.status_code}")
            record(name, dt)

        # NF10：Agent 首事件（POST → SSE 首帧）
        t0 = time.perf_counter()
        r = c.post("/api/runs", json={"input": "我想学车载唤醒词标注"})
        run_id = r.json()["run_id"]
        with c.stream("GET", f"/api/runs/{run_id}/events?after_seq=0") as s:
            first_event_at = None
            for line in s.iter_lines():
                if line.startswith("event: "):
                    first_event_at = time.perf_counter() - t0
                    break
        record("nf10.first_event", first_event_at or 99.0)
        # 等运行到等待确认/完成，避免悬挂运行占用后续请求
        deadline = time.time() + 25
        while time.time() < deadline:
            st = c.get(f"/api/runs/{run_id}").json()["run"]["status"]
            if st in ("waiting_confirmation", "completed", "failed"):
                break
            time.sleep(0.3)

        # NF11：RAG 召回
        t0 = time.perf_counter()
        r = c.post("/api/rag/query", json={"question": "唤醒词标注的边界容差是多少？"})
        record("nf11.rag_query", time.perf_counter() - t0)
        if r.status_code != 200:
            failures.append(f"{email} rag_query http {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{email} flow exception: {exc!r}")
    finally:
        c.close()


def pct(values: list[float], q: float) -> float:
    return statistics.quantiles(values, n=100)[q - 1] if len(values) >= 2 else (values[0] if values else float("nan"))


def _run_load() -> int:
    print("== 种子 + 建压测用户 ==")
    run_seed(demo=True)
    users = make_load_users()

    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "bhzd_py.app:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(REPO / "server"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_health()
        print(f"== {STUDENTS} 并发学生全序列 ==")
        t0 = time.time()
        threads = [threading.Thread(target=student_flow, args=u) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.time() - t0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Windows can retain SQLite file handles until the child is fully gone.
                proc.kill()
                proc.wait()

    print(f"\n并发墙钟时间: {wall:.1f}s，异常数: {len(failures)}")
    for f in failures[:10]:
        print("  FAIL:", f)

    gates = [
        ("nf9.session", 3.0, "NF9 首屏会话 API"),
        ("nf9.presets", 3.0, "NF9 首屏预设 API"),
        ("nf9.tasks", 3.0, "NF9 首屏任务 API"),
        ("nf9.graph", 3.0, "NF9 图谱全图 API"),
        ("nf10.first_event", 2.0, "NF10 Agent 首事件"),
        ("nf11.rag_query", 1.0, "NF11 RAG 召回"),
    ]
    print(f"\n{'指标':<28}{'样本':>4}{'p50':>9}{'p95':>9}{'阈值':>8}  结论")
    all_ok = not failures
    for metric, threshold, label in gates:
        vs = results.get(metric, [])
        if not vs:
            print(f"{label:<28}无样本")
            all_ok = False
            continue
        p50, p95 = statistics.median(vs), pct(vs, 95)
        ok = p95 <= threshold
        all_ok = all_ok and ok
        print(f"{label:<28}{len(vs):>4}{p50:>8.3f}s{p95:>8.3f}s{p95 and threshold:>7.1f}s  {'PASS' if ok else 'FAIL'}")
    nf14 = len(failures) == 0
    print(f"{'NF14 并发会话成功率':<28}{STUDENTS - len(set(f.split()[0] for f in failures))}/{STUDENTS}  {'PASS' if nf14 else 'FAIL'}")
    print(f"\n== 汇总: {'全部达标' if all_ok else '存在未达标项'} ==")
    return 0 if all_ok else 1


def main() -> int:
    """Own the temporary directory for the full load-test lifecycle."""
    with isolated_runtime():
        return _run_load()


if __name__ == "__main__":
    raise SystemExit(main())
