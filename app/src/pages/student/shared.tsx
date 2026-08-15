/**
 * 学生端页面共享工具与小组件（F2 各页共用）。
 *
 * 为什么集中在这里：能力名解析（cap_id→中文名）、掌握度变化预览、埋点
 * 上报、各类 id → 中文文案映射横跨 7 个学生页；散在各页必然漂移，统一
 * 出口保证同一语义全站同文（与 StatusBadge 的集中化思路一致）。
 */
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { GraphOverview, MasteryChange } from "../../api/types";
import { masteryStatusOf, ProgressBar } from "../../components";

/* ---------------------------------------------------------------- 文案映射 */

/** 数据类型中文名（后端取值 text/image/audio/video/general；null 视为通用） */
export const DATA_TYPE_LABELS: Record<string, string> = {
  text: "文本",
  image: "图像",
  audio: "语音",
  video: "视频",
  general: "通用",
};

export function dataTypeLabel(dataType: string | null | undefined): string {
  if (!dataType) return "通用";
  return DATA_TYPE_LABELS[dataType] ?? dataType;
}

/** 任务来源中文名（learning_tasks.source 四值，PRD-06 §8.2） */
export const TASK_SOURCE_LABELS: Record<string, string> = {
  agent: "Agent 创建",
  preset: "预设学习",
  teacher: "教师发布",
  diagnostic: "诊断补强",
};

export function taskSourceLabel(source: string | null | undefined): string {
  return TASK_SOURCE_LABELS[source ?? ""] ?? source ?? "未知";
}

/** 掌握度事件来源中文名（mastery_events.source，个人中心成长记录用） */
export const MASTERY_SOURCE_LABELS: Record<string, string> = {
  exercise: "练习",
  diagnostic: "诊断",
  teacher_task: "教师任务",
  assessment: "入学测评",
};

export function masterySourceLabel(source: string | null | undefined): string {
  return MASTERY_SOURCE_LABELS[source ?? ""] ?? source ?? "其他";
}

/** 错误 → 用户可读文案（后端中文 message 原样透传，网络错误等兜底） */
export function errMsg(err: unknown): string {
  return err instanceof Error ? err.message : "操作失败，请稍后重试";
}

/* ---------------------------------------------------------------- 图谱工具 */

/** 节点显示名：源 JSON 主字段是 label，loader 规范化出 name，双兜底防字段漂移 */
export function nodeLabel(node: { id: string; label?: string; name?: string }): string {
  return node.label ?? node.name ?? node.id;
}

/**
 * cap_id → 中文名映射 hook：取一次全图（166 节点）构建映射。
 * 任务列表/诊断补强计划等处只有 cap_id，需要图谱把 id 翻译成中文名；
 * 拉取失败降级为空映射（页面回退显示 id），不阻断主流程。
 */
export function useCapNames(): Map<string, string> {
  const [capNames, setCapNames] = useState<Map<string, string>>(new Map());
  useEffect(() => {
    const controller = new AbortController();
    api
      .get<GraphOverview>("/api/graph/overview", undefined, { signal: controller.signal })
      .then((res) => {
        if (controller.signal.aborted) return;
        const map = new Map<string, string>();
        for (const node of res.nodes) {
          if (node.type === "CAP") map.set(node.id, nodeLabel(node));
        }
        setCapNames(map);
      })
      .catch(() => {
        /* 名称解析失败不阻断页面：chips 显示 cap_id 兜底 */
      });
    return () => controller.abort();
  }, []);
  return capNames;
}

export function capNameOf(capNames: Map<string, string>, capId: string): string {
  return capNames.get(capId) ?? capId;
}

/* ---------------------------------------------------------------- 埋点 */

/**
 * 前端埋点上报（蓝图 §8 白名单事件）。
 *
 * 为什么只补 UI 层事件：preset_clicked / rag_query_submitted /
 * diagnostic_uploaded / mastery_updated 等已由后端在业务端点内埋点，
 * 前端重复上报会扭曲运营指标的分母（如 preset_start_rate=创建数/点击数）。
 * 前端只负责后端看不到的交互事件（如 citation_clicked）。
 * 失败静默——观测绝不能影响主流程。
 */
export function trackEvent(name: string, props: Record<string, unknown> = {}): void {
  api.post("/api/events", { events: [{ name, props }] }).catch(() => {});
}

/* ---------------------------------------------------------------- 掌握度变化预览 */

export interface MasteryPreviewListProps {
  changes: MasteryChange[];
  capNames: Map<string, string>;
}

/**
 * 掌握度变化预览列表（PRD-06 §6.4 确认门口径：任务提交后/诊断保存前必须展示）。
 * 每行：能力名 + old% → new% 徽章 + old/new 双条对比；徽章颜色取新值档位，
 * 与图谱配色同一口径（绿=已掌握/橙=待加强/红=初学），避免跨页颜色语义冲突。
 */
export function MasteryPreviewList({ changes, capNames }: MasteryPreviewListProps) {
  if (changes.length === 0) {
    return <p className="text-sm text-secondary">本次操作不涉及掌握度变化。</p>;
  }
  return (
    <ul className="flex flex-col gap-3">
      {changes.map((change) => {
        const key = change.cap_id;
        const oldPct =
          change.old_score == null ? null : Math.round(change.old_score * 100);
        const newPct =
          change.new_score == null ? null : Math.round(change.new_score * 100);
        const status = masteryStatusOf(change.new_score);
        // 新值档位 → 进度条色（ProgressBar 语义色与掌握度三色对齐）
        const newTone =
          status === "mastered" ? "success" : status === "weak" ? "warning" : status === "beginner" ? "danger" : "primary";
        return (
          <li key={key}>
            <div className="flex items-center justify-between gap-3 mb-2">
              <span className="text-sm">{capNameOf(capNames, change.cap_id)}</span>
              <span className={`badge badge-${status === "none" ? "neutral" : status}`}>
                {oldPct == null ? "暂无" : `${oldPct}%`} →{" "}
                {newPct == null ? "暂无" : `${newPct}%`}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div style={{ flex: 1 }}>
                <ProgressBar value={change.old_score ?? 0} />
              </div>
              <span className="text-xs text-muted">→</span>
              <div style={{ flex: 1 }}>
                <ProgressBar value={change.new_score ?? 0} tone={newTone} />
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------------------------------------------------------------- 时间 */

/** ISO 时间 → 本地短格式（列表/时间线展示；非法输入原样返回防渲染崩溃） */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}
