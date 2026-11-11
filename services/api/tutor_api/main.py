"""应用工厂。

本地运行（仅回环地址）见 tools/run_dev_api.ps1。公开契约是 contracts/openapi.yaml，
所以这里关闭了 FastAPI 自动生成的文档，避免出现两份可能不一致的接口描述。
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from ai_gateway import ModelGateway, ProviderAdapter, build_gateway
from tutor_api import API_PREFIX, proto_models  # noqa: F401  （注册原型表）
from tutor_api.auth import DisabledIdentityProvider, LocalMockIdentityProvider
from tutor_api.db import Base, create_session_factory, make_engine
from tutor_api.errors import install_error_handlers
from tutor_api.gateway_io import DbAuditSink, DbBudgetStore
from tutor_api.middleware import RequestContextMiddleware
from tutor_api.routers import (
    attempts,
    learning,
    planned,
    profile,
    questions,
    reviews,
    sessions,
    system,
    tutor,
)
from tutor_api.services.content_seed import seed_if_empty
from tutor_api.settings import EVENT_SCHEMA_PATH, VISUAL_REGISTRY_PATH, Settings

Clock = Callable[[], datetime]

_LOCAL_ORIGIN = r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    gateway: ModelGateway | None = None,
    gateway_adapters: Mapping[str, ProviderAdapter] | None = None,
) -> FastAPI:
    """gateway_adapters 用来在测试里替换某个供应商的适配器；路由、预算与审计仍按配置走真实逻辑。"""
    settings = settings or Settings()
    clock = clock or (lambda: datetime.now(UTC))
    engine = make_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # 原型库直接按 ORM 建表（ADR-006）；生产结构以 migrations/*.sql 为准。
        Base.metadata.create_all(engine)
        if settings.seed_sample_content:
            with session_factory() as db:
                seed_if_empty(db, clock())
                db.commit()
        yield
        engine.dispose()

    app = FastAPI(
        title="AI 理科私教 API",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.session_factory = session_factory
    app.state.identity_provider = (
        LocalMockIdentityProvider() if settings.local_identity_mock else DisabledIdentityProvider()
    )
    # local 环境没配密钥时每次启动随机生成：去标识化 ID 只在本次运行内稳定，本机演示够用。
    app.state.pseudonym_secret = settings.pseudonym_secret or secrets.token_hex(32)
    app.state.gateway = gateway or build_gateway(
        settings.model_routes_path,
        env=os.environ,
        environment=settings.env,
        allow_external_calls=settings.allow_external_model_calls,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        audit=DbAuditSink(session_factory),
        budget_store=DbBudgetStore(session_factory, clock),
        adapter_overrides=gateway_adapters,
        now=clock,
    )

    install_error_handlers(app)
    for module in (
        system,
        profile,
        questions,
        sessions,
        attempts,
        tutor,
        reviews,
        learning,
        planned,
    ):
        app.include_router(module.router, prefix=API_PREFIX)

    # 后添加的中间件在外层。请求上下文必须在最外层：这样包括跨域预检在内的每个响应都带请求 ID，
    # 回环限制也先于其他一切生效。
    if settings.env == "local":
        # 本地开发时 Flutter Web 的调试服务器与 API 不同源
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=_LOCAL_ORIGIN,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
            expose_headers=["X-Request-Id", "Idempotency-Replayed"],
            max_age=600,
        )
    app.add_middleware(RequestContextMiddleware, loopback_only=settings.local_identity_mock)
    return app
