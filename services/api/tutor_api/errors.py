"""统一错误信封：{"error": {"code", "message", "details", "request_id"}}，不返回栈信息。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from tutor_api.blob_store import BlobStorageUnavailable, BlobWriteConflict

logger = logging.getLogger("tutor_api")

REQUEST_ID_HEADER = "X-Request-Id"


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


def not_found(message: str = "资源不存在") -> ApiError:
    """资源不存在，或不属于当前用户——两种情况对外不作区分（防枚举）。"""
    return ApiError(404, "not_found", message)


def conflict(code: str, message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(409, code, message, details)


def unprocessable(field: str, message: str) -> ApiError:
    return ApiError(
        422,
        "validation_error",
        "请求字段不合法",
        {"errors": [{"field": field, "message": message, "type": "value_error"}]},
    )


def request_id_of(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
    return request_id


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = request_id_of(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
            }
        },
        headers={REQUEST_ID_HEADER: request_id, **(headers or {})},
    )


def _field(loc: tuple[Any, ...]) -> str:
    parts = [str(p) for p in loc]
    if parts and parts[0] in {"body", "query", "path", "header"}:
        source, parts = parts[0], parts[1:]
        if not parts or all(p.isdigit() for p in parts):
            return source
    return ".".join(parts) or "body"


_HTTP_CODES = {404: ("not_found", "资源不存在"), 405: ("method_not_allowed", "不支持的请求方法")}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BlobWriteConflict)
    @app.exception_handler(BlobStorageUnavailable)
    async def _storage_error(request: Request, exc: Exception) -> JSONResponse:
        status, code, message = (
            (409, "storage_conflict", "媒体状态已变化，请保留原操作后重试")
            if isinstance(exc, BlobWriteConflict)
            else (503, "storage_unavailable", "媒体存储暂不可用，请保留原操作后重试")
        )
        return error_response(
            request,
            status,
            code,
            message,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(
            request, exc.status_code, exc.code, exc.message, exc.details, exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 只返回字段、消息和类型；不回显用户输入
        errors = [
            {"field": _field(tuple(e["loc"])), "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return error_response(
            request, 422, "validation_error", "请求字段不合法", {"errors": errors}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(exc.status_code, ("http_error", "请求无法处理"))
        return error_response(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error request_id=%s", request_id_of(request))
        return error_response(request, 500, "internal_error", "服务内部错误")
