"""请求级依赖：数据库会话、当前用户、请求上下文。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from tutor_api.auth import Principal, parse_bearer
from tutor_api.errors import ApiError, request_id_of
from tutor_api.settings import Settings


def get_db(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        # 未提交的事务在这里回滚。提交一律在返回响应之前显式完成，
        # 不依赖依赖项的收尾代码（它可能在响应发出之后才执行）。
        session.close()


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    token = parse_bearer(request.headers.get("authorization"))
    principal = request.app.state.identity_provider.authenticate(db, token) if token else None
    if principal is None:
        raise ApiError(
            401, "unauthenticated", "未认证或 token 无效", headers={"WWW-Authenticate": "Bearer"}
        )
    return principal


def require_student(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "student":
        raise ApiError(403, "forbidden", "当前角色无权访问")
    return principal


@dataclass
class Ctx:
    """一次学生请求的上下文。权限只来自 principal，不来自请求体里的任何 ID。"""

    request: Request
    db: Session
    principal: Principal

    @property
    def settings(self) -> Settings:
        return self.request.app.state.settings

    @property
    def student_id(self) -> str:
        return self.principal.user_id

    @property
    def request_id(self) -> str:
        return request_id_of(self.request)

    def now(self) -> datetime:
        return self.request.app.state.clock()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """提交成功后才会继续往下走到构造响应；出错则回滚并原样抛出。"""
        try:
            yield self.db
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise


def student_ctx(
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_student),
) -> Ctx:
    return Ctx(request=request, db=db, principal=principal)


def dump(data: Any) -> Any:
    return data.model_dump(mode="json") if isinstance(data, BaseModel) else data


def ok(data: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"data": dump(data)}, headers=headers)
