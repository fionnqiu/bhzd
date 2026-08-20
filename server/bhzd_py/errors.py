"""统一错误格式（蓝图 §4）：`{"error":{"code","message"}}` + 恰当 HTTP 状态。

为什么单独成模块：所有 router 只抛 `ApiError`，序列化、日志、兜底集中在
这里处理，保证学生端永远看不到堆栈（PRD-01 §3.5 失败态要求）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """业务错误：code 用 SNAKE_CODE，message 必须是面向用户的中文。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        # Selected failures need machine-readable recovery data (for example a
        # retry delay), while the default error shell stays concise and safe.
        self.details = details
        self.headers = dict(headers or {})


def _error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def register_error_handlers(app: FastAPI) -> None:
    """注册统一错误处理器；兜底 handler 绝不泄露堆栈与内部细节。"""

    @app.exception_handler(ApiError)
    async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # FastAPI 内置 404/405 等也统一成同样的错误外壳
        message = exc.detail if isinstance(exc.detail, str) else "请求无法处理"
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("HTTP_ERROR", message),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 校验细节只进日志，对外给笼统提示，避免暴露内部字段结构
        logger.info("请求参数校验失败: %s", exc.errors())
        return JSONResponse(
            status_code=422,
            content=_error_body("VALIDATION_ERROR", "请求参数不完整或格式不正确"),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # 兜底：完整堆栈进服务端日志，响应体只有通用中文提示
        logger.exception("未处理的服务端异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content=_error_body("INTERNAL_ERROR", "服务器开小差了，请稍后重试"),
        )
