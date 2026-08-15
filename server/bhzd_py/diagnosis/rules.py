"""确定性诊断规则引擎（蓝图 §11，PRD-06 §9）。

为什么规则全部确定性、零 LLM：P0 要求"诊断可信"——评分扣分永远来自确定性
引擎（蓝图 §10.6），同样的文件必须得到同样的报告。

规则 → 能力节点映射表（RULE_CAP_MAP）使用图谱真实 CAP id；按 (规则, 数据类型)
两级查找，找不到时回退到通用 CORE 能力。规则库未覆盖的任务类型：不扣分 +
notice（PRD-06 §9.2），由 engine 层统一拼报告。
"""

from __future__ import annotations

from typing import Any

# ---- 错误类型常量 ----
ERR_EMPTY_LABEL = "empty_label"  # 标注内容为空
ERR_INVALID_DURATION = "invalid_duration"  # 区间时长为负或为零
ERR_OVERLAP = "overlap"  # 标注区间重叠
ERR_OUT_OF_DURATION = "out_of_duration"  # 区间超出媒体总时长
ERR_ZERO_AREA = "zero_area_box"  # 标注框面积为零/负
ERR_OUT_OF_BOUNDS = "bbox_out_of_bounds"  # 标注框超出图片边界
ERR_UNKNOWN_CATEGORY = "unknown_category"  # 类别不在 categories 表内
ERR_DUPLICATE_BOX = "duplicate_box"  # 完全重复的标注框（IoU=1）

# ---- 规则中文名（报告 rule 字段 + RAG 召回的 question 文本）----
RULE_NAMES: dict[str, str] = {
    ERR_EMPTY_LABEL: "标注内容不得为空",
    ERR_INVALID_DURATION: "标注区间的结束时间必须大于开始时间",
    ERR_OVERLAP: "同一轨道的标注区间不得重叠",
    ERR_OUT_OF_DURATION: "标注区间不得超出媒体总时长",
    ERR_ZERO_AREA: "标注框的宽和高必须大于 0",
    ERR_OUT_OF_BOUNDS: "标注框不得超出图片边界",
    ERR_UNKNOWN_CATEGORY: "标注类别必须在 categories 类别表中声明",
    ERR_DUPLICATE_BOX: "同一图片不得存在完全重复的标注框",
}

# ---- 规则 → 图谱能力映射（按数据类型细化，缺省回退 CORE）----
# 选 id 依据图谱真实节点：边界类→SEGMENT-ALIGN/ENTITY-BOUNDARY/RECT-VALIDATE，
# 标签类→LABEL-VALIDATE/OBJECT-CLASS，质量类→CORE-ASSET-QUALITY。
RULE_CAP_MAP: dict[str, dict[str, str]] = {
    ERR_EMPTY_LABEL: {
        "text": "CAP-TXT-LABEL-VALIDATE-001",
        "image": "CAP-IMG-OBJECT-CLASS-001",
        "audio": "CAP-AUD-TRANSCRIBE-PUNCT-001",
        "video": "CAP-VID-FRAME-ANNOTATE-001",
        "_default": "CAP-CORE-LABEL-SCHEMA-001",
    },
    ERR_INVALID_DURATION: {
        "audio": "CAP-AUD-SEGMENT-ALIGN-001",
        "video": "CAP-VID-EVENT-BOUNDARY-001",
        "text": "CAP-TXT-ENTITY-BOUNDARY-001",
        "_default": "CAP-AUD-SEGMENT-ALIGN-001",
    },
    ERR_OVERLAP: {
        "audio": "CAP-AUD-NOISE-OVERLAP-001",
        "video": "CAP-VID-EVENT-BOUNDARY-001",
        "_default": "CAP-AUD-SEGMENT-ALIGN-001",
    },
    ERR_OUT_OF_DURATION: {
        "audio": "CAP-AUD-SEGMENT-ALIGN-001",
        "video": "CAP-VID-EVENT-BOUNDARY-001",
        "_default": "CAP-AUD-SEGMENT-ALIGN-001",
    },
    ERR_ZERO_AREA: {
        "image": "CAP-IMG-BOX-ANNOTATE-001",
        "_default": "CAP-IMG-BOX-ANNOTATE-001",
    },
    ERR_OUT_OF_BOUNDS: {
        "image": "CAP-IMG-RECT-VALIDATE-001",
        "_default": "CAP-IMG-RECT-VALIDATE-001",
    },
    ERR_UNKNOWN_CATEGORY: {
        "image": "CAP-IMG-OBJECT-CLASS-001",
        "_default": "CAP-IMG-OBJECT-CLASS-001",
    },
    ERR_DUPLICATE_BOX: {
        "image": "CAP-IMG-RECT-VALIDATE-001",
        "_default": "CAP-IMG-RECT-VALIDATE-001",
    },
}

# 规则库覆盖的数据类型（PRD-06 §9.2：未覆盖类型不扣分 + notice）
COVERED_DATA_TYPES = {"text", "image", "audio", "video", "general"}


def cap_for(error_type: str, data_type: str | None) -> str:
    """规则 → cap_id：优先按数据类型取细化映射，否则回退 _default。"""
    mapping = RULE_CAP_MAP[error_type]
    return mapping.get(data_type or "", mapping["_default"])


def _err(
    error_type: str,
    severity: str,
    user_value: Any,
    expected: str,
    data_type: str | None,
    suggestion: str,
) -> dict:
    return {
        "error_type": error_type,
        "severity": severity,
        "user_value": user_value,
        "expected": expected,
        "rule": RULE_NAMES[error_type],
        "cap_id": cap_for(error_type, data_type),
        "suggestion": suggestion,
    }


def check_spans(
    spans: list[dict],
    *,
    data_type: str | None,
    media_duration: float | None,
    source_format: str,
) -> list[dict]:
    """区间类规则（TextGrid / 通用 JSON）：空标注、时长非法、重叠和越界。

    空标注的严重度分格式：TextGrid 空白区间常用来表示"非语音段"，单条只记
    minor；通用 JSON 里空 label 属于明显漏标，记 major。
    """
    errors: list[dict] = []
    empty_severity = "minor" if source_format == "textgrid" else "major"

    for span in spans:
        label = str(span.get("label") or "").strip()
        start, end = span["start"], span["end"]
        if not label:
            errors.append(
                _err(
                    ERR_EMPTY_LABEL,
                    empty_severity,
                    f"[{start}, {end}]",
                    "每个标注区间都应有非空标签",
                    data_type,
                    "补全该区间的标注内容，或按规范删除无效区间",
                )
            )
        if end < start:
            errors.append(
                _err(
                    ERR_INVALID_DURATION,
                    "major",
                    f"start={start}, end={end}",
                    "结束时间必须大于开始时间",
                    data_type,
                    "交换或修正该区间的起止时间",
                )
            )
        elif end == start:
            errors.append(
                _err(
                    ERR_INVALID_DURATION,
                    "minor",
                    f"start=end={start}",
                    "区间时长应大于 0",
                    data_type,
                    "零时长区间通常无意义，请确认起止边界",
                )
            )
        if media_duration is not None and (end > media_duration or start < 0):
            errors.append(
                _err(
                    ERR_OUT_OF_DURATION,
                    "major",
                    f"[{start}, {end}]",
                    f"区间应落在 [0, {media_duration}] 内",
                    data_type,
                    "按媒体实际时长修正区间边界",
                )
            )

    # 重叠检测：同轨道（tier）内两两比较；相邻区间共享端点不算重叠（严格不等号）
    by_tier: dict[str, list[dict]] = {}
    for span in spans:
        by_tier.setdefault(str(span.get("tier", "")), []).append(span)
    for tier_spans in by_tier.values():
        ordered = sorted(tier_spans, key=lambda s: (s["start"], s["end"]))
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                a, b = ordered[i], ordered[j]
                if b["start"] >= a["end"]:
                    break  # 已按 start 排序，后续不可能再与 a 重叠
                errors.append(
                    _err(
                        ERR_OVERLAP,
                        "minor",
                        f"[{a['start']}, {a['end']}] 与 [{b['start']}, {b['end']}]",
                        "同一轨道区间不得重叠",
                        data_type,
                        "检查两条区间的边界，按实际内容重新切分",
                    )
                )
    return errors


def _iou(a: dict, b: dict) -> float:
    """两框 IoU；完全重合 = 1.0（重复框判定用）。"""
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    inter_w = max(0.0, min(ax2, bx2) - max(a["x"], b["x"]))
    inter_h = max(0.0, min(ay2, by2) - max(a["y"], b["y"]))
    inter = inter_w * inter_h
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def check_boxes(
    boxes: list[dict],
    *,
    data_type: str | None,
    declared_categories: set[str] | None,
) -> list[dict]:
    """框类规则（COCO / VOC）：零面积、越界、类别合法性、重复框。"""
    errors: list[dict] = []
    for box in boxes:
        label = str(box.get("label") or "").strip()
        desc = f"图片 {box['image_id']} 中 ({box['x']}, {box['y']}, {box['w']}, {box['h']})"
        if not label:
            errors.append(
                _err(
                    ERR_EMPTY_LABEL,
                    "major",
                    desc,
                    "每个标注框都应有类别标签",
                    data_type,
                    "补全该框的类别标签",
                )
            )
        if box["w"] <= 0 or box["h"] <= 0:
            errors.append(
                _err(
                    ERR_ZERO_AREA,
                    "major",
                    f"w={box['w']}, h={box['h']}（{desc}）",
                    "宽和高都必须大于 0",
                    data_type,
                    "重新框选目标，确保框有实际覆盖区域",
                )
            )
        if box.get("image_w") is not None and box.get("image_h") is not None:
            if (
                box["x"] < 0
                or box["y"] < 0
                or box["x"] + box["w"] > box["image_w"]
                or box["y"] + box["h"] > box["image_h"]
            ):
                errors.append(
                    _err(
                        ERR_OUT_OF_BOUNDS,
                        "major",
                        desc,
                        f"框应落在图片 0..{box['image_w']} × 0..{box['image_h']} 范围内",
                        data_type,
                        "把框调整到图片边界以内",
                    )
                )
        # 类别合法性只来自 COCO categories 声明表，不依赖外部标签集。
        if declared_categories is not None and label and label not in declared_categories:
            errors.append(
                _err(
                    ERR_UNKNOWN_CATEGORY,
                    "major",
                    label,
                    "类别应在 categories 表中声明：" + "、".join(sorted(declared_categories)),
                    data_type,
                    "改用 categories 中声明的类别，或补充类别声明",
                )
            )
    # 重复框：同图同标签且 IoU=1（坐标完全一致才算重复，近似重叠不判罚）
    by_image: dict[Any, list[dict]] = {}
    for box in boxes:
        by_image.setdefault(box["image_id"], []).append(box)
    for image_boxes in by_image.values():
        for i in range(len(image_boxes)):
            for j in range(i + 1, len(image_boxes)):
                a, b = image_boxes[i], image_boxes[j]
                if a["label"] == b["label"] and _iou(a, b) >= 0.999999:
                    errors.append(
                        _err(
                            ERR_DUPLICATE_BOX,
                            "minor",
                            f"图片 {a['image_id']} 中标签「{a['label']}」的重复框",
                            "同一目标只保留一个标注框",
                            data_type,
                            "删除多余的重复标注框",
                        )
                    )
    return errors


def run_rules(
    doc: dict,
    *,
    data_type: str | None,
    source_format: str,
) -> list[dict]:
    """按规范化记录的 kind 分发到区间/框规则组。"""
    if doc["kind"] == "spans":
        return check_spans(
            doc["spans"],
            data_type=data_type,
            media_duration=doc.get("media_duration"),
            source_format=source_format,
        )
    return check_boxes(
        doc["boxes"],
        data_type=data_type,
        declared_categories=(
            set(doc["categories"]) if doc.get("categories") else None
        ),
    )
