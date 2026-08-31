# -*- coding: utf-8 -*-
"""将参赛产品文档 Markdown 渲染为格式规范的 docx。"""
import os
import re
from docx import Document
from docx.shared import Pt, Cm, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

MD_PATH = r"E:\AgentWorkspaces\bhzd\docs\参赛作品产品文档.md"
OUT_DIR = r"E:\AgentWorkspaces\bhzd"
DOCX_PATH = os.path.join(OUT_DIR, "标航智导-参赛作品产品文档.docx")
ASSETS = r"E:\AgentWorkspaces\bhzd\var\doc-assets"

doc = Document()

# ---- 全局样式 ----
def set_cell_border(cell, **kwargs):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        if edge in kwargs:
            b = OxmlElement(f"w:{edge}")
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), str(kwargs[edge]))
            b.set(qn("w:color"), "8c9099")
            tcBorders.append(b)
    tcPr.append(tcBorders)


def set_run_font(run, name="Microsoft YaHei", size=10.5, bold=False, color=None, ascii_name="Calibri"):
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), name)
    rFonts.set(qn("w:ascii"), ascii_name)
    rFonts.set(qn("w:hAnsi"), ascii_name)
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def set_doc_default_font(doc, name="Microsoft YaHei", ascii_name="Calibri", size=10.5):
    style = doc.styles["Normal"]
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), name)
    rFonts.set(qn("w:ascii"), ascii_name)
    rFonts.set(qn("w:hAnsi"), ascii_name)
    style.font.size = Pt(size)
    # 段落默认行距
    pPr = style.element.get_or_add_pPr()
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:line"), "320")  # 1.4 倍行距
    spacing.set(qn("w:lineRule"), "auto")


# 设置中文字体
set_doc_default_font(doc)
# 标题样式
for i, size in enumerate([18, 15, 13, 11.5], start=1):
    st = doc.styles[f"Heading {i}"]
    rPr = st.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    rFonts.set(qn("w:ascii"), "Calibri")
    rFonts.set(qn("w:hAnsi"), "Calibri")
    st.font.size = Pt(size)
    st.font.bold = True
    st.font.color.rgb = RGBColor(0x1F, 0x6F, 0xEB)


# ---- 页面边距 ----
for section in doc.sections:
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.4)


# ---- 封面页 ----
def add_cover():
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("\n\n\n标航智导")
    set_run_font(r, size=36, bold=True, color="1f6feb", ascii_name="Calibri")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run('面向“人工智能技术应用”专业群、AI 数据标注工程师岗位的\n教学实训与岗位技能智能体平台')
    set_run_font(r, size=18, bold=True, color="212529")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("\n参赛作品产品文档")
    set_run_font(r, size=20, bold=True, color="e8590c")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("\n\n\n")
    info = [
        ("发榜单位", "科大讯飞股份有限公司"),
        ("赛题名称", "面向职业教育高水平专业群建设的教学实训与岗位技能智能体开发"),
        ("专业群方向", "人工智能技术应用"),
        ("核心就业岗位", "AI 数据标注工程师"),
        ("文档版本", "V1.0（2026-08-24）"),
        ("文档性质", "作品阐述、功能思路、技术方案、运行效果、迭代计划与创新之处的系统化说明"),
    ]
    for k, v in info:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(f"{k}：")
        set_run_font(r, size=12, bold=True, color="495057")
        r2 = p.add_run(v)
        set_run_font(r2, size=12, color="212529")

    doc.add_page_break()


add_cover()

# ---- 目录页（简单手写） ----
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.LEFT
r = p.add_run("目  录")
set_run_font(r, size=22, bold=True, color="1f6feb")
p.paragraph_format.space_after = Pt(18)

toc_items = [
    "1  项目概述",
    "2  需求分析",
    "3  系统架构设计",
    "4  功能模块说明",
    "5  技术实现方案",
    "6  核心业务流程",
    "7  创新亮点",
    "8  测试方案与结果",
    "9  部署说明",
    "10  项目成果总结",
    "11  附录",
]
for it in toc_items:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run("   " + it)
    set_run_font(r, size=13, color="212529")
doc.add_page_break()


# ---- 通用渲染函数 ----
INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
INLINE_CODE = re.compile(r"`([^`]+)`")
IMG_TOKEN = re.compile(r"\[图\s*([0-9A-Za-z\-]+)\s*：\s*([^\]]+)\]")

FIG_MAP = {
    "3-1": "fig3-1_architecture.png",
    "3-2": "fig3-2_agent_flow.png",
    "3-3": "fig3-3_rag_lifecycle.png",
    "6-1": "fig6-1_learning_loop.png",
}


def add_inline(paragraph, text, base_bold=False):
    """处理行内 **bold** 与 `code`"""
    parts = []
    cursor = 0
    for m in INLINE_BOLD.finditer(text):
        if m.start() > cursor:
            parts.append((text[cursor:m.start()], False))
        parts.append((m.group(1), True))
        cursor = m.end()
    if cursor < len(text):
        parts.append((text[cursor:], False))
    for chunk, bold in parts:
        # 再切 code
        sub_parts = []
        c2 = 0
        for mc in INLINE_CODE.finditer(chunk):
            if mc.start() > c2:
                sub_parts.append((chunk[c2:mc.start()], False, None))
            sub_parts.append((mc.group(1), False, "code"))
            c2 = mc.end()
        if c2 < len(chunk):
            sub_parts.append((chunk[c2:], False, None))
        for c, b, tag in sub_parts:
            r = paragraph.add_run(c)
            if tag == "code":
                set_run_font(r, size=10, color="c92a2a", ascii_name="Consolas")
                r.font.name = "Consolas"
                rPr = r._element.get_or_add_rPr()
                rFonts = rPr.find(qn("w:rFonts"))
                if rFonts is None:
                    rFonts = OxmlElement("w:rFonts")
                    rPr.append(rFonts)
                rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
            else:
                set_run_font(r, size=10.5, bold=(bold or base_bold))


def render_table(lines):
    """lines 是去掉首尾 | 的行列表；首行为表头"""
    if not lines:
        return
    rows = [re.split(r"\s*\|\s*", ln.strip().strip("|")) for ln in lines]
    # 过滤第二行（---|---|---）
    if len(rows) >= 2 and re.match(r"^[\s\-:|]+$", "|".join(rows[1])):
        rows.pop(1)
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    nrows = len(rows)
    t = doc.add_table(rows=nrows, cols=ncols)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = "Table Grid"
    t.autofit = True
    for r_i, row in enumerate(rows):
        for c_i in range(ncols):
            cell = t.cell(r_i, c_i)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            cell.text = ""
            p = cell.paragraphs[0]
            txt = row[c_i] if c_i < len(row) else ""
            r = p.add_run(txt)
            if r_i == 0:
                set_run_font(r, size=10.5, bold=True, color="ffffff")
                # 蓝色表头
                shd = OxmlElement("w:shd")
                shd.set(qn("w:fill"), "1f6feb")
                shd.set(qn("w:val"), "clear")
                cell._tc.get_or_add_tcPr().append(shd)
            else:
                set_run_font(r, size=10, color="212529")
                # 斑马纹
                if r_i % 2 == 0:
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:fill"), "f1f6ff")
                    shd.set(qn("w:val"), "clear")
                    cell._tc.get_or_add_tcPr().append(shd)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)


def add_code_block(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.right_indent = Cm(0.5)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(8)
    # 灰底
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), "f1f3f5")
    shd.set(qn("w:val"), "clear")
    pPr.append(shd)
    r = p.add_run(text)
    set_run_font(r, size=9.5, color="212529", ascii_name="Consolas")
    rPr = r._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def add_image(name, caption):
    path = os.path.join(ASSETS, name)
    if not os.path.exists(path):
        p = doc.add_paragraph()
        r = p.add_run(f"[图缺失：{name}]")
        set_run_font(r, size=10, color="c92a2a")
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run()
    r.add_picture(path, width=Inches(6.0))
    cp = doc.add_paragraph()
    cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cp.paragraph_format.space_after = Pt(12)
    cr = cp.add_run(caption)
    set_run_font(cr, size=9.5, bold=True, color="495057")


def add_blockquote(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.6)
    p.paragraph_format.right_indent = Cm(0.4)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(8)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "24")
    left.set(qn("w:color"), "1f6feb")
    pBdr.append(left)
    pPr.append(pBdr)
    r = p.add_run(text)
    set_run_font(r, size=10.5, color="495057")


# ---- 读取并解析 markdown ----
with open(MD_PATH, "r", encoding="utf-8") as f:
    md = f.read()

# 跳过 markdown 顶部直到"## 目录"（目录在 docx 中已手写）
md_body = re.split(r"^## 目录\s*$", md, maxsplit=1, flags=re.M)[1]
md_body = re.sub(r"^---\s*$", "", md_body, flags=re.M)  # 移除分隔线
md_body = re.sub(r"^>\s.*$", "", md_body, flags=re.M)  # 暂时跳过块引用

lines = md_body.split("\n")

i = 0
n = len(lines)

while i < n:
    line = lines[i]
    stripped = line.strip()

    # 空行
    if not stripped:
        i += 1
        continue

    # 标题
    m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
    if m:
        level = len(m.group(1))
        title = m.group(2).strip()
        # 跳过"目录"标题（已在封面后处理）
        if title == "目录":
            i += 1
            continue
        # 跳过 markdown 末尾的"维护说明"风格的引用/提示
        h = doc.add_heading("", level=level)
        h.paragraph_format.space_before = Pt(10 if level == 1 else 8)
        h.paragraph_format.space_after = Pt(4)
        r = h.add_run(title)
        # 字体在 styles 里已设
        i += 1
        continue

    # 代码块
    if stripped.startswith("```"):
        i += 1
        code_buf = []
        while i < n and not lines[i].strip().startswith("```"):
            code_buf.append(lines[i])
            i += 1
        i += 1
        add_code_block("\n".join(code_buf))
        continue

    # 表格
    if "|" in stripped and i + 1 < n and re.match(r"^\s*\|?[\s\-:|]+\|?\s*$", lines[i + 1]):
        tbl = [stripped]
        i += 1
        while i < n and "|" in lines[i] and lines[i].strip():
            tbl.append(lines[i].strip())
            i += 1
        render_table(tbl)
        continue

    # 列表
    if re.match(r"^\s*[-*]\s+", line):
        items = []
        while i < n and (re.match(r"^\s*[-*]\s+", lines[i]) or (i < len(lines) and lines[i].startswith("  ") and lines[i].strip())):
            items.append(lines[i])
            i += 1
        for it in items:
            mm = re.match(r"^\s*[-*]\s+(.*)$", it)
            if not mm:
                continue
            txt = mm.group(1).strip()
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.left_indent = Cm(0.7)
            add_inline(p, txt)
        continue

    # 编号列表
    if re.match(r"^\s*\d+\.\s+", line):
        items = []
        while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
            items.append(lines[i])
            i += 1
        for it in items:
            mm = re.match(r"^\s*\d+\.\s+(.*)$", it)
            if not mm:
                continue
            txt = mm.group(1).strip()
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.left_indent = Cm(0.7)
            add_inline(p, txt)
        continue

    # 图占位符
    m = IMG_TOKEN.search(stripped)
    if m and len(stripped) <= 80:
        key = m.group(1)
        cap = m.group(2).strip()
        fname = FIG_MAP.get(key)
        if fname:
            add_image(fname, cap)
            i += 1
            continue

    # 普通段落
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.first_line_indent = Cm(0.74)
    add_inline(p, stripped)
    i += 1

# 页脚页码（在每个 section 添加简单页码）
for section in doc.sections:
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("第 ")
    set_run_font(r, size=9, color="6c757d")
    # PAGE field
    fldChar1 = OxmlElement("w:fldChar"); fldChar1.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText"); instrText.set(qn("xml:space"), "preserve"); instrText.text = "PAGE"
    fldChar2 = OxmlElement("w:fldChar"); fldChar2.set(qn("w:fldCharType"), "end")
    r2 = p.add_run()
    r2._element.append(fldChar1)
    r2._element.append(instrText)
    r2._element.append(fldChar2)
    set_run_font(r2, size=9, color="6c757d")
    r3 = p.add_run(" 页 / 共 ")
    set_run_font(r3, size=9, color="6c757d")
    fldChar3 = OxmlElement("w:fldChar"); fldChar3.set(qn("w:fldCharType"), "begin")
    instrText2 = OxmlElement("w:instrText"); instrText2.set(qn("xml:space"), "preserve"); instrText2.text = "NUMPAGES"
    fldChar4 = OxmlElement("w:fldChar"); fldChar4.set(qn("w:fldCharType"), "end")
    r4 = p.add_run()
    r4._element.append(fldChar3)
    r4._element.append(instrText2)
    r4._element.append(fldChar4)
    set_run_font(r4, size=9, color="6c757d")
    r5 = p.add_run(" 页")
    set_run_font(r5, size=9, color="6c757d")

doc.save(DOCX_PATH)
print("saved:", DOCX_PATH)
print("size:", os.path.getsize(DOCX_PATH), "bytes")
