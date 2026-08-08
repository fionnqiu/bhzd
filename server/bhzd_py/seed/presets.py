"""8 条预设学习路径（PRD-01 §4.3 七条 + v3.0"内容安全文本审核"）。

为什么放在代码而非数据库：预设是产品内置内容，随版本发布演进，蓝图 §13
把它划归 seed/presets.py；`cap_ids`/`unit_ids` 必须引用真实存在的图谱节点
与教学单元，loader 启动时会校验并对悬空 id 告警（只告警不阻断，避免图谱
修订期卡死启动）。
"""

from __future__ import annotations

from typing import Any

# 通用（非特定数据类型）路径的 data_type 取值
GENERAL_DATA_TYPE = "general"

PRESETS: list[dict[str, Any]] = [
    {
        "id": "preset-intro-basics",
        "title": "数据标注零基础入门",
        "description": "从零认识数据标注：任务拆解、标签体系、质量底线与交付规范，建立完整工作框架。",
        "data_type": GENERAL_DATA_TYPE,
        "scenario_id": None,
        "goal": "掌握数据标注全流程与通用质量规范，能独立完成基础标注任务",
        "difficulty": 1,
        "est_minutes": 90,
        "cap_ids": [
            "CAP-CORE-TASK-SCOPE-001",
            "CAP-CORE-LABEL-SCHEMA-001",
            "CAP-CORE-ASSET-QUALITY-001",
            "CAP-CORE-EXPORT-QA-001",
        ],
        "unit_ids": ["TU-TEXT-LABEL-VOCAB-001", "TU-IMAGE-RECT-BOUNDS-001"],
        "recommended_for": "零基础新生与转岗同学",
    },
    {
        "id": "preset-ner-intro",
        "title": "NER 实体标注入门",
        "description": "学习命名实体识别标注：BIO 边界划分、实体类型判定与标签一致性校验。",
        "data_type": "text",
        "scenario_id": None,
        "goal": "能按 BIO 规范独立完成 NER 标注并通过一致性质检",
        "difficulty": 2,
        "est_minutes": 120,
        "cap_ids": [
            "CAP-TXT-ENTITY-BOUNDARY-001",
            "CAP-TXT-ENTITY-TYPE-001",
            "CAP-TXT-LABEL-VALIDATE-001",
        ],
        "unit_ids": ["TU-TEXT-NER-BOUNDARY-001", "TU-TEXT-LABEL-VOCAB-001"],
        "recommended_for": "已了解标注基础、准备进入文本方向的同学",
    },
    {
        "id": "preset-cs-emotion",
        "title": "客服情感标注",
        "description": "面向智能客服场景的语音/文本情感标注：情感标签判定、副语言事件记录与服务质检要点。",
        "data_type": "audio",
        "scenario_id": "SCN-CUSTOMER-SERVICE-001",
        "goal": "能对客服通话完成情感标签与副语言事件标注，达到质检要求",
        "difficulty": 3,
        "est_minutes": 150,
        "cap_ids": [
            "CAP-AUD-EMOTION-PARALING-001",
            "CAP-AUD-TRANSCRIBE-PUNCT-001",
            "CAP-AUD-SEGMENT-ALIGN-001",
        ],
        "unit_ids": [
            "TU-AUDIO-EMOTION-PARALINGUISTICS-001",
            "TU-AUDIO-TRANSCRIPTION-PUNCTUATION-001",
        ],
        "recommended_for": "有语音标注基础、目标客服质检岗位的同学",
    },
    {
        "id": "preset-wake-word",
        "title": "车载唤醒词标注",
        "description": "面向车载语音助手：唤醒词起止边界、正误唤醒样本判定与噪声重叠段处理。",
        "data_type": "audio",
        "scenario_id": "SCN-IN-VEHICLE-001",
        "goal": "能准确切分唤醒词边界并判定正误唤醒样本",
        "difficulty": 3,
        "est_minutes": 120,
        "cap_ids": [
            "CAP-AUD-WAKE-COMMAND-001",
            "CAP-AUD-NOISE-OVERLAP-001",
            "CAP-AUD-SEGMENT-ALIGN-001",
        ],
        "unit_ids": [
            "TU-AUDIO-WAKE-COMMAND-WORDS-001",
            "TU-AUDIO-SEGMENTATION-ALIGNMENT-001",
        ],
        "recommended_for": "目标车载语音数据岗位的同学",
    },
    {
        "id": "preset-image-detection",
        "title": "图像目标检测标注",
        "description": "矩形框标注规范：贴边要求、类别判定、遮挡/截断处理与 IOU 质量判定。",
        "data_type": "image",
        "scenario_id": None,
        "goal": "能按贴边规范完成目标检测框标注，IOU 质检达标",
        "difficulty": 2,
        "est_minutes": 120,
        "cap_ids": [
            "CAP-IMG-BOX-ANNOTATE-001",
            "CAP-IMG-OBJECT-CLASS-001",
            "CAP-IMG-RECT-VALIDATE-001",
        ],
        "unit_ids": ["TU-IMAGE-RECT-BOUNDS-001", "TU-IMAGE-OCCLUSION-TRUNCATION-001"],
        "recommended_for": "准备进入图像标注方向的同学",
    },
    {
        "id": "preset-video-event",
        "title": "视频片段事件标注",
        "description": "视频时间片段与事件边界标注：行为事件切分、帧级标注与跨帧目标跟踪。",
        "data_type": "video",
        "scenario_id": "SCN-CONTENT-SAFETY-001",
        "goal": "能完成视频事件的时间边界切分与目标跟踪标注",
        "difficulty": 4,
        "est_minutes": 150,
        "cap_ids": [
            "CAP-VID-ACTION-EVENT-001",
            "CAP-VID-EVENT-BOUNDARY-001",
            "CAP-VID-OBJECT-TRACK-001",
        ],
        "unit_ids": [
            "TU-VIDEO-BEHAVIOR-EVENT-001",
            "TU-VIDEO-FRAME-ANNOTATION-001",
            "TU-VIDEO-OBJECT-TRACKING-001",
        ],
        "recommended_for": "有图像标注经验、进阶视频方向的同学",
    },
    {
        "id": "preset-cert-1x",
        "title": "1+X 数据标注考证路径",
        "description": "对标 1+X 数据标注职业技能等级证书：考点梳理、规范强化与模拟练习。",
        "data_type": GENERAL_DATA_TYPE,
        "scenario_id": None,
        "goal": "系统覆盖 1+X 证书考点，通过模拟评测",
        "difficulty": 3,
        "est_minutes": 180,
        "cap_ids": [
            "CAP-CORE-LABEL-SCHEMA-001",
            "CAP-CORE-ASSET-QUALITY-001",
            "CAP-CORE-EXPORT-QA-001",
        ],
        "unit_ids": [
            "TU-TEXT-DOCUMENT-CLASSIFY-001",
            "TU-IMAGE-RECT-BOUNDS-001",
            "TU-AUDIO-SEGMENTATION-ALIGNMENT-001",
        ],
        "recommended_for": "备考 1+X 数据标注职业技能等级证书的同学",
    },
    {
        "id": "preset-content-safety-text",
        "title": "内容安全文本审核",
        "description": "文本内容安全审核标注：敏感词识别、违规类别判定与结合上下文的尺度把握。",
        "data_type": "text",
        "scenario_id": "SCN-CONTENT-SAFETY-001",
        "goal": "能识别敏感词与违规内容，并结合上下文做出一致判定",
        "difficulty": 3,
        "est_minutes": 120,
        # 敏感词识别→标签校验、违规判定→文本分类、上下文理解→歧义消解/意图
        "cap_ids": [
            "CAP-TXT-LABEL-VALIDATE-001",
            "CAP-TXT-CLASSIFY-001",
            "CAP-TXT-AMBIGUITY-001",
            "CAP-TXT-INTENT-001",
        ],
        "unit_ids": [
            "TU-TEXT-DOCUMENT-CLASSIFY-001",
            "TU-TEXT-INTENT-AMBIGUITY-001",
            "TU-TEXT-LABEL-VOCAB-001",
        ],
        "recommended_for": "目标内容安全审核岗位的同学",
    },
]


def get_presets() -> list[dict[str, Any]]:
    """返回预设列表（浅拷贝，防调用方意外改到模块级常量）。"""
    return [dict(preset) for preset in PRESETS]
