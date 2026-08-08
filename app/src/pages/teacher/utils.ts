/**
 * 教师端共享小工具（F3 各页面并置模块）。
 *
 * 为什么集中在这里：日期/百分比/错误文案的格式化口径跨 6 个教师页面复用，
 * 各写一份必然漂移（如 null 是显示 "—" 还是空串）；保持单一事实来源。
 */

import { ApiRequestError } from "../../api/client";

/** ISO 时间 → 本地中文短格式；空值显示 "—"（后端大量字段可空） */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { hour12: false });
}

/** 0..1 比率 → 百分比文本；null 表示"暂无数据"（后端口径，不虚构 0%） */
export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "暂无数据";
  return `${Math.round(value * 100)}%`;
}

/** 提取后端中文错误文案；非 API 错误给兜底话（错误话术后端统一，前端不编造） */
export function errMsg(err: unknown, fallback = "操作失败，请稍后重试"): string {
  if (err instanceof ApiRequestError) return err.message;
  return fallback;
}

/** 一组可空比率的均值；全空返回 null（"暂无数据"与"0%"必须区分开） */
export function avgOf(values: (number | null)[]): number | null {
  const valid = values.filter((v): v is number => v !== null);
  if (valid.length === 0) return null;
  return valid.reduce((a, b) => a + b, 0) / valid.length;
}

/**
 * 数据类型词表（后端口径为英文代码，见 seed/presets.py 与 PRD-02 §6.2）。
 * 教师端所有"数据类型"下拉统一用它，避免各页自造取值导致筛选落空。
 */
export const DATA_TYPE_OPTIONS = [
  { value: "text", label: "文本" },
  { value: "image", label: "图像" },
  { value: "audio", label: "语音" },
  { value: "video", label: "视频" },
];

/** 数据类型代码 → 中文（未知代码原样显示，后端新增类型时也能兜住） */
export function dataTypeLabel(code: string | null | undefined): string {
  if (!code) return "不限";
  return DATA_TYPE_OPTIONS.find((o) => o.value === code)?.label ?? code;
}

/** 任务来源词表（learning_tasks.source，PRD-02 §6.2 学情筛选项） */
export const TASK_SOURCE_OPTIONS = [
  { value: "agent", label: "Agent 创建" },
  { value: "preset", label: "预设学习" },
  { value: "teacher", label: "教师发布" },
  { value: "diagnostic", label: "诊断补强" },
];

/** 学情时间范围（teacher.py analytics 的 range 参数） */
export const ANALYTICS_RANGE_OPTIONS = [
  { value: "7d", label: "最近 7 天" },
  { value: "30d", label: "最近 30 天" },
  { value: "term", label: "本学期" },
];
