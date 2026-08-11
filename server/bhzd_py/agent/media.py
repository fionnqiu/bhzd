"""Short-lived Agent file attachments.

Uploads are kept in a bounded in-process cache instead of business tables.  The
run envelope stores only an owner-scoped token, so a conversation reload cannot
turn an old image, video, or audio payload into a durable data export.
"""

from __future__ import annotations

from io import BytesIO
import secrets
import threading
import time
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps

from .documents import DocumentParseError, document_type_for, extract_document_text

MAX_MEDIA_BYTES = 20 * 1024 * 1024
MAX_USER_MEDIA_BYTES = 100 * 1024 * 1024
MEDIA_TTL_SECONDS = 15 * 60
ALLOWED_MEDIA_PREFIXES = ("image/", "video/", "audio/")

# A retained preview is deliberately much smaller than its source. These
# independent limits bound decoder work, the rendered surface, and the data we
# keep after the short-lived upload cache is released.
MAX_THUMBNAIL_SOURCE_EDGE = 12_000
MAX_THUMBNAIL_SOURCE_PIXELS = 12_000_000
MAX_THUMBNAIL_EDGE = 512
MAX_THUMBNAIL_BYTES = 256 * 1024
THUMBNAIL_MIME_TYPE = "image/webp"
_THUMBNAIL_QUALITIES = (78, 62, 46, 30)


@dataclass(frozen=True)
class MediaAttachment:
    token: str
    user_id: str
    filename: str
    mime_type: str
    kind: str
    size: int
    content: bytes
    extracted_text: str | None
    expires_at: float


@dataclass(frozen=True)
class MediaThumbnail:
    """A bounded, derived preview safe to persist with a sent message."""

    content: bytes
    mime_type: str = THUMBNAIL_MIME_TYPE


_LOCK = threading.Lock()
_STORE: dict[str, MediaAttachment] = {}


def _media_kind(mime_type: str) -> str | None:
    for prefix in ALLOWED_MEDIA_PREFIXES:
        if mime_type.startswith(prefix):
            return prefix[:-1]
    return None


def _prune(now: float) -> None:
    expired = [token for token, item in _STORE.items() if item.expires_at <= now]
    for token in expired:
        _STORE.pop(token, None)


def store(user_id: str, filename: str, mime_type: str, content: bytes) -> MediaAttachment:
    """Validate and retain one user-owned media or document for the next run."""

    normalized_type = (mime_type or "").split(";", 1)[0].strip().lower()
    safe_name = " ".join((filename or "upload").split())[:160] or "upload"
    # Filename wins for document formats because browsers label `.ts` as video/mp2t
    # and Office/Markdown MIME strings are inconsistent across operating systems.
    document_type = document_type_for(safe_name)
    kind = "document" if document_type else _media_kind(normalized_type)
    if kind is None:
        raise ValueError("unsupported_media_type")
    if len(content) > MAX_MEDIA_BYTES:
        raise ValueError("media_too_large")
    extracted_text: str | None = None
    if document_type:
        try:
            extracted_text = extract_document_text(content, document_type)
        except DocumentParseError as exc:
            # Preserve the parser's coarse reason without exposing implementation
            # details; routers map it to a stable, user-facing API error.
            raise ValueError(exc.code) from exc
    now = time.time()
    token = secrets.token_urlsafe(32)
    item = MediaAttachment(
        token=token,
        user_id=user_id,
        filename=safe_name,
        mime_type=normalized_type,
        kind=kind,
        size=len(content),
        content=content,
        extracted_text=extracted_text,
        expires_at=now + MEDIA_TTL_SECONDS,
    )
    with _LOCK:
        _prune(now)
        # A run can contain up to ten independently uploaded files. Bound the
        # owner's live cache as well, so abandoned selections cannot grow the
        # process beyond the same 100MB aggregate limit enforced at send time.
        owner_bytes = sum(
            stored.size for stored in _STORE.values() if stored.user_id == user_id
        )
        if owner_bytes + item.size > MAX_USER_MEDIA_BYTES:
            raise ValueError("media_total_too_large")
        _STORE[token] = item
    return item


def get(token: str, user_id: str) -> MediaAttachment | None:
    """Return an unexpired attachment only for its owning user."""

    now = time.time()
    with _LOCK:
        _prune(now)
        item = _STORE.get(token)
        if item is None or item.user_id != user_id:
            return None
        return item


def discard(token: str, user_id: str) -> None:
    """Release a consumed token without affecting another user's attachment."""

    with _LOCK:
        item = _STORE.get(token)
        if item is not None and item.user_id == user_id:
            _STORE.pop(token, None)


def thumbnail_for(item: MediaAttachment) -> MediaThumbnail | None:
    """Create a bounded WebP preview without retaining an uploaded original.

    Image bytes are untrusted, so decoding remains optional: malformed, overly
    large, or unsupported images still become a durable file card while this
    function returns ``None``. Keeping preview failure non-fatal preserves the
    existing provider-delivery contract for media attachments.
    """

    if item.kind != "image":
        return None

    try:
        # Pillow warns before attempting some decompression bombs. Turn that
        # warning into a local failure so a forged image cannot bypass our
        # metadata checks by relying on a permissive process-wide default.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(item.content)) as source:
                width, height = source.size
                if (
                    width <= 0
                    or height <= 0
                    or width > MAX_THUMBNAIL_SOURCE_EDGE
                    or height > MAX_THUMBNAIL_SOURCE_EDGE
                    or width * height > MAX_THUMBNAIL_SOURCE_PIXELS
                ):
                    return None

                # ``load`` validates the compressed pixel data before we make
                # a resized copy; that avoids persisting a preview for a file
                # which advertised dimensions but cannot actually decode.
                source.seek(0)
                source.load()
                preview = ImageOps.exif_transpose(source)
                if preview.mode not in {"RGB", "RGBA"}:
                    preview = preview.convert(
                        "RGBA" if "transparency" in preview.info else "RGB"
                    )
                preview.thumbnail((MAX_THUMBNAIL_EDGE, MAX_THUMBNAIL_EDGE), Image.Resampling.LANCZOS)

                for quality in _THUMBNAIL_QUALITIES:
                    target = BytesIO()
                    preview.save(target, format="WEBP", quality=quality, method=4)
                    content = target.getvalue()
                    if content and len(content) <= MAX_THUMBNAIL_BYTES:
                        return MediaThumbnail(content=content)
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ):
        # The message still records server-verified file metadata. A thumbnail
        # is a convenience, never a reason to reject a valid media run.
        return None
    return None
