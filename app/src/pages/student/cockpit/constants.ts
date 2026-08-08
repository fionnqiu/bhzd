/**
 * 指挥舱共享常量与埋点工具。
 *
 * 为什么集中在这里：工具名/确认门动作的中文映射在执行轨迹、确认门、
 * 嵌入工具卡三处复用，分散写必然不一致；埋点统一走 trackEvent 保证
 * 失败静默——埋点是观测写入，绝不允许影响学习主流程。
 */
import { api } from "../../../api/client";

/** 工具名 → 中文（蓝图 §9 工具契约；未收录的原样展示英文名兜底） */
export const TOOL_LABELS: Record<string, string> = {
  "course.search": "课程检索",
  "graph.reason": "图谱定位",
  "task.preview": "任务卡预览",
  "task.create": "创建学习任务",
  "diagnostic.preview": "诊断解读",
  "diagnostic.save_summary": "保存诊断摘要",
  "mastery.update": "更新掌握度",
  "rag.search": "资料召回",
  "rag.answer": "规范问答",
  "rag.preview_upload": "资料上传预检",
  "rag.create_document": "创建资料草稿",
  "rag.reindex_document": "重建资料索引",
  "rag.publish_document": "发布资料",
  "rag.archive_document": "归档资料",
  "rag.save_eval_case": "保存评测用例",
};

// RAG lifecycles now appear as controlled timeline rows, but their structured
// result cards can duplicate or overexplain the final answer. Keep those cards
// out of the transcript while retaining bounded stage and tool summaries.
const STUDENT_HIDDEN_EMBEDDED_TOOLS = new Set(["rag.search", "rag.answer"]);

export function isStudentHiddenEmbeddedTool(tool: string | null | undefined): boolean {
  return Boolean(tool && STUDENT_HIDDEN_EMBEDDED_TOOLS.has(tool));
}

/** 确认门 action_type → 中文（PRD-06 §6.4 写操作表） */
export const ACTION_LABELS: Record<string, string> = {
  "task.create": "创建学习任务",
  "diagnostic.save_summary": "保存诊断摘要",
  "mastery.update": "更新掌握度",
  "teacher.publish_task": "发布班级任务",
  "rag.publish_document": "发布资料",
  "rag.archive_document": "归档资料",
  "rag.create_document": "创建资料草稿",
  "rag.reindex_document": "重建资料索引",
  "rag.save_eval_case": "保存评测用例",
};

/** 数据类型 → 中文（task_tools.py `_DATA_TYPE_LABELS` 同口径） */
export const DATA_TYPE_LABELS: Record<string, string> = {
  text: "文本",
  image: "图像",
  audio: "语音",
  video: "视频",
};

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool;
}

export function actionLabel(actionType: string): string {
  return ACTION_LABELS[actionType] ?? actionType;
}

export function dataTypeLabel(dataType: string | null | undefined): string {
  return (dataType && DATA_TYPE_LABELS[dataType]) || "通用";
}

/**
 * 发送一条埋点（蓝图 §8 白名单事件）。
 * 为什么 catch 吞掉：POST /api/events 不强制 CSRF 且后端对未知事件名
 * 静默丢弃，前端只需保证"发了就行"，失败不影响用户操作。
 *
 * 注意：goal_submitted / diagnostic_uploaded / diagnostic_summary_saved
 * 由后端在对应路由写入（runs.py / diagnostics.py），前端只发
 * preset_clicked，避免重复计数。
 */
export function trackEvent(name: string, props: Record<string, unknown> = {}): void {
  void api.post("/api/events", { events: [{ name, props }] }).catch(() => {});
}

/** 欢迎态目标输入占位文案（PRD-01 §3 / 蓝图 §14 逐字契约，不可改） */
export const GOAL_PLACEHOLDER = "说说你想学什么，比如：我想学客服语音情感标注";

/** 欢迎态 3 个示例问题（PRD-06 §7.2 空状态） */
export const EXAMPLE_QUESTIONS: string[] = [
  "NER 标注的 BIO 边界怎么划分？",
  "客服语音情感标签有哪些？",
  "COCO 框选 IOU 合格线是多少？",
];
