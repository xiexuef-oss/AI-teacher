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
from typing import Protocol

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from ai_gateway import ModelGateway, ProviderAdapter, build_gateway
from tutor_api import API_PREFIX, proto_models, scan_models  # noqa: F401  （注册原型表）
from tutor_api.auth import DisabledIdentityProvider, IdentityProvider, LocalMockIdentityProvider
from tutor_api.blob_store import BlobStore, FilesystemBlobStore
from tutor_api.db import Base, create_session_factory, make_engine
from tutor_api.errors import install_error_handlers
from tutor_api.gateway_io import DbAuditSink, DbBudgetStore
from tutor_api.middleware import RequestContextMiddleware
from tutor_api.receipt_coordination import RedisReceiptCoordinator
from tutor_api.receipts import LegacyProtoReceiptStore, SqlReceiptStore
from tutor_api.routers import (
    admin,
    attempts,
    diagnostics,
    document_imports,
    draft_copies,
    learning,
    learning_jobs,
    media,
    parents,
    planned,
    profile,
    questions,
    reviews,
    school_materials,
    sessions,
    system,
    tutor,
)
from tutor_api.runtime_dependencies import (
    disabled_managed_router,
    managed_configuration,
    validate_managed_startup,
)
from tutor_api.services.content_seed import seed_if_empty
from tutor_api.services.document_import_worker import ImportWorker
from tutor_api.services.http_limits import (
    HttpLimitsMiddleware,
    InMemoryHttpLimiter,
    RedisHttpLimiter,
    validate_route_configuration,
)
from tutor_api.services.learning_pack_outbox import RedisPaperQueue
from tutor_api.services.learning_pack_worker import LearningPackWorker
from tutor_api.services.media_service import cleanup as cleanup_media
from tutor_api.services.parent_invite_security import InviteRedeemLimiter, scrub_legacy_responses
from tutor_api.settings import EVENT_SCHEMA_PATH, VISUAL_REGISTRY_PATH, Settings

Clock = Callable[[], datetime]


class InviteLimiter(Protocol):
    def check(self, actor_id: str, settings: Settings, now: datetime) -> None: ...


_LOCAL_ORIGIN = r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    gateway: ModelGateway | None = None,
    gateway_adapters: Mapping[str, ProviderAdapter] | None = None,
    identity_provider: IdentityProvider | None = None,
    media_store: BlobStore | None = None,
    parent_invite_limiter: InviteLimiter | None = None,
    receipt_store: LegacyProtoReceiptStore | SqlReceiptStore | None = None,
    receipt_coordinator: RedisReceiptCoordinator | None = None,
    http_limiter: InMemoryHttpLimiter | RedisHttpLimiter | None = None,
    paper_queue: RedisPaperQueue | None = None,
) -> FastAPI:
    """gateway_adapters 用来在测试里替换某个供应商的适配器；路由、预算与审计仍按配置走真实逻辑。"""
    settings = settings or Settings()
    from tutor_api.services import invocation_runtime

    invocation_runtime.validate_configuration(settings, receipt_store, gateway)
    validate_route_configuration(settings)
    if (
        settings.http_limits_enabled
        and settings.env != "local"
        and not isinstance(http_limiter, RedisHttpLimiter)
    ):
        raise ValueError("非local启用通用HTTP门控必须显式注入共享Redis适配器")
    if isinstance(identity_provider, LocalMockIdentityProvider) and settings.env != "local":
        raise ValueError("本地身份 Mock provider 只允许 local 环境")
    if identity_provider is not None and settings.local_identity_mock:
        raise ValueError("注入身份 provider 时必须关闭 local_identity_mock，不能混用身份来源")
    managed = managed_configuration(
        settings,
        identity_provider,
        media_store,
        parent_invite_limiter,
        receipt_store,
        receipt_coordinator,
        gateway,
    )
    clock = clock or (lambda: datetime.now(UTC))
    engine = make_engine(settings.database_url, settings=settings)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        worker = None
        pack_worker = None
        try:
            if managed:
                validate_managed_startup(
                    engine,
                    settings,
                    app.state.media_store,
                    app.state.parent_invite_limiter,
                    app.state.receipt_coordinator,
                    http_limiter=app.state.http_limiter,
                )
            else:
                from tutor_api.local_provenance_schema import upgrade_local_provenance_schema
                from tutor_api.local_schema import upgrade_local_draft_schema

                upgrade_local_draft_schema(engine)
                upgrade_local_provenance_schema(engine)
                Base.metadata.create_all(engine)
                with session_factory() as db:
                    scrub_legacy_responses(db)
                    db.commit()
                cleanup_media(session_factory, app.state.media_store, clock())
                from tutor_api.services.scan_service import cleanup

                with session_factory() as db:
                    cleanup(db, app.state.media_store, clock())
                if settings.seed_sample_content:
                    with session_factory() as db:
                        seed_if_empty(db, clock())
                        db.commit()
            app.state.invocation_store = invocation_runtime.initialize(
                engine,
                session_factory,
                settings,
                app.state.receipt_store,
                clock,
                managed=managed,
                gateway=app.state.gateway,
            )
            if not managed and settings.import_worker_enabled:
                worker = ImportWorker(
                    session_factory,
                    settings,
                    clock,
                    app.state.gateway,
                    invocation_store=app.state.invocation_store,
                )
                worker.start()
            if not managed and settings.learning_pack_worker_enabled:
                pack_worker = LearningPackWorker(
                    session_factory,
                    clock,
                    settings,
                    settings.learning_pack_sample_font if settings.seed_sample_content else None,
                    media_store=app.state.media_store,
                    gateway=app.state.gateway,
                    queue=paper_queue,
                    invocation_store=app.state.invocation_store,
                )
                pack_worker.start()
            yield
        finally:
            if pack_worker is not None:
                pack_worker.close()
            if worker is not None:
                worker.close()
            engine.dispose()

    app = FastAPI(
        title="AI 理科私教 API",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.parent_invite_limiter = (
        parent_invite_limiter if parent_invite_limiter is not None else InviteRedeemLimiter()
    )
    app.state.runtime_mode = "managed" if managed else "local_prototype"
    app.state.invocation_store = None
    app.state.receipt_store = (
        receipt_store if receipt_store is not None else LegacyProtoReceiptStore()
    )
    app.state.receipt_coordinator = receipt_coordinator
    app.state.http_limiter = (
        (http_limiter if http_limiter is not None else InMemoryHttpLimiter())
        if settings.http_limits_enabled
        else None
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.session_factory = session_factory
    app.state.media_store = (
        media_store
        if media_store is not None
        else (
            FilesystemBlobStore(
                settings.media_root,
                max_bytes=settings.media_max_bytes,
                temporary_ttl_seconds=settings.media_temporary_ttl_seconds,
            )
            if settings.env == "local" and settings.media_local_enabled
            else None
        )
    )
    app.state.identity_provider = (
        identity_provider
        if identity_provider is not None
        else (
            LocalMockIdentityProvider()
            if settings.local_identity_mock
            else DisabledIdentityProvider()
        )
    )
    # local 环境没配密钥时每次启动随机生成：去标识化 ID 只在本次运行内稳定，本机演示够用。
    app.state.pseudonym_secret = settings.pseudonym_secret or secrets.token_hex(32)
    app.state.gateway = (
        gateway
        if gateway is not None
        else build_gateway(
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
    )

    install_error_handlers(app)
    for module in (
        system,
        profile,
        learning_jobs,
        school_materials,
        questions,
        sessions,
        attempts,
        diagnostics,
        draft_copies,
        tutor,
        reviews,
        learning,
        admin,
        document_imports,
        media,
        parents,
        planned,
    ):
        router = (
            disabled_managed_router(module.router)
            if managed and module is document_imports
            else module.router
        )
        app.include_router(router, prefix=API_PREFIX)

    # 后添加的中间件在外层。请求上下文必须在最外层：这样包括跨域预检在内的每个响应都带请求 ID，
    # 回环限制也先于其他一切生效。
    if settings.http_limits_enabled:
        app.add_middleware(
            HttpLimitsMiddleware, settings=settings, limiter=app.state.http_limiter, clock=clock
        )
    if settings.env == "local":
        # 本地开发时 Flutter Web 的调试服务器与 API 不同源
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=_LOCAL_ORIGIN,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
            expose_headers=["X-Request-Id", "Idempotency-Replayed", "Retry-After"],
            max_age=600,
        )
    app.add_middleware(RequestContextMiddleware, loopback_only=settings.local_identity_mock)
    return app
