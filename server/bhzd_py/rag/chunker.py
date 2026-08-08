"""文本切片器：把解析块切成大小受控、带章节继承与重叠的切片草稿（蓝图 §2.1）。

切分策略（为什么这样设计）：
- 章节（section_title）是天然语义边界：缓冲区一旦遇到新章节就先落盘，
  避免一个切片横跨两个主题稀释向量主题（与 seed/loader 内联管线同理）。
- 超长文本用滑动窗口硬切，窗口内优先在句读（。！？\\n）处下刀，
  找不到合适句读才按 chunk_size 硬切——保证句子尽量完整，召回片段可读。
- 重叠（overlap）只在窗口硬切之间携带：块/章节边界本身是完整语义，
  不需要重复内容；硬切处携带重叠可避免答案被从中间截断。
- 表格策略（rag_settings.table_strategy，PRD-03 §6 切片参数）：
  'keep'    → markdown 表格（连续的 `|` 开头行）作为原子单元，绝不在表格
              内部下刀（因此表格切片允许略超 chunk_size），保留原始管道
              格式让引用展示仍是表格；
  'flatten' → 先把每行表格数据展平为 "列1 值1；列2 值2" 句子再走常规切分，
              让行级事实变成独立可召回的命题。
- token_count ≈ len(content) // 2：中文 1 字≈1 token、英文约 4 字符 1 token，
  混合语料取折半是零依赖下的工程近似（PRD 未要求精确 tokenize）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parsers import Block

# 句读字符：优先在这些位置之后下刀
_SENT_ENDS = frozenset("。！？!?\n")

# markdown 表格行：行首（允许空白缩进）是管道符
_TABLE_LINE_RE = re.compile(r"^\s*\|")
# 表格分隔行单元格（--- / :--- / ---: / :---:）
_TABLE_SEPARATOR_CELL_RE = re.compile(r":?-+:?")


@dataclass
class ChunkDraft:
    """切片草稿（尚未入库）：内容 + 展示/引用所需的定位信息。"""

    content: str
    section_title: str | None
    page_start: int | None
    page_end: int | None
    token_count: int


@dataclass
class _Piece:
    """切片缓冲的最小单元：一个块内的一段文本（普通段落或整张表格）。"""

    block: Block
    text: str
    is_table: bool


def _is_table_line(line: str) -> bool:
    return bool(_TABLE_LINE_RE.match(line))


def _split_keep_tables(text: str) -> list[tuple[str, bool]]:
    """把块文本切成 (文本段, 是否表格)：连续的 `|` 行构成一个原子表格段。"""
    segments: list[tuple[str, bool]] = []
    plain: list[str] = []
    table: list[str] = []

    def flush_plain() -> None:
        if plain:
            segments.append(("\n".join(plain), False))
            plain.clear()

    def flush_table() -> None:
        if table:
            segments.append(("\n".join(table), True))
            table.clear()

    for line in text.splitlines():
        if _is_table_line(line):
            flush_plain()
            table.append(line)
        else:
            flush_table()
            plain.append(line)
    flush_plain()
    flush_table()
    return segments


def _table_to_sentences(rows: list[str]) -> list[str]:
    """把表格行组展平为句子列表：首行作表头，分隔行跳过，数据行 → "列 值；列 值"。"""
    cell_rows: list[list[str]] = []
    for row in rows:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        # 分隔行（|---|---|）：所有单元格仅由 - 与 : 组成
        if cells and all(_TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells):
            continue
        cell_rows.append(cells)
    if len(cell_rows) < 2:
        # 没有表头+数据的完整表格（如只有一行）：按原样保留一行文本，不丢信息
        return ["；".join(cell for cell in cell_rows[0] if cell)] if cell_rows else []
    header = cell_rows[0]
    sentences: list[str] = []
    for cells in cell_rows[1:]:
        pairs = []
        for index, value in enumerate(cells):
            if not value:
                continue
            name = header[index] if index < len(header) and header[index] else f"列{index + 1}"
            pairs.append(f"{name} {value}")
        if pairs:
            sentences.append("；".join(pairs) + "。")
    return sentences


def _flatten_markdown_tables(text: str) -> str:
    """把文本中的 markdown 表格逐行展平为 "列1 值1；列2 值2" 句子（'flatten' 策略）。"""
    out_lines: list[str] = []
    table: list[str] = []

    def flush() -> None:
        if table:
            out_lines.extend(_table_to_sentences(table))
            table.clear()

    for line in text.splitlines():
        if _is_table_line(line):
            table.append(line)
        else:
            flush()
            out_lines.append(line)
    flush()
    return "\n".join(out_lines)


def chunk_blocks(
    blocks: list[Block],
    *,
    chunk_size: int,
    chunk_overlap: int,
    title_inherit: bool,
    table_strategy: str = "keep",
) -> list[ChunkDraft]:
    """把有序解析块切成切片草稿列表；空输入返回空列表（由调用方判 CHUNK_EMPTY）。

    table_strategy：'keep' 表格原子不拆（可略超 chunk_size）；'flatten' 表格
    先展平成句再常规切分；其他取值按 'keep' 处理（容错）。
    """
    drafts: list[ChunkDraft] = []
    buffer: list[_Piece] = []

    def flush() -> None:
        if not buffer:
            return
        # 组装切分单元：表格段保持原子整块产出，相邻非表格段合并后走窗口切分
        units: list[tuple[str, bool]] = []
        plain_parts: list[str] = []

        def flush_plain() -> None:
            if plain_parts:
                units.append(("\n\n".join(plain_parts), False))
                plain_parts.clear()

        for piece in buffer:
            if piece.is_table:
                flush_plain()
                units.append((piece.text, True))
            else:
                plain_parts.append(piece.text)
        flush_plain()
        source_blocks = [piece.block for piece in buffer]
        for text, is_table in units:
            text = text.strip()
            if not text:
                continue
            if is_table:
                # 原子表格：整块成为一个切片，绝不在表格内部下刀
                drafts.append(_make_draft(text, source_blocks, title_inherit))
            else:
                for segment in _window_split(text, chunk_size, chunk_overlap):
                    drafts.append(_make_draft(segment, source_blocks, title_inherit))
        buffer.clear()

    current_size = 0
    current_section: str | None = None
    for block in blocks:
        if not block.text.strip():
            continue  # 空块不参与切片，但不应阻断流程
        if table_strategy == "flatten":
            segments: list[tuple[str, bool]] = [(_flatten_markdown_tables(block.text), False)]
        else:  # 'keep' 及未知取值：表格保持原子
            segments = _split_keep_tables(block.text)
        for segment_text, is_table in segments:
            if not segment_text.strip():
                continue
            if buffer and block.section_title != current_section:
                flush()  # 章节边界：先落盘再开新缓冲
                current_size = 0
            if buffer and current_size + len(segment_text) > chunk_size:
                flush()  # 再加会超长：先落盘，让切片贴近 chunk_size
                current_size = 0
            if not buffer:
                current_section = block.section_title
            buffer.append(_Piece(block=block, text=segment_text, is_table=is_table))
            current_size += len(segment_text)
    flush()
    return drafts


def _window_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    """滑动窗口切分：窗口内优先句读处下刀，窗口间携带 overlap 字符重叠。"""
    if len(text) <= chunk_size:
        return [text]
    segments: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end >= n:
            segments.append(text[start:])
            break
        # 在窗口后半段找最后一个句读，避免切出过碎的前缀块
        cut = -1
        for i in range(end, start + max(chunk_size // 2, 1), -1):
            if text[i - 1] in _SENT_ENDS:
                cut = i
                break
        if cut == -1:
            cut = end  # 找不到句读：硬切
        segments.append(text[start:cut])
        # 下一段回退 overlap 携带上下文；max 保证 start 严格递增、不死循环
        start = max(cut - overlap, start + 1) if overlap > 0 else cut
    return [s for s in segments if s.strip()]


def _make_draft(content: str, source_blocks: list[Block], title_inherit: bool) -> ChunkDraft:
    """由一段切分文本与来源块组装 ChunkDraft（含标题继承前缀与页码范围）。"""
    content = content.strip()
    section = source_blocks[0].section_title
    if title_inherit and section and not content.startswith((section, f"【{section}】")):
        # 标题继承：把所属章节路径前置进切片内容，单切片独立成义、向量更聚焦
        content = f"【{section}】\n{content}"
    pages = [b.page for b in source_blocks if b.page is not None]
    return ChunkDraft(
        content=content,
        section_title=section,
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        token_count=len(content) // 2,  # 混合 CJK 的工程近似，见模块 docstring
    )
