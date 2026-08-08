"""诊断文件格式识别：扩展名 + 内容嗅探双通道（蓝图 §11）。

为什么双通道：学生上传的文件经常扩展名乱取（.txt 装 JSON、无扩展名的
TextGrid），只看扩展名误判率高；内容特征（TextGrid 头、COCO 三件套键、
XML <annotation> 根）才是可靠依据，扩展名只作为首轮线索。

DiagnosticError 定义在这里（依赖链最底层），engine 再 re-export，
保证 `engine.DiagnosticError` 与 `detect.DiagnosticError` 是同一个类。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

# 支持的四类格式标识
FORMAT_TEXTGRID = "textgrid"
FORMAT_COCO = "coco_json"
FORMAT_VOC = "voc_xml"
FORMAT_GENERIC_JSON = "generic_json"

TEXTGRID_HEADER = 'File type = "ooTextFile"'

# 解析失败的统一中文提示（PRD-06 §9.2：返回格式错误和示例模板说明）
PARSE_FAILED_MESSAGE = (
    "无法识别或解析该文件。当前支持四种标注格式："
    "1) Praat TextGrid（文件头为 File type = \"ooTextFile\"）；"
    "2) COCO JSON（包含 images、annotations、categories 三个字段的 JSON）；"
    "3) VOC XML（根节点为 <annotation>，含 <object><bndbox>）；"
    "4) 通用 JSON（记录数组，每条含 start/end 与 label 字段）。"
    "请检查文件内容是否为上述格式之一后重新上传。"
)


class DiagnosticError(Exception):
    """诊断流程错误：code 供前端分支（PARSE_FAILED / FIELDS_MISSING），message 为中文。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def detect_format(file_bytes: bytes, filename: str) -> str:
    """识别文件格式，返回 FORMAT_* 常量之一；无法识别抛 DiagnosticError(PARSE_FAILED)。

    判定顺序（先特异后通用）：TextGrid 头 → XML(VOC) → COCO → 通用 JSON。
    """
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    # 二进制/非 UTF-8 内容直接判失败（标注文件都是文本格式）
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiagnosticError("PARSE_FAILED", PARSE_FAILED_MESSAGE) from exc
    stripped = text.lstrip()

    # 1) TextGrid：文件头嗅探为准（扩展名 .textgrid 仅作辅助线索，不单独采信）
    if stripped.startswith(TEXTGRID_HEADER) or (
        suffix in ("textgrid", "tg") and TEXTGRID_HEADER in stripped[:500]
    ):
        return FORMAT_TEXTGRID

    # 2) XML：根标签 <annotation> 即 VOC；其余 XML 不支持
    if stripped.startswith("<"):
        try:
            root = ET.fromstring(stripped)
        except ET.ParseError as exc:
            raise DiagnosticError("PARSE_FAILED", PARSE_FAILED_MESSAGE) from exc
        if root.tag == "annotation":
            return FORMAT_VOC
        raise DiagnosticError("PARSE_FAILED", PARSE_FAILED_MESSAGE)

    # 3) JSON：COCO 三件套键优先，其余对象/数组走通用 JSON
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise DiagnosticError("PARSE_FAILED", PARSE_FAILED_MESSAGE) from exc
        if isinstance(obj, dict) and all(
            key in obj for key in ("images", "annotations", "categories")
        ):
            return FORMAT_COCO
        return FORMAT_GENERIC_JSON

    raise DiagnosticError("PARSE_FAILED", PARSE_FAILED_MESSAGE)
