"""Temporary document extraction for one Agent attachment.

The Agent accepts common user-authored documents, but only extracted text is
given to a model.  Keeping parsing here avoids persisting source bytes or
reusing RAG records for a short-lived conversation attachment.
"""

from __future__ import annotations

import io
import re
import threading
import zipfile
from typing import Any
from xml.etree import ElementTree

from ..rag.errors import RAGError
from ..rag.parsers import parse_document

MAX_DOCUMENT_TEXT_CHARS = 120_000
MAX_PPTX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
# OCR is deliberately bounded more tightly than the upload size: a dense PDF
# rasterizes into far more memory than its original bytes suggest.
MAX_PDF_OCR_PAGES = 12
PDF_OCR_RENDER_SCALE = 1.5
OCR_MIN_CONFIDENCE = 0.45

# Loading ONNX models is costly. Keep one process-local engine and serialize
# inference so concurrent uploads cannot multiply the temporary raster memory.
_OCR_LOCK = threading.Lock()
_OCR_ENGINE: Any | None = None

# Modern formats are intentionally allow-listed.  Legacy Office binaries and
# archives need external converters or unpacking and therefore stay rejected.
DOCUMENT_TYPES: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".tsv": "tsv",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".log": "txt",
    ".json": "text",
    ".xml": "text",
    ".yaml": "text",
    ".yml": "text",
    ".html": "text",
    ".htm": "text",
    ".css": "text",
    ".js": "text",
    ".jsx": "text",
    ".ts": "text",
    ".tsx": "text",
    ".py": "text",
    ".java": "text",
    ".go": "text",
    ".rs": "text",
    ".sql": "text",
    ".sh": "text",
    ".ps1": "text",
}


class DocumentParseError(ValueError):
    """Raised when an allow-listed document cannot yield safe readable text."""

    def __init__(self, message: str, *, code: str = "document_parse_failed") -> None:
        super().__init__(message)
        self.code = code


def document_type_for(filename: str) -> str | None:
    """Return the allow-listed parser type from a filename extension."""

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return DOCUMENT_TYPES.get(f".{suffix}")


def _truncate(text: str) -> str:
    """Bound extracted content so one file cannot dominate the model context."""

    compact = text.strip()
    if len(compact) <= MAX_DOCUMENT_TEXT_CHARS:
        return compact
    return compact[:MAX_DOCUMENT_TEXT_CHARS] + "\n\n[文件内容已截断]"


def _parse_pptx(content: bytes) -> str:
    """Extract visible slide text without introducing a presentation renderer."""

    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (OSError, zipfile.BadZipFile) as exc:
        raise DocumentParseError("PPTX 文件无法读取") from exc
    with archive:
        slide_names = [
            info.filename
            for info in archive.infolist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", info.filename)
        ]
        if sum(info.file_size for info in archive.infolist()) > MAX_PPTX_UNCOMPRESSED_BYTES:
            raise DocumentParseError("PPTX 解压后的内容过大")
        sections: list[str] = []
        for name in sorted(slide_names, key=lambda item: int(re.search(r"\d+", item).group())):
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError as exc:
                raise DocumentParseError("PPTX 文件内容损坏") from exc
            lines = [node.text.strip() for node in root.iter() if node.tag.endswith("}t") and node.text]
            if lines:
                sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _parsed_blocks_text(parsed: Any) -> str:
    """Flatten RAG blocks while retaining headings that give Agent context."""

    return "\n\n".join(
        "\n".join(part for part in (block.section_title, block.text) if part)
        for block in parsed.blocks
    )


def _ocr_engine() -> Any:
    """Create the local OCR engine only when a PDF actually needs fallback OCR."""

    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _ocr_result_text(result: Any) -> str:
    """Project RapidOCR rows to reliable text without trusting low-confidence noise."""

    lines: list[str] = []
    for row in result or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        text, confidence = row[1], row[2]
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            if float(confidence) < OCR_MIN_CONFIDENCE:
                continue
        except (TypeError, ValueError):
            continue
        lines.append(text.strip())
    return "\n".join(lines)


def _extract_pdf_text_with_ocr(content: bytes) -> str:
    """Render a bounded scanned PDF locally and extract only its recognized text."""

    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(content)
    except Exception as exc:
        raise DocumentParseError("PDF 文件无法读取或受密码保护", code="pdf_ocr_failed") from exc

    try:
        page_count = len(document)
        if page_count > MAX_PDF_OCR_PAGES:
            raise DocumentParseError(
                f"扫描 PDF 最多支持 {MAX_PDF_OCR_PAGES} 页，请拆分后重新上传",
                code="pdf_ocr_page_limit",
            )
        pages: list[str] = []
        # RapidOCR's ONNX session is reusable but raster pages are large, so
        # serialize the full loop to keep concurrent uploads memory-bounded.
        with _OCR_LOCK:
            engine = _ocr_engine()
            for index in range(page_count):
                bitmap = document[index].render(scale=PDF_OCR_RENDER_SCALE)
                try:
                    image = bitmap.to_pil()
                    try:
                        result, _elapsed = engine(image)
                    finally:
                        image.close()
                finally:
                    bitmap.close()
                text = _ocr_result_text(result)
                if text:
                    pages.append(f"第 {index + 1} 页\n{text}")
        return "\n\n".join(pages)
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("PDF OCR 处理失败", code="pdf_ocr_failed") from exc
    finally:
        document.close()


def _extract_pdf_text(content: bytes) -> str:
    """Prefer embedded text, then use OCR only for scanned or unreadable PDFs."""

    try:
        return _parsed_blocks_text(parse_document(content, "pdf"))
    except RAGError:
        text = _extract_pdf_text_with_ocr(content)
        if text.strip():
            return text
        raise DocumentParseError(
            "PDF 未识别到可读取文字，请上传更清晰的扫描件或文字版 PDF",
            code="pdf_ocr_no_text",
        )


def extract_document_text(content: bytes, file_type: str) -> str:
    """Return bounded plain text for a supported document attachment."""

    try:
        if file_type == "pptx":
            text = _parse_pptx(content)
        elif file_type == "pdf":
            text = _extract_pdf_text(content)
        elif file_type in {"docx", "md", "txt", "csv", "xlsx"}:
            parsed = parse_document(content, file_type)
            # RAG keeps headings separately for citation display; an Agent
            # needs that context inline so Markdown/Word section names survive.
            text = _parsed_blocks_text(parsed)
        elif file_type in {"tsv", "text"}:
            text = content.decode("utf-8-sig", errors="replace")
        else:  # document_type_for is the only caller, but keep the boundary explicit.
            raise DocumentParseError("文件格式不受支持")
    except RAGError as exc:
        raise DocumentParseError("文件无法解析为文本") from exc
    result = _truncate(text)
    if not result:
        raise DocumentParseError("文件未包含可读取的文本")
    return result
