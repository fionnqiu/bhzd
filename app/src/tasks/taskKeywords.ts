import type { GraphNode } from "../data/contracts";
import { graph } from "../data/rawData";

interface KeywordRule {
  id: string;
  keywords: readonly string[];
}

interface DataTypeRule {
  id: "audio" | "video" | "image" | "text";
  keywords: readonly string[];
}

export interface KeywordMatch {
  id: string;
  keywords: string[];
  score: number;
  precedence: number;
}

const DATA_TYPE_RULES: readonly DataTypeRule[] = [
  {
    id: "audio",
    keywords: [
      "音频",
      "语音",
      "录音",
      "audio",
      "唤醒词",
      "说话人",
      "转写",
      "声道",
    ],
  },
  {
    id: "video",
    keywords: ["视频", "video", "跨帧", "轨迹", "抽帧", "行为事件"],
  },
  {
    id: "image",
    keywords: [
      "图像",
      "图片",
      "影像",
      "image",
      "目标框",
      "矩形框",
      "多边形",
      "掩码",
      "关键点",
    ],
  },
  {
    id: "text",
    keywords: [
      "文本",
      "文档",
      "text",
      "字符偏移",
      "命名实体",
      "实体关系",
      "意图",
    ],
  },
];

const TASK_RULES: readonly KeywordRule[] = [
  {
    id: "TSK-AUD-COMMAND-SEGMENT-001",
    keywords: ["唤醒词", "命令意图", "命令词", "唤醒与命令"],
  },
  {
    id: "TSK-AUD-TRANSCRIPT-ALIGN-001",
    keywords: ["语音转写", "音频转写", "转写", "添加标点", "语音对齐"],
  },
  {
    id: "TSK-AUD-SPEAKER-DIARIZE-001",
    keywords: ["说话人轮次", "说话人", "轮次划分", "speaker"],
  },
  {
    id: "TSK-AUD-EMOTION-EVENT-001",
    keywords: ["语音情感", "副语言", "笑声", "叹气"],
  },
  {
    id: "TSK-AUD-CONFIG-AUDIT-001",
    keywords: ["音频任务配置", "音频配置", "字段绑定"],
  },
  {
    id: "TSK-IMG-OBJECT-BOX-001",
    keywords: ["图像目标框", "目标框", "矩形框", "框标注"],
  },
  {
    id: "TSK-IMG-POLYGON-TRACE-001",
    keywords: ["实例多边形", "多边形", "轮廓"],
  },
  {
    id: "TSK-IMG-MASK-REVIEW-001",
    keywords: ["分割掩码", "掩码", "实例分割", "语义分割"],
  },
  {
    id: "TSK-IMG-KEYPOINT-MARK-001",
    keywords: ["目标关键点", "关键点", "骨架"],
  },
  {
    id: "TSK-IMG-RECT-AUDIT-001",
    keywords: ["矩形框坐标", "坐标审计", "坐标越界"],
  },
  {
    id: "TSK-TXT-NER-ANNOTATE-001",
    keywords: ["实体边界", "命名实体", "实体标注", "字符偏移"],
  },
  {
    id: "TSK-TXT-RELATION-LINK-001",
    keywords: ["实体关系", "关系连边", "关系方向"],
  },
  {
    id: "TSK-TXT-INTENT-REVIEW-001",
    keywords: ["文本意图", "意图歧义", "用户意图", "意图标注"],
  },
  {
    id: "TSK-TXT-DOCUMENT-CLASSIFY-001",
    keywords: ["文档分类", "文本分类", "类别定义"],
  },
  {
    id: "TSK-TXT-LABEL-AUDIT-001",
    keywords: ["文本标签", "标签词表", "封闭标签", "标签审计"],
  },
  {
    id: "TSK-VID-OBJECT-TRACK-001",
    keywords: ["跨帧目标轨迹", "视频目标轨迹", "目标轨迹", "目标追踪"],
  },
  {
    id: "TSK-VID-ACTION-EVENT-001",
    keywords: ["视频行为事件", "行为事件", "事件区间", "事件类别"],
  },
  {
    id: "TSK-VID-FRAME-LABEL-001",
    keywords: ["抽样视频帧", "视频帧标注", "关键帧", "抽帧"],
  },
  {
    id: "TSK-VID-TRACK-ID-AUDIT-001",
    keywords: ["轨迹 id", "轨迹id", "id 切换", "id切换"],
  },
  {
    id: "TSK-VID-TRACK-QA-001",
    keywords: ["轨迹与事件导出", "轨迹导出", "视频质检"],
  },
];

const SCENARIO_RULES: readonly KeywordRule[] = [
  {
    id: "SCN-MEDICAL-001",
    keywords: ["医疗", "医学", "病历", "病例", "药品", "症状"],
  },
  {
    id: "SCN-CUSTOMER-SERVICE-001",
    keywords: ["智能客服", "客服", "客户", "坐席", "工单", "订单"],
  },
  {
    id: "SCN-IN-VEHICLE-001",
    keywords: ["车载", "车机", "车辆", "导航", "车控"],
  },
  {
    id: "SCN-CONTENT-SAFETY-001",
    keywords: ["内容安全", "风险审核", "敏感内容", "风险标记"],
  },
];

const GOAL_MARKERS = [
  "标注任务",
  "标注",
  "分类",
  "审计",
  "复核",
  "检查",
  "切割",
  "转写",
  "对齐",
  "绘制",
  "追踪",
  "轨迹",
  "边界",
  "意图",
  "事件",
] as const;

const taskNodes = graph.nodes.filter(({ type }) => type === "TSK");
const taskNodeIndex = new Map(taskNodes.map((node) => [node.id, node]));

const matchingKeywords = (
  normalizedText: string,
  keywords: readonly string[],
): string[] =>
  keywords.filter((keyword) => normalizedText.includes(keyword.toLowerCase()));

const rankRules = (
  normalizedText: string,
  rules: readonly KeywordRule[],
): KeywordMatch[] =>
  rules
    .map((rule, precedence): KeywordMatch => {
      const keywords = matchingKeywords(normalizedText, rule.keywords);
      return {
        id: rule.id,
        keywords,
        score: keywords.reduce((score, keyword) => score + keyword.length, 0),
        precedence,
      };
    })
    .filter(({ score }) => score > 0)
    .sort(
      (left, right) =>
        right.score - left.score || left.precedence - right.precedence,
    );

export const normalizeTaskText = (text: string): string =>
  text.trim().toLowerCase();

export const detectDataType = (
  normalizedText: string,
): KeywordMatch | null => {
  const matches = DATA_TYPE_RULES.map((rule, precedence): KeywordMatch => {
    const keywords = matchingKeywords(normalizedText, rule.keywords);
    return {
      id: rule.id,
      keywords,
      score: keywords.reduce((score, keyword) => score + keyword.length, 0),
      precedence,
    };
  })
    .filter(({ score }) => score > 0)
    .sort(
      (left, right) =>
        right.score - left.score || left.precedence - right.precedence,
    );

  return matches[0] ?? null;
};

export const detectScenario = (
  normalizedText: string,
): KeywordMatch | null => rankRules(normalizedText, SCENARIO_RULES)[0] ?? null;

export const rankTaskMatches = (
  normalizedText: string,
  dataType: string,
): KeywordMatch[] =>
  rankRules(normalizedText, TASK_RULES).filter(({ id }) =>
    taskNodeIndex.get(id)?.data_types.includes(dataType),
  );

export const hasGoalMarker = (normalizedText: string): boolean =>
  GOAL_MARKERS.some((marker) => normalizedText.includes(marker));

export const candidateLabels = (dataType: string | null): string[] =>
  taskNodes
    .filter((node) => dataType === null || node.data_types.includes(dataType))
    .map((node) => `${node.id}|${node.label}`);

export const getTaskNode = (taskId: string): GraphNode | undefined =>
  taskNodeIndex.get(taskId);
