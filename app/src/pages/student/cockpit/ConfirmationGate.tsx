/**
 * 确认门（PRD-06 §6.4 / PRD-01 §3.6：创建任务、保存诊断、更新掌握度必须出现）。
 *
 * 预览内容按 action_type 分派渲染（后端 preview 载荷形状见 tools/*_tools.py）：
 * - task.create → 任务卡摘要（名称/目标/步骤/关联能力）
 * - diagnostic.save_summary → 错误数/薄弱能力/掌握度 old→new
 * - mastery.update → 每项能力 old→new 对比条
 * 过期倒计时来自 expires_at（ISO）；过期后禁用按钮，引导重新生成预览。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Card, ProgressBar } from "../../../components";
import type { Confirmation, MasteryChange, TaskStep } from "../../../api/types";
import { actionLabel, dataTypeLabel } from "./constants";

interface TaskCardPreview {
  title?: string;
  goal?: string;
  data_type?: string | null;
  est_minutes?: number;
  steps?: TaskStep[];
  cap_names?: { cap_id: string; name: string }[];
}

interface DiagnosticSummaryPreview {
  error_count?: number;
  severity_counts?: { major?: number; minor?: number };
  weak_cap_ids?: string[];
  mastery_preview?: MasteryChange[];
}

interface MasteryUpdateItem {
  cap_id: string;
  old_score?: number | null;
  new_score?: number | null;
  source?: string;
}

function pct(score: number | null | undefined): number {
  return Math.round((score ?? 0) * 100);
}

/** 掌握度 old→new 行（确认门与诊断保存确认共用） */
export function MasteryChangeRow({ change }: { change: MasteryChange | MasteryUpdateItem }) {
  const oldScore = "old_score" in change ? change.old_score : null;
  const newScore = "new_score" in change ? change.new_score : null;
  return (
    <div className="mastery-change-row">
      <span className="mastery-change-cap">{change.cap_id}</span>
      <div className="mastery-change-bars">
        <ProgressBar value={pct(oldScore)} tone="warning" />
        <span className="text-xs text-muted">
          {pct(oldScore)}% → {pct(newScore)}%
        </span>
        <ProgressBar value={pct(newScore)} tone="success" />
      </div>
    </div>
  );
}

/** 预览内容（确认门内联卡与右栏确认门共用，避免两处翻译不一致） */
export function ConfirmationPreview({ confirmation }: { confirmation: Confirmation }) {
  const preview = (confirmation.preview ?? {}) as Record<string, unknown>;
  const summaryText = typeof preview.summary === "string" ? preview.summary : null;
  const action = confirmation.action_type;

  if (action === "task.create") {
    const card = (preview.card ?? {}) as TaskCardPreview;
    return (
      <div className="confirm-preview">
        {summaryText ? <p>{summaryText}</p> : null}
        <dl className="confirm-fields">
          <dt>任务名称</dt>
          <dd>{card.title ?? "标注练习任务"}</dd>
          <dt>学习目标</dt>
          <dd>{card.goal ?? "—"}</dd>
          <dt>数据类型</dt>
          <dd>{dataTypeLabel(card.data_type)}</dd>
          <dt>任务步骤</dt>
          <dd>
            <ol className="confirm-steps">
              {(card.steps ?? []).map((s, i) => (
                <li key={i}>{s.title}</li>
              ))}
            </ol>
          </dd>
          <dt>关联能力</dt>
          <dd>
            {card.cap_names?.length
              ? card.cap_names.map((c) => c.name).join("、")
              : "—"}
          </dd>
          {card.est_minutes ? (
            <>
              <dt>预计时长</dt>
              <dd>约 {card.est_minutes} 分钟</dd>
            </>
          ) : null}
        </dl>
      </div>
    );
  }

  if (action === "diagnostic.save_summary") {
    const diag = (preview.diagnostic ?? {}) as DiagnosticSummaryPreview;
    return (
      <div className="confirm-preview">
        {summaryText ? <p>{summaryText}</p> : null}
        <p>
          共 {diag.error_count ?? 0} 个问题（严重 {diag.severity_counts?.major ?? 0} /
          轻微 {diag.severity_counts?.minor ?? 0}）
        </p>
        {diag.weak_cap_ids?.length ? (
          <p>薄弱能力：{diag.weak_cap_ids.join("、")}</p>
        ) : null}
        {diag.mastery_preview?.length ? (
          <div>
            <p className="text-sm text-muted">保存后掌握度变化：</p>
            {diag.mastery_preview.map((m) => (
              <MasteryChangeRow key={`${m.cap_id}|${m.scenario_id}`} change={m} />
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  if (action === "mastery.update") {
    const updates = (preview.updates ?? []) as MasteryUpdateItem[];
    return (
      <div className="confirm-preview">
        {summaryText ? <p>{summaryText}</p> : null}
        {updates.map((u) => (
          <MasteryChangeRow key={u.cap_id} change={u} />
        ))}
      </div>
    );
  }

  // 未识别的 action：展示后端给的 summary，不做臆测渲染
  return (
    <div className="confirm-preview">
      <p>{summaryText ?? "请确认以下写操作。"}</p>
    </div>
  );
}

/** 过期倒计时（普通写 30min，删除/归档 10min——时长由后端决定，这里只展示） */
function useCountdown(expiresAt: string): { text: string; expired: boolean } {
  const [state, setState] = useState(() => {
    const remain = new Date(expiresAt).getTime() - Date.now();
    if (Number.isNaN(remain)) return { text: "", expired: false };
    if (remain <= 0) return { text: "已过期", expired: true };
    return { text: "", expired: false };
  });
  useEffect(() => {
    const tick = () => {
      const remain = new Date(expiresAt).getTime() - Date.now();
      if (Number.isNaN(remain)) {
        setState({ text: "", expired: false });
      } else if (remain <= 0) {
        setState({ text: "已过期", expired: true });
      } else {
        const minutes = Math.floor(remain / 60000);
        const seconds = Math.floor((remain % 60000) / 1000);
        setState({
          text: `${minutes}:${String(seconds).padStart(2, "0")} 后过期`,
          expired: false,
        });
      }
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [expiresAt]);
  return state;
}

export interface ConfirmationGateProps {
  confirmation: Confirmation;
  confirming: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** Optional lifecycle hook for hosts that resolve expiry directly from the card. */
  onExpire?: () => void;
}

/** 右栏确认门：高亮卡片 + 预览 + 倒计时 + 确认/取消 */
export default function ConfirmationGate({
  confirmation,
  confirming,
  onConfirm,
  onCancel,
  onExpire,
}: ConfirmationGateProps) {
  const countdown = useCountdown(confirmation.expires_at);
  const expiredConfirmationId = useRef<string | null>(null);
  const title = useMemo(
    () => actionLabel(confirmation.action_type),
    [confirmation.action_type],
  );
  useEffect(() => {
    if (!countdown.expired || expiredConfirmationId.current === confirmation.id) return;
    // A timer may tick again before React removes the card.  Notify at most once
    // per confirmation so an expiry endpoint is never spammed by the UI.
    expiredConfirmationId.current = confirmation.id;
    onExpire?.();
  }, [confirmation.id, countdown.expired, onExpire]);
  return (
    <Card
      title={`待确认：${title}`}
      className="confirm-gate"
      data-testid="confirmation-gate"
    >
      <ConfirmationPreview confirmation={confirmation} />
      <p className="text-xs text-muted" role="timer">
        {countdown.text}
      </p>
      <div className="flex gap-2 mt-2">
        <Button
          size="sm"
          loading={confirming}
          disabled={countdown.expired}
          onClick={onConfirm}
        >
          确认
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={confirming || countdown.expired}
          onClick={onCancel}
        >
          取消
        </Button>
      </div>
      {countdown.expired ? (
        <p className="text-xs text-danger mt-2">预览已过期，请重新发起操作。</p>
      ) : null}
    </Card>
  );
}

/** 对话区内联确认卡：提示去右栏完成确认（PRD-01 §3.5 等待确认态） */
export function ConfirmationInlineHint({
  confirmation,
}: {
  confirmation: Confirmation;
}) {
  return (
    <Card
      title={`等待确认：${actionLabel(confirmation.action_type)}`}
      className="confirm-inline"
    >
      <ConfirmationPreview confirmation={confirmation} />
      <p className="text-sm text-muted mt-2">请在右侧确认门中确认或取消。</p>
    </Card>
  );
}
