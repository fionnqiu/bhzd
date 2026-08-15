"""SQLite 连接助手与迁移执行器（蓝图 §5 契约的落实点）。

关键决策（为什么）：
- 用标准库 sqlite3 而非 ORM：蓝图 §1 明确"sqlite3 标准库 + SQL 迁移文件"。
- 迁移文件带 sha256 校验：已应用的迁移若被篡改（哪怕是格式化差异）直接拒绝
  启动，防止"线上库与迁移文件漂移"这类难以排查的事故。
- WAL + foreign_keys=ON：WAL 提升并发读写体验；SQLite 默认不开外键，必须
  每连接显式开启，否则 REFERENCES 约束形同虚设。
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class MigrationError(RuntimeError):
    """迁移失败（含已应用文件被篡改）。"""


def utc_now_iso() -> str:
    """UTC ISO8601 字符串（蓝图 §4 时间约定；统一格式保证可字典序比较）。"""
    return datetime.now(timezone.utc).isoformat()


def connect(database_path: str) -> sqlite3.Connection:
    """打开一个配置好的 SQLite 连接（调用方负责关闭）。

    check_same_thread=False 的原因：FastAPI 的同步生成器依赖（deps.get_db）在
    anyio 线程池建连，而 async 端点在事件循环线程使用、依赖清理又可能落到另一个
    线程池线程——sqlite3 默认限制单线程使用会在真实服务器（非 TestClient）下
    间歇性抛 ProgrammingError 造成 500。同一请求生命周期内连接的访问是严格
    串行的（建连→端点→关闭依次发生），不存在真并发访问，故关闭该限制是安全的；
    跨请求并发由"每请求独立连接 + WAL"承担。
    """
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    # Detached content workers and request handlers can briefly contend for
    # SQLite's single-writer slot.  A bounded busy timeout lets the second
    # writer wait for the first commit instead of surfacing a transient 500.
    conn = sqlite3.connect(database_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    # Setting WAL on every connection is itself a locking operation.  Read the
    # current mode first and only switch freshly-created databases; this keeps
    # request/worker connections from competing with a long-lived read cursor.
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if str(journal_mode).lower() != "wal":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(
    conn: sqlite3.Connection, *, immediate: bool = False
) -> Iterator[sqlite3.Connection]:
    """事务上下文：正常结束提交，异常回滚并继续抛出。"""
    try:
        # Reserve the writer slot before read-then-write fan-out when requested;
        # this avoids stale WAL snapshots failing their later write upgrade.
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          name TEXT PRIMARY KEY,
          sha256 TEXT NOT NULL,
          applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: str | Path | None = None,
) -> list[str]:
    """按文件名顺序应用 `migrations/*.sql`，返回本次新应用的迁移名列表。

    已应用的迁移会校验 sha256：不一致说明文件被改动过，直接抛
    `MigrationError` 拒绝继续（宁停不错）。
    """
    directory = Path(migrations_dir) if migrations_dir else MIGRATIONS_DIR
    _ensure_migrations_table(conn)
    applied_rows = {
        row["name"]: row["sha256"]
        for row in conn.execute("SELECT name, sha256 FROM schema_migrations")
    }
    newly_applied: list[str] = []
    for sql_file in sorted(directory.glob("*.sql")):
        digest = _sha256_file(sql_file)
        if sql_file.name in applied_rows:
            if applied_rows[sql_file.name] != digest:
                raise MigrationError(
                    f"迁移文件 {sql_file.name} 的 sha256 与已应用记录不一致，"
                    "文件可能被篡改；已拒绝继续执行。"
                )
            continue
        # 每个迁移在独立事务中执行，失败时不留半截 schema。
        # 注意：sqlite3 的 executescript 会先隐式提交挂起事务、且不再做任何
        # 事务控制，因此 BEGIN/COMMIT 必须写进脚本本体才能包住整段 DDL。
        script = sql_file.read_text(encoding="utf-8")
        try:
            conn.executescript(f"BEGIN;\n{script}\nCOMMIT;")
            conn.execute(
                "INSERT INTO schema_migrations (name, sha256, applied_at) VALUES (?, ?, ?)",
                (sql_file.name, digest, utc_now_iso()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        newly_applied.append(sql_file.name)
    return newly_applied
