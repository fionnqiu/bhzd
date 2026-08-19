/**
 * 系统状态（/admin/security）——当前告警与可观测运行指标。
 *
 * 为什么告警置顶：失败率/超时率类告警是"正在发生"的运行时风险，优先级高于
 * 静态策略说明；告警由 GET /api/admin/alerts 实时评估，忽略状态按管理员保存，
 * 管理端打开本页或手动刷新即完成一次评估闭环。
 *
 * 运行时指标也保持只读：页面展示后端实际返回的登录、会话、API 与供应商数据，
 * 不把无法在线修改的安全策略伪装成可配置板块。
 */

import { EyeOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { MetricsResponse } from "../../api/types";
import { Button, Card, PageHeader, Spinner, Tag } from "../../components";
import { errText, fmtTime } from "./adminShared";

/** 系统告警项（GET /api/admin/alerts；服务端为当前管理员附加稳定指纹）。 */
interface SystemAlert {
  code: string;
  fingerprint: string;
  level: "critical" | "warning" | string;
  message: string;
  metric: string;
  threshold: number;
  current: number;
  since?: string;
}

/** 告警级别 → 中文徽章（critical 红 / warning 黄；未知级别中性色兜底） */
const LEVEL_META: Record<string, { label: string; tone: string }> = {
  critical: { label: "严重", tone: "danger" },
  warning: { label: "警告", tone: "warning" },
};

/**
 * 阈值/当前值格式化：指标名含 rate 的是 0-1 比率（如失败率 0.5），按百分比
 * 展示更可读；计数类（连续失败次数等）原样展示整数。
 */
function fmtAlertValue(metric: string, value: number): string {
  if (metric.includes("rate")) return `${(value * 100).toFixed(1)}%`;
  return String(value);
}

function fmtRate(value: number | null): string {
  return value === null ? "暂无样本" : `${(value * 100).toFixed(1)}%`;
}

function fmtLatency(value: number | null): string {
  return value === null ? "暂无样本" : `${value.toFixed(2)} ms`;
}


export default function SecurityPage() {
  // 系统告警：null 表示尚未加载完成（区分"加载中"与"无告警"两种空白）
  const [alerts, setAlerts] = useState<SystemAlert[] | null>(null);
  const [evaluatedAt, setEvaluatedAt] = useState<string | null>(null);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [ignoringFingerprint, setIgnoringFingerprint] = useState<string | null>(null);
  const [ignoreError, setIgnoreError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [metricsError, setMetricsError] = useState<string | null>(null);

  /** 拉取实时告警评估；服务端按当前管理员过滤已忽略的活动告警。 */
  const loadAlerts = useCallback(async (signal?: AbortSignal) => {
    setAlertsLoading(true);
    setAlertsError(null);
    setIgnoreError(null);
    try {
      const res = await api.get<{ alerts: SystemAlert[]; evaluated_at: string }>(
        "/api/admin/alerts",
        undefined,
        { signal },
      );
      if (signal?.aborted) return;
      setAlerts(res.alerts);
      setEvaluatedAt(res.evaluated_at);
    } catch (err) {
      if (!signal?.aborted) setAlertsError(errText(err, "系统告警加载失败"));
    } finally {
      if (!signal?.aborted) setAlertsLoading(false);
    }
  }, []);

  /** Runtime metrics are read-only snapshots; null rates mean no telemetry, not zero success. */
  const loadMetrics = useCallback(async (signal?: AbortSignal) => {
    setMetricsLoading(true);
    setMetricsError(null);
    try {
      const res = await api.get<MetricsResponse>("/api/admin/metrics", undefined, { signal });
      if (signal?.aborted) return;
      setMetrics(res);
    } catch (err) {
      if (!signal?.aborted) setMetricsError(errText(err, "运行时指标加载失败"));
    } finally {
      if (!signal?.aborted) setMetricsLoading(false);
    }
  }, []);

  /**
   * 隐藏当前管理员已确认的活动告警。服务端持久化忽略状态，前端同步移除
   * 卡片，避免一次成功操作还要等待下一次刷新才能反映结果。
   */
  const ignoreAlert = useCallback(async (alert: SystemAlert) => {
    setIgnoringFingerprint(alert.fingerprint);
    setIgnoreError(null);
    try {
      await api.post(`/api/admin/alerts/${encodeURIComponent(alert.fingerprint)}/ignore`);
      setAlerts(
        (current) => current?.filter((item) => item.fingerprint !== alert.fingerprint) ?? current,
      );
    } catch (err) {
      setIgnoreError(errText(err, "系统告警忽略失败"));
    } finally {
      setIgnoringFingerprint(null);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadAlerts(controller.signal);
    return () => controller.abort();
  }, [loadAlerts]);

  useEffect(() => {
    const controller = new AbortController();
    void loadMetrics(controller.signal);
    return () => controller.abort();
  }, [loadMetrics]);

  return (
    <div>
      <PageHeader
        title="系统状态"
      />

      {/* 系统告警（PRD-06 §13.2）：触发中的告警逐条展示，健康时为绿色"当前无告警" */}
      <Card
        title="系统告警"
        className="mb-4"
        actions={
          <Button
            size="sm"
            variant="secondary"
            loading={alertsLoading}
            onClick={() => void loadAlerts()}
          >
            刷新
          </Button>
        }
      >
        {alertsError ? (
          <p className="form-alert form-alert-error" role="alert">
            {alertsError}
          </p>
        ) : ignoreError ? (
          <p className="form-alert form-alert-error" role="alert">
            {ignoreError}
          </p>
        ) : alerts === null ? (
          <p className="text-sm text-muted flex items-center gap-2">
            <Spinner size={14} /> 正在评估告警指标…
          </p>
        ) : alerts.length === 0 ? (
          <p className="form-alert form-alert-success" role="status">
            当前无告警：全部监控指标处于阈值内。
          </p>
        ) : (
          <div className="grid grid-cols-2">
            {alerts.map((alert) => {
              const meta = LEVEL_META[alert.level] ?? { label: alert.level, tone: "neutral" };
              return (
                <div
                  key={alert.fingerprint}
                  style={{
                    border: "1px solid var(--color-border)",
                    borderRadius: "var(--radius-md)",
                    padding: "var(--space-3)",
                  }}
                >
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <strong className="text-sm">{alert.message}</strong>
                    <div className="flex items-center gap-2">
                      <span className={`badge badge-${meta.tone}`}>{meta.label}</span>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={ignoringFingerprint === alert.fingerprint}
                        onClick={() => void ignoreAlert(alert)}
                        title="忽略此告警（仅当前管理员）"
                      >
                        <EyeOff size={14} aria-hidden />
                        忽略
                      </Button>
                    </div>
                  </div>
                  <p className="text-xs text-secondary">
                    {`指标 ${alert.metric} · 阈值 ${fmtAlertValue(alert.metric, alert.threshold)} · 当前值 ${fmtAlertValue(alert.metric, alert.current)}`}
                  </p>
                  {alert.since ? (
                    <p className="text-xs text-muted mt-2">统计窗口起点：{fmtTime(alert.since)}</p>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
        {evaluatedAt ? (
          <p className="text-xs text-muted mt-2">
            评估时间：{fmtTime(evaluatedAt)}（实时评估；忽略仅对当前管理员生效，点击刷新重新评估）
          </p>
        ) : null}
      </Card>

      <Card
        title="运行时指标"
        className="mb-4"
        actions={
          <Button
            size="sm"
            variant="secondary"
            loading={metricsLoading}
            onClick={() => void loadMetrics()}
          >
            刷新
          </Button>
        }
      >
        {metricsError ? (
          <p className="form-alert form-alert-error" role="alert">
            {metricsError}
          </p>
        ) : metrics === null ? (
          <p className="text-sm text-muted flex items-center gap-2">
            <Spinner size={14} /> 正在加载运行时指标…
          </p>
        ) : (
          <>
            <div className="grid grid-cols-4">
              <div>
                <span className="text-xs text-muted">今日登录</span>
                <strong className="block mt-1">
                  成功 {metrics.metrics.login_success_today} · 失败 {metrics.metrics.login_failure_today}
                </strong>
              </div>
              <div>
                <span className="text-xs text-muted">当前活跃会话</span>
                <strong className="block mt-1">{metrics.metrics.active_sessions}</strong>
              </div>
              <div>
                <span className="text-xs text-muted">API 成功率（24h）</span>
                <strong className="block mt-1">{fmtRate(metrics.metrics.api_success_rate_24h)}</strong>
              </div>
              <div>
                <span className="text-xs text-muted">Provider 延迟（最近测试）</span>
                <strong className="block mt-1">{fmtLatency(metrics.metrics.provider_latency_avg_ms)}</strong>
              </div>
            </div>
            <p className="text-xs text-muted mt-3">{metrics.note}</p>
          </>
        )}
      </Card>

    </div>
  );
}
