"""四种格式 → 规范化记录的解析器（蓝图 §11 校验链第 2 步：字段齐全才评分）。

规范化输出统一为：
  spans: [{start, end, label, text, tier?}]            —— TextGrid / 通用 JSON
  boxes: [{x, y, w, h, label, image_id, image_w, image_h}] —— COCO / VOC
外加 media_duration（可选）、fields（识别到的字段清单，供预检展示）、warnings。

缺必填字段一律抛 DiagnosticError(FIELDS_MISSING) 并在消息里**点名缺哪个字段**
（PRD-06 §9.2：指出缺少字段，不进入评分）。
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from .detect import DiagnosticError

# 通用 JSON 里记录数组可能挂的键名（按常见标注导出习惯穷举）
_RECORD_LIST_KEYS = ("annotations", "spans", "items", "records", "data", "segments")
# 记录里起止时间的可接受键名（秒或毫秒都按数值处理，单位不在诊断阶段裁决）
_START_KEYS = ("start", "start_ms", "begin")
_END_KEYS = ("end", "end_ms", "finish")
_LABEL_KEYS = ("label", "category", "text", "tag")
_DURATION_KEYS = ("media_duration", "duration", "duration_ms")


def _fields_missing(message: str) -> DiagnosticError:
    return DiagnosticError("FIELDS_MISSING", message)


def _pick(record: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return None


def _to_float(value: Any, field: str) -> float:
    """数值字段强转；不可转视为字段缺失（内容型错误不该在解析期静默吞掉）。"""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise _fields_missing(f"字段 {field} 的值「{value}」不是有效数值") from exc


# ---------------------------------------------------------------- TextGrid


def parse_textgrid(text: str) -> dict:
    """解析 Praat TextGrid（IntervalTier 的 intervals → spans）。

    顶层 xmax 作为 media_duration（供"边界超出媒体时长"规则使用）。
    空的 text 区间保留在结果里（空标注本身是一条可诊断信号，见 rules）。
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    media_duration: float | None = None
    spans: list[dict[str, Any]] = []
    fields: set[str] = set()
    current_tier: str | None = None
    cur_start: float | None = None
    cur_end: float | None = None
    in_intervals = False
    seen_tier = False  # 是否已进入任一 tier；之前的 xmin/xmax 是顶层媒体范围
    # TextGrid 的键值行形如 `xmin = 0.5` / `text = "..."`，用正则逐行读取
    kv_re = re.compile(r"^(xmin|xmax|text|name|class)\s*=\s*(.*)$")

    def _flush(tier: str | None, start: float | None, end: float | None, label: str) -> None:
        if start is None or end is None:
            raise _fields_missing("TextGrid 的 intervals 缺少 xmin 或 xmax 数值字段")
        spans.append(
            {"start": start, "end": end, "label": label, "text": label, "tier": tier or ""}
        )
        fields.update(["intervals.xmin", "intervals.xmax", "intervals.text"])

    for line in lines:
        match = kv_re.match(line)
        if match:
            key, raw = match.group(1), match.group(2).strip()
            value = raw.strip('"')
            if key == "class":
                # 进入新的 tier；只有 IntervalTier 才产 spans（TextTier 的 points 首期不支持）
                seen_tier = True
                in_intervals = value == "IntervalTier"
                current_tier = None
                cur_start = cur_end = None
            elif key == "name" and seen_tier and current_tier is None:
                current_tier = value
                fields.add("tier.name")
            elif key == "xmin":
                if seen_tier:
                    cur_start = _to_float(value, "xmin")
                # 顶层 xmin 一律为 0 起点，无诊断价值，忽略
            elif key == "xmax":
                if not seen_tier:
                    # 顶层 xmax = 媒体总时长（供"边界超出媒体时长"规则使用）
                    media_duration = _to_float(value, "xmax")
                    fields.add("xmax(媒体时长)")
                else:
                    cur_end = _to_float(value, "xmax")
            elif key == "text":
                if in_intervals:
                    if cur_start is None or cur_end is None:
                        raise _fields_missing("TextGrid 的 intervals 缺少 xmin 或 xmax 数值字段")
                    _flush(current_tier, cur_start, cur_end, value)
                    cur_start = cur_end = None
            continue
        # intervals [n]: 每进入一个新区间，先把上一个未闭合的冲掉（防御性格式变体）
        if line.startswith("intervals [") and in_intervals:
            cur_start = cur_end = None
    if not spans:
        raise _fields_missing("TextGrid 中未找到任何 IntervalTier 的 intervals 标注区间")
    return {
        "kind": "spans",
        "spans": spans,
        "boxes": [],
        "media_duration": media_duration,
        "fields": sorted(fields),
        "warnings": [],
    }


# ---------------------------------------------------------------- COCO JSON


def parse_coco(text: str) -> dict:
    """解析 COCO JSON：annotations[].bbox → boxes，category_id 映射类别名。

    必填：images[].{id,width,height}、annotations[].{image_id,category_id,bbox}、
    categories[].{id,name}；缺哪个就在错误消息里点名哪个（不评分）。
    """
    obj = json.loads(text)
    images = obj.get("images") or []
    annotations = obj.get("annotations") or []
    categories = obj.get("categories") or []
    warnings: list[str] = []
    fields = {"images", "annotations", "categories"}

    image_index: dict[Any, dict] = {}
    for image in images:
        for key in ("id", "width", "height"):
            if key not in image:
                raise _fields_missing(f"COCO images 记录缺少必填字段 {key}")
        image_index[image["id"]] = image
    cat_names: dict[Any, str] = {}
    for cat in categories:
        for key in ("id", "name"):
            if key not in cat:
                raise _fields_missing(f"COCO categories 记录缺少必填字段 {key}")
        cat_names[cat["id"]] = str(cat["name"])

    boxes: list[dict[str, Any]] = []
    for ann in annotations:
        for key in ("image_id", "category_id", "bbox"):
            if key not in ann:
                raise _fields_missing(f"COCO annotations 记录缺少必填字段 {key}")
        bbox = ann["bbox"]
        if not isinstance(bbox, list | tuple) or len(bbox) != 4:
            raise _fields_missing("COCO annotations.bbox 必须是 [x, y, w, h] 四元数组")
        x, y, w, h = (_to_float(v, "bbox") for v in bbox)
        image = image_index.get(ann["image_id"])
        if image is None:
            # 引用不存在的图片：不阻断，降级为未知尺寸（边界规则会跳过）
            warnings.append(f"标注引用了不存在的图片 image_id={ann['image_id']}，已跳过尺寸校验")
        boxes.append(
            {
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "label": cat_names.get(ann["category_id"], str(ann["category_id"])),
                "category_id": ann["category_id"],
                "image_id": ann["image_id"],
                "image_w": float(image["width"]) if image else None,
                "image_h": float(image["height"]) if image else None,
            }
        )
        fields.update(["annotations.bbox", "annotations.category_id", "annotations.image_id"])
    if not boxes:
        raise _fields_missing("COCO annotations 为空，没有可诊断的标注框")
    return {
        "kind": "boxes",
        "spans": [],
        "boxes": boxes,
        "media_duration": None,
        "fields": sorted(fields),
        "warnings": warnings,
        "categories": sorted(cat_names.values()),
    }


# ---------------------------------------------------------------- VOC XML


def parse_voc(text: str) -> dict:
    """解析 VOC XML：<object><bndbox> → boxes（xmin/ymin/xmax/ymax 转 x/y/w/h）。"""
    root = ET.fromstring(text)
    filename = root.findtext("filename") or "unknown"
    size = root.find("size")
    image_w = image_h = None
    warnings: list[str] = []
    fields = {"object.name", "object.bndbox"}
    if size is not None:
        try:
            image_w = float(size.findtext("width") or 0) or None
            image_h = float(size.findtext("height") or 0) or None
            fields.add("size")
        except ValueError:
            image_w = image_h = None
    if image_w is None or image_h is None:
        warnings.append("VOC 缺少 <size> 图片尺寸，已跳过边界越界校验")

    objects = root.findall("object")
    if not objects:
        raise _fields_missing("VOC XML 中未找到任何 <object> 标注对象")
    boxes: list[dict[str, Any]] = []
    for obj_el in objects:
        name = obj_el.findtext("name")
        if name is None:
            raise _fields_missing("VOC <object> 缺少必填字段 <name>")
        bndbox = obj_el.find("bndbox")
        if bndbox is None:
            raise _fields_missing(f"VOC 对象「{name}」缺少必填字段 <bndbox>")
        coords = {}
        for key in ("xmin", "ymin", "xmax", "ymax"):
            raw = bndbox.findtext(key)
            if raw is None:
                raise _fields_missing(f"VOC 对象「{name}」的 <bndbox> 缺少坐标字段 {key}")
            coords[key] = _to_float(raw, key)
        boxes.append(
            {
                "x": coords["xmin"],
                "y": coords["ymin"],
                "w": coords["xmax"] - coords["xmin"],
                "h": coords["ymax"] - coords["ymin"],
                "label": name,
                "image_id": filename,
                "image_w": image_w,
                "image_h": image_h,
            }
        )
    return {
        "kind": "boxes",
        "spans": [],
        "boxes": boxes,
        "media_duration": None,
        "fields": sorted(fields),
        "warnings": warnings,
    }


# ---------------------------------------------------------------- 通用 JSON


def parse_generic_json(text: str) -> dict:
    """解析通用 JSON：记录数组（或含记录数组键的对象）→ spans。

    每条记录必填 start/end（或 start_ms/end_ms、begin/finish 同义键），
    label 可来自 label/category/text/tag；缺起止字段直接 FIELDS_MISSING。
    """
    obj = json.loads(text)
    media_duration: float | None = None
    if isinstance(obj, dict):
        for key in _DURATION_KEYS:
            if key in obj:
                media_duration = _to_float(obj[key], key)
                break
        records = None
        for key in _RECORD_LIST_KEYS:
            if isinstance(obj.get(key), list):
                records = obj[key]
                break
        if records is None:
            raise _fields_missing(
                "通用 JSON 中未找到标注记录数组（期望键名之一："
                + "/".join(_RECORD_LIST_KEYS)
                + "）"
            )
    elif isinstance(obj, list):
        records = obj
    else:
        raise _fields_missing("通用 JSON 顶层必须是记录数组或含记录数组的对象")

    spans: list[dict[str, Any]] = []
    fields: set[str] = set()
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            raise _fields_missing(f"第 {idx + 1} 条标注记录不是对象")
        start = _pick(record, _START_KEYS)
        end = _pick(record, _END_KEYS)
        if start is None or end is None:
            raise _fields_missing(
                f"第 {idx + 1} 条标注记录缺少必填的起止字段（start/end 或 start_ms/end_ms）"
            )
        label = _pick(record, _LABEL_KEYS)
        spans.append(
            {
                "start": _to_float(start, "start"),
                "end": _to_float(end, "end"),
                "label": "" if label is None else str(label),
                "text": str(record.get("text", label if label is not None else "")),
            }
        )
        fields.update(["start", "end", "label"])
    if not spans:
        raise _fields_missing("通用 JSON 的标注记录数组为空，没有可诊断的样本")
    if media_duration is not None:
        fields.add("media_duration")
    return {
        "kind": "spans",
        "spans": spans,
        "boxes": [],
        "media_duration": media_duration,
        "fields": sorted(fields),
        "warnings": [],
    }
