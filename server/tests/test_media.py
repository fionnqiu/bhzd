from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

from bhzd_py.agent import documents, media


def _png_bytes(size: tuple[int, int] = (64, 40)) -> bytes:
    """Make a valid fixture image so thumbnail assertions exercise real decoding."""

    buffer = io.BytesIO()
    Image.new("RGB", size, color=(29, 85, 143)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_media_cache_is_owner_scoped_and_expires(monkeypatch):
    """The in-process cache must enforce both ownership and its TTL."""

    current_time = 1_000.0
    monkeypatch.setattr(media.time, "time", lambda: current_time)
    item = media.store("user-a", "photo.png", "image/png", b"image")

    assert media.get(item.token, "user-a") == item
    assert media.get(item.token, "user-b") is None

    current_time += media.MEDIA_TTL_SECONDS + 1
    assert media.get(item.token, "user-a") is None


def test_document_attachment_extracts_markdown_without_changing_cache_contract():
    """Common text documents become bounded context while retaining owner-scoped bytes."""

    item = media.store("user-a", "notes.md", "text/markdown", b"# Heading\n\nUse this note.")

    assert item.kind == "document"
    assert item.extracted_text == "Heading\nUse this note."
    assert media.get(item.token, "user-a") == item


def test_media_cache_limits_one_owner_to_the_multi_file_total(monkeypatch):
    """Repeated uploads cannot bypass the 100MB batch limit before send time."""

    monkeypatch.setattr(media, "MAX_USER_MEDIA_BYTES", 4)
    first = media.store("quota-user", "first.mp3", "audio/mpeg", b"abc")
    try:
        with pytest.raises(ValueError, match="media_total_too_large"):
            media.store("quota-user", "second.mp3", "audio/mpeg", b"de")
    finally:
        media.discard(first.token, "quota-user")


def test_scanned_pdf_attachment_uses_ocr_fallback(monkeypatch):
    """An image-only PDF must reach local OCR before the upload is rejected."""

    from pypdf import PdfWriter

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buffer)
    monkeypatch.setattr(documents, "_extract_pdf_text_with_ocr", lambda _content: "扫描件中的课堂要求")

    item = media.store("user-a", "scanned.pdf", "application/pdf", buffer.getvalue())

    assert item.kind == "document"
    assert item.extracted_text == "扫描件中的课堂要求"


def test_scanned_pdf_without_ocr_text_returns_specific_reason(monkeypatch):
    """A completed OCR pass with no text stays rejected with a useful API reason."""

    from pypdf import PdfWriter

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buffer)
    monkeypatch.setattr(documents, "_extract_pdf_text_with_ocr", lambda _content: "")

    with pytest.raises(ValueError, match="pdf_ocr_no_text"):
        media.store("user-a", "blank.pdf", "application/pdf", buffer.getvalue())


def test_pptx_attachment_extracts_slide_text_without_external_renderer():
    """PPTX is a zip/XML container, so only its text nodes are accepted."""

    slide = b'<p:sld xmlns:p="urn:p"><p:cSld><a:t xmlns:a="urn:a">Slide text</a:t></p:cSld></p:sld>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)

    item = media.store("user-a", "lesson.pptx", "application/octet-stream", buffer.getvalue())

    assert item.kind == "document"
    assert item.extracted_text == "Slide text"


def test_unknown_binary_attachment_is_rejected():
    with pytest.raises(ValueError, match="unsupported_media_type"):
        media.store("user-a", "payload.zip", "application/zip", b"PK")


def test_media_thumbnail_is_bounded_webp_and_does_not_retain_the_source_format():
    """A persisted preview is a small derived rendering, not the uploaded PNG."""

    source = _png_bytes((1_024, 640))
    item = media.store("user-a", "photo.png", "image/png", source)

    thumbnail = media.thumbnail_for(item)

    assert thumbnail is not None
    assert thumbnail.mime_type == "image/webp"
    assert thumbnail.content != source
    assert len(thumbnail.content) <= media.MAX_THUMBNAIL_BYTES
    with Image.open(io.BytesIO(thumbnail.content)) as preview:
        assert preview.format == "WEBP"
        assert max(preview.size) <= media.MAX_THUMBNAIL_EDGE


def test_media_thumbnail_rejects_unsafe_or_malformed_image_without_rejecting_the_item(monkeypatch):
    """Preview generation is optional so malformed images still have a file card."""

    malformed = media.store("user-a", "broken.png", "image/png", b"not-a-real-image")
    assert media.thumbnail_for(malformed) is None

    valid = media.store("user-a", "small.png", "image/png", _png_bytes((3, 3)))
    monkeypatch.setattr(media, "MAX_THUMBNAIL_SOURCE_PIXELS", 4)
    assert media.thumbnail_for(valid) is None
