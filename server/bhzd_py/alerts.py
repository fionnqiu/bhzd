"""告警评估（PRD-06 §13.2）：从真实数据表按阈值计算告警，供管理端拉取。

为什么同步按需计算而不是后台推送：MVP 没有告警通道（邮件/webhook 均未配），
`GET /api/admin/alerts` 实时算一遍就是最小可用闭环；每项评估都带
try/except 防御——缺表/缺字段/数据形状不符时跳过该项并记日志，而不是让
整个接口 500（告警接口自身的可用性必须高于被监控对象）。

所有"率"类告警都有最小样本量：低流量期分母太小，零星失败就会把比率顶过
阈值造成误报，样本不足一律不告警。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import get_config
from .security import decrypt_secret, load_encryption_key

logger = logging.getLogger(__name__)

# ---- 阈值常数（PRD-06 §13.2 建议值；样本量下限是为防抖补充的工程口径）----
AGENT_RUN_WINDOW_MIN = 5          # Agent 运行失败率：5 分钟窗口
AGENT_RUN_MIN_SAMPLE = 10
AGENT_RUN_FAILURE_RATE = 0.10
RECALL_WINDOW_MIN = 10            # RAG 召回超时率：10 分钟窗口
RECALL_MIN_SAMPLE = 10
RECALL_TIMEOUT_RATE = 0.10
# PRD 只说"超时"未给毫秒线；本地混合召回正常在几十毫秒内，取 2s 为可调口径
RECALL_TIMEOUT_MS = 2000
PARSE_WINDOW_HOURS = 24           # 文档解析失败率：单日窗口
PARSE_MIN_SAMPLE = 5
PARSE_FAILURE_RATE = 0.20
PROVIDER_CONSECUTIVE_FAILURES = 3  # 模型连接连续失败次数


def evaluate_alerts(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """评估全部告警项，返回触发中的告警列表（健康时为空列表）。"""
    now = datetime.now(timezone.utc)
    alerts: list[dict[str, Any]] = []
    alerts.extend(_agent_run_alerts(db, now))
    alerts.extend(_recall_timeout_alerts(db, now))
    alerts.extend(_parse_failure_alerts(db, now))
    alerts.extend(_provider_test_alerts(db))
    alerts.extend(_api_key_decrypt_alerts(db))
    return alerts


def _agent_run_alerts(db: sqlite3.Connection, now: datetime) -> list[dict]:
    """Agent 运行失败率：5 分钟内失败占比 >10%（样本 ≥10 才评估）。"""
    since = (now - timedelta(minutes=AGENT_RUN_WINDOW_MIN)).isoformat()
    try:
        row = db.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed"
            " FROM agent_runs WHERE created_at >= ?",
            (since,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("Agent 运行失败率告警评估跳过：%s", exc)
        return []
    total, failed = (row["total"] or 0), (row["failed"] or 0)
    if total < AGENT_RUN_MIN_SAMPLE:
        return []
    rate = failed / total
    if rate <= AGENT_RUN_FAILURE_RATE:
        return []
    return [
        {
            "code": "AGENT_RUN_FAILURE_RATE",
            "level": "critical",
            "message": (
                f"近 {AGENT_RUN_WINDOW_MIN} 分钟 Agent 运行失败率 {rate:.0%}"
                f"（{failed}/{total} 次失败），超过阈值 {AGENT_RUN_FAILURE_RATE:.0%}，"
                "请检查模型供应商配置与网络"
            ),
            "metric": "agent_run_failure_rate_5m",
            "threshold": AGENT_RUN_FAILURE_RATE,
            "current": round(rate, 4),
            "since": since,
        }
    ]


def _recall_timeout_alerts(db: sqlite3.Connection, now: datetime) -> list[dict]:
    """RAG 召回超时率：10 分钟内超时（latency_ms 超线）占比 >10%。

    数据源说明：独立的 recall_logs 表不存在，召回延迟实际由埋点事件
    rag_retrieval_completed 的 props.latency_ms 承载（Agent 工具链路上报）；
    没有 latency_ms 属性的事件不计入样本（老口径事件只有 hit_count）。
    """
    since = (now - timedelta(minutes=RECALL_WINDOW_MIN)).isoformat()
    try:
        rows = db.execute(
            "SELECT props_json FROM analytics_events"
            " WHERE event_name = 'rag_retrieval_completed' AND created_at >= ?",
            (since,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("RAG 召回超时率告警评估跳过：%s", exc)
        return []
    latencies: list[float] = []
    for row in rows:
        try:
            props = json.loads(row["props_json"] or "{}")
        except json.JSONDecodeError:
            continue
        value = props.get("latency_ms")
        if isinstance(value, (int, float)):
            latencies.append(float(value))
    if len(latencies) < RECALL_MIN_SAMPLE:
        return []
    timeouts = sum(1 for v in latencies if v > RECALL_TIMEOUT_MS)
    rate = timeouts / len(latencies)
    if rate <= RECALL_TIMEOUT_RATE:
        return []
    return [
        {
            "code": "RAG_RECALL_TIMEOUT_RATE",
            "level": "warning",
            "message": (
                f"近 {RECALL_WINDOW_MIN} 分钟 RAG 召回超时率 {rate:.0%}"
                f"（{timeouts}/{len(latencies)} 次超过 {RECALL_TIMEOUT_MS}ms），"
                f"超过阈值 {RECALL_TIMEOUT_RATE:.0%}，请检查嵌入服务与索引规模"
            ),
            "metric": "rag_recall_timeout_rate_10m",
            "threshold": RECALL_TIMEOUT_RATE,
            "current": round(rate, 4),
            "since": since,
        }
    ]


def _parse_failure_alerts(db: sqlite3.Connection, now: datetime) -> list[dict]:
    """文档解析失败率：单日 parse 阶段任务失败占比 >20%（样本 ≥5）。"""
    since = (now - timedelta(hours=PARSE_WINDOW_HOURS)).isoformat()
    try:
        row = db.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed"
            " FROM rag_jobs WHERE stage = 'parse' AND created_at >= ?",
            (since,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("文档解析失败率告警评估跳过：%s", exc)
        return []
    total, failed = (row["total"] or 0), (row["failed"] or 0)
    if total < PARSE_MIN_SAMPLE:
        return []
    rate = failed / total
    if rate <= PARSE_FAILURE_RATE:
        return []
    return [
        {
            "code": "DOC_PARSE_FAILURE_RATE",
            "level": "warning",
            "message": (
                f"近 24 小时文档解析失败率 {rate:.0%}（{failed}/{total} 个任务失败），"
                f"超过阈值 {PARSE_FAILURE_RATE:.0%}，请检查上传文件格式与解析器"
            ),
            "metric": "doc_parse_failure_rate_1d",
            "threshold": PARSE_FAILURE_RATE,
            "current": round(rate, 4),
            "since": since,
        }
    ]


def _provider_test_alerts(db: sqlite3.Connection) -> list[dict]:
    """模型连接连续失败：同一 provider 的连通性测试最近连续失败 ≥3 次。

    provider_configs.last_test_json 只存最近一次结果，判断"连续"需要历史，
    因此读 provider.test 审计流水（每次测试必写审计，是天然的历史记录）。
    """
    try:
        rows = db.execute(
            "SELECT target_id, after_json FROM audit_logs"
            " WHERE action = 'provider.test' ORDER BY created_at DESC"
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("模型连接失败告警评估跳过：%s", exc)
        return []
    # 按时间倒序累计每个 provider 的"尾部连续失败"段，遇到成功/不可判读即截断
    streaks: dict[str, int] = {}
    closed: set[str] = set()
    for row in rows:
        pid = row["target_id"]
        if pid in closed:
            continue
        ok: bool | None = None
        try:
            ok = bool(json.loads(row["after_json"] or "{}").get("ok"))
        except json.JSONDecodeError:
            ok = None
        if ok is False:
            streaks[pid] = streaks.get(pid, 0) + 1
        else:
            closed.add(pid)
    alerts: list[dict[str, Any]] = []
    for pid, streak in streaks.items():
        if streak < PROVIDER_CONSECUTIVE_FAILURES:
            continue
        name_row = db.execute(
            "SELECT name FROM provider_configs WHERE id = ?", (pid,)
        ).fetchone()
        name = name_row["name"] if name_row else pid
        alerts.append(
            {
                "code": "PROVIDER_CONN_FAILURE",
                "target_id": pid,
                "level": "critical",
                "message": (
                    f"模型供应商「{name}」连接测试已连续失败 {streak} 次"
                    f"（阈值 {PROVIDER_CONSECUTIVE_FAILURES} 次），"
                    "主备链路可能均不可用，请立即检查密钥与网络"
                ),
                "metric": "provider_consecutive_test_failures",
                "threshold": PROVIDER_CONSECUTIVE_FAILURES,
                "current": streak,
            }
        )
    return alerts


def _api_key_decrypt_alerts(db: sqlite3.Connection) -> list[dict]:
    """API Key 解密失败：逐个尝试解密启用中的 provider 密钥，任意失败即告警。"""
    try:
        rows = db.execute(
            "SELECT id, name, api_key_encrypted FROM provider_configs WHERE enabled = 1"
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("API Key 解密告警评估跳过：%s", exc)
        return []
    if not rows:
        return []
    try:
        key = load_encryption_key(get_config().config_encryption_key or None)
    except Exception:
        # 密钥配置本身非法：所有启用中的 provider 都不可能解开，直接整体告警
        return [
            {
                "code": "API_KEY_DECRYPT_FAILURE",
                "level": "critical",
                "message": (
                    "配置加密密钥（BHZD_CONFIG_ENCRYPTION_KEY）不可用，"
                    f"{len(rows)} 个启用中的供应商 API Key 均无法解密，请检查密钥配置"
                ),
                "metric": "api_key_decrypt_failures",
                "threshold": 0,
                "current": len(rows),
            }
        ]
    failed_names: list[str] = []
    for row in rows:
        try:
            decrypt_secret(row["api_key_encrypted"], key)
        except Exception:
            # 密钥错乱/密文被改/密钥轮换后旧密文：明文永不出现在日志与告警里
            failed_names.append(row["name"])
    if not failed_names:
        return []
    shown = "、".join(f"「{n}」" for n in failed_names[:3])
    return [
        {
            "code": "API_KEY_DECRYPT_FAILURE",
            "level": "critical",
            "message": (
                f"有 {len(failed_names)} 个启用中的供应商 API Key 解密失败（{shown}），"
                "加密密钥可能已轮换，请重新录入对应密钥"
            ),
            "metric": "api_key_decrypt_failures",
            "threshold": 0,
            "current": len(failed_names),
        }
    ]
