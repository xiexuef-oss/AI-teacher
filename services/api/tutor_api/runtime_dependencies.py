"""Explicit managed dev/staging dependencies. Read-only startup, never a prod permit."""

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from tutor_api.auth import DisabledIdentityProvider, LocalMockIdentityProvider
from tutor_api.blob_store import FilesystemBlobStore
from tutor_api.db import Base
from tutor_api.deps import Ctx, reviewer_ctx, student_ctx
from tutor_api.errors import ApiError, not_found
from tutor_api.receipt_coordination import RedisReceiptCoordinator
from tutor_api.receipts import SqlReceiptStore
from tutor_api.s3_blob_store import S3BlobStore, validate_local_s3_client
from tutor_api.services.parent_invite_rate_limit import RedisInviteRedeemLimiter
from tutor_api.settings import REPO_ROOT


def managed_configuration(settings, identity, media, limiter, receipts, coordinator, gateway):
    if settings.env == "prod":
        raise ValueError("生产存储和决策尚未完整验收，prod发布仍被禁止")
    try:
        url = make_url(settings.database_url)
    except Exception:
        raise ValueError("数据库配置无效") from None
    if settings.env == "local":
        if url.get_backend_name() != "sqlite":
            raise ValueError("local仅允许SQLite原型；MySQL须使用显式dev/staging生产存储依赖")
        return False
    requirements = (
        settings.env in {"dev", "staging"},
        url.drivername == "mysql+pymysql",
        bool(settings.pseudonym_secret),
        not settings.local_identity_mock,
        not settings.seed_sample_content,
        not settings.import_worker_enabled,
        not settings.allow_external_model_calls,
        identity is not None
        and not isinstance(identity, (LocalMockIdentityProvider, DisabledIdentityProvider)),
        callable(getattr(identity, "authenticate", None)),
        isinstance(receipts, SqlReceiptStore),
        isinstance(media, (FilesystemBlobStore, S3BlobStore)),
        isinstance(limiter, RedisInviteRedeemLimiter),
        coordinator is None or isinstance(coordinator, RedisReceiptCoordinator),
        not bool(getattr(gateway, "external_calls_possible", False)),
        not bool(getattr(gateway, "_allow_external_calls", False)),
    )
    if not all(requirements):
        raise ValueError("非local生产存储须显式依赖、关闭原型bootstrap及外部模型，不能静默回退")
    if isinstance(media, S3BlobStore):
        validate_local_s3_client(media.client)
    return True


def validate_managed_startup(engine, settings, media, limiter, coordinator, *, http_limiter=None):
    """Only SELECT/metadata/PING, scoped S3 LIST or stat; no DDL, seed, cleanup or quota."""
    try:
        paths = sorted((REPO_ROOT / "migrations").glob("*.sql"))
        expected = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        if not expected:
            raise ValueError("迁移文件缺失")
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            if "schema_migration_ledger" not in tables or any(
                name.startswith("proto_") for name in tables
            ):
                raise ValueError("迁移未就绪或存在proto表")
            rows = list(
                connection.execute(
                    text("SELECT name, sha256, state FROM schema_migration_ledger")
                ).mappings()
            )
            if len(rows) != len(expected) or {row["name"] for row in rows} != set(expected):
                raise ValueError("迁移历史不完整")
            if any(
                row["state"] != "applied" or row["sha256"] != expected[row["name"]] for row in rows
            ):
                raise ValueError("迁移状态或校验和不匹配")
            for table in Base.metadata.sorted_tables:
                if table.name.startswith("proto_"):
                    continue
                if table.name not in tables:
                    raise ValueError("业务表缺失")
                actual = {column["name"] for column in inspector.get_columns(table.name)}
                if not set(table.columns.keys()) <= actual:
                    raise ValueError("业务列缺失")
        if isinstance(media, S3BlobStore):
            if media.ping() is not True:
                raise ValueError("显式S3媒体不可用")
        else:
            root = Path(media.root)
            if not root.is_dir() or root.is_symlink() or root.resolve(strict=True) != root:
                raise ValueError("显式媒体root不可用")
        clients = [limiter.client] + ([coordinator.client] if coordinator is not None else [])
        if http_limiter is not None:
            clients.append(http_limiter.client)
        for client in clients:
            if client.ping() is not True:
                raise ValueError("Redis依赖不可用")
    except Exception:
        raise ValueError("受控运行依赖校验失败；迁移、媒体或Redis未就绪，未自动修复") from None


def disabled_managed_router(original, *, tutor=False):
    router = APIRouter()
    if tutor:

        def unavailable(ctx: Ctx = Depends(student_ctx)):
            raise not_found()
    else:

        def unavailable(ctx: Ctx = Depends(reviewer_ctx)):
            raise ApiError(501, "not_implemented", "原型导入事务尚未适配受控MySQL运行")

    for route in original.routes:
        router.add_api_route(
            route.path, unavailable, methods=sorted(route.methods), name=route.name
        )
    return router
