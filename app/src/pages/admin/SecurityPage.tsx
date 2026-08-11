/**
 * 安全配置（/admin/security）——系统告警 + 安全策略只读视图（PRD-04 §6 / PRD-06 §13.2）。
 *
 * 为什么告警置顶：失败率/超时率类告警是"正在发生"的运行时风险，优先级高于
 * 静态策略说明；告警由 GET /api/admin/alerts 实时评估，忽略状态按管理员保存，
 * 管理端打开本页或手动刷新即完成一次评估闭环。
 *
 * 下半部分仍是纯静态策略页：首期安全策略全部内置于后端常量（security.py /
 * deps.py / 蓝图 §4），没有配置端点；页面如实展示"已启用"状态与机制说明，
 * 不虚构开关让管理员误以为可以在此修改。数值（5 次/分钟、10 次锁 15 分钟）
 * 与 security.py 常量逐一核对过。
 */

import { EyeOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
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

interface Policy {
  name: string;
  nf: string;
  desc: string;
}

/** 策略清单（事实来源：security.py / deps.py / admin.py / 蓝图 §4） */
const POLICIES: Policy[] = [
  {
    name: "登录限流",
    nf: "NF5",
    desc: "同一 IP 每分钟最多 5 次登录尝试（成功失败都计数），超出返回限流提示。",
  },
  {
    name: "失败锁定",
    nf: "NF5",
    desc: "同一账号连续失败 10 次锁定 15 分钟，锁定期间即使密码正确也拒绝登录。",
  },
  {
    name: "CSRF 防护",
    nf: "NF5",
    desc: "全部变更类请求必须携带 x-csrf-token（登录后由会话签发并轮换），缺失或失效即 403。",
  },
  {
    name: "会话隔离",
    nf: "NF4",
    desc: "学生/教师端与系统管理端使用两套独立 Cookie（bhzd_session / bhzd_admin_session），/api/admin/* 仅认管理端会话。",
  },
  {
    name: "密码存储",
    nf: "NF1",
    desc: "密码使用 Argon2id 哈希存储，任何接口与日志不输出明文或哈希。",
  },
  {
    name: "API Key 加密",
    nf: "NF2",
    desc: "供应商 API Key 使用 AES-256-GCM 加密落库；编辑时仅显示固定掩码，可留空复用已保存密钥；明文不进日志与审计快照。",
  },
  {
    name: "诊断原文件不持久化",
    nf: "NF3",
    desc: "学生上传的诊断文件仅在请求内存中解析，不写入磁盘；只保存用户确认后的诊断摘要。",
  },
  {
    name: "base_url 安全校验",
    nf: "NF9",
    desc: "供应商 base_url 拒绝本机、内网与云元数据地址，防止 API Key 被转发到内网服务（SSRF 防线）。",
  },
  {
    name: "资料授权强制登记",
    nf: "NF6",
    desc: "RAG 上传必须填写授权状态与来源，未填不得上传；禁止/待确认状态不能发布。",
  },
  {
    name: "未发布资料隔离",
    nf: "NF7",
    desc: "学生端召回强制 published_only：未发布、已归档、已过期资料永不进入学生召回。",
  },
  {
    name: "审计覆盖",
    nf: "NF8",
    desc: "审核、发布、归档、删除、权限变更、模型配置变更、RAG 参数修改全部写入审计日志，且不允许删除。",
  },
];

export default function SecurityPage() {
  // 系统告警：null 表示尚未加载完成（区分"加载中"与"无告警"两种空白）
  const [alerts, setAlerts] = useState<SystemAlert[] | null>(null);
  const [evaluatedAt, setEvaluatedAt] = useState<string | null>(null);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [ignoringFingerprint, setIgnoringFingerprint] = useState<string | null>(null);
  const [ignoreError, setIgnoreError] = useState<string | null>(null);

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

  return (
    <div>
      <PageHeader
        title="安全配置"
        sub="系统告警实时评估置顶展示；每位管理员可单独忽略活动告警，恢复后重新显示"
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

      <p className="form-alert form-alert-success mb-4">
        以下策略均为系统内置常量（PRD-04 §6 / NF1-NF9），随服务启动生效，无需也无法在页面修改。
      </p>
      <div className="grid grid-cols-3">
        {POLICIES.map((policy) => (
          <Card key={policy.name}>
            <div className="flex items-center justify-between mb-2">
              <strong>{policy.name}</strong>
              <span className="flex gap-1 items-center">
                <Tag>{policy.nf}</Tag>
                <span className="badge badge-success">已启用</span>
              </span>
            </div>
            <p className="text-sm text-secondary">{policy.desc}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}
