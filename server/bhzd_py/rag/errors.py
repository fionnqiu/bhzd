"""RAG 域错误类型与错误码（PRD-06 §5.3）。

为什么单独成模块：解析/切片/索引各阶段都会抛出业务错误，统一用 `RAGError`
携带 PRD-06 §5.3 的错误码，管线（pipeline）据此落库到 rag_jobs.error_code，
路由层据此映射为 HTTP 422（`to_api_error`）。错误消息必须是面向用户的中文。
"""

from __future__ import annotations

from ..errors import ApiError

# PRD-06 §5.3 失败错误码
PARSE_UNSUPPORTED = "PARSE_UNSUPPORTED"  # 文件格式暂不支持
PARSE_EMPTY_TEXT = "PARSE_EMPTY_TEXT"  # 未解析出文本（可能是扫描件）
CHUNK_EMPTY = "CHUNK_EMPTY"  # 切片为空
EMBEDDING_FAILED = "EMBEDDING_FAILED"  # 向量化失败
REVIEW_REQUIRED = "REVIEW_REQUIRED"  # 未审核/缺来源禁止送审
LICENSE_BLOCKED = "LICENSE_BLOCKED"  # 授权状态不允许发布

# §4.3 敏感信息阻止发布（PRD-06 §4.2「检测到明显敏感信息」）
SENSITIVE_INFO_BLOCKED = "SENSITIVE_INFO_BLOCKED"

# 各错误码的默认中文提示（PRD-06 §5.3「用户提示」列）
DEFAULT_MESSAGES = {
    PARSE_UNSUPPORTED: "文件格式暂不支持，请上传 PDF、Word、Markdown、CSV 或 Excel",
    PARSE_EMPTY_TEXT: "未解析出文本，文档可能是扫描件，请开启 OCR 或更换文件",
    CHUNK_EMPTY: "切片为空，请检查解析文本",
    EMBEDDING_FAILED: "向量化失败，模型连接异常，请稍后重试",
    REVIEW_REQUIRED: "资料需要审核后才能发布",
    LICENSE_BLOCKED: "资料授权状态不允许发布",
    SENSITIVE_INFO_BLOCKED: "检测到身份证号等敏感信息，需脱敏后才能发布",
}


class RAGError(Exception):
    """RAG 业务错误：`.code` 为 PRD-06 §5.3 错误码，`.message` 为中文提示。"""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGES.get(code, "处理失败，请稍后重试")
        super().__init__(self.message)


def to_api_error(exc: RAGError, status_code: int = 422) -> ApiError:
    """把 RAGError 映射为统一错误外壳（默认 422，路由层可覆盖状态码）。

    为什么走转换而不是注册 exception_handler：FastAPI 的 APIRouter 不支持
    注册异常处理器，而 app.py / errors.py 属于地基（只读），因此在路由边界
    用本函数把 RAGError 转成 ApiError，效果等同于"映射到 422 的 handler"。
    """
    return ApiError(status_code, exc.code, exc.message)
