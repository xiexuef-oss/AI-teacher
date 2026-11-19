"""Idempotency-Key 处理（docs/05 §1）。

同一用户、同一个键：
- 请求完全相同 → 重放首次的成功响应，带 `Idempotency-Replayed: true`；
- 请求不同（包括用在别的操作上）→ 409 `idempotency_key_conflict`；
- 首次请求失败 → 不留记录，重试时重新执行。

去重记录与业务写入在同一个事务里提交，所以不会出现"业务生效了但记录没写上"的情况。
原型期兼容 proto_idempotency_records；正式回执与业务写入同一数据库事务，Redis只协调。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from tutor_api.deps import Ctx, dump
from tutor_api.errors import ApiError, conflict
from tutor_api.receipt_coordination import coordinate
from tutor_api.receipts import LegacyProtoReceiptStore
from tutor_api.services.parent_invite_security import replay_invite, stored_response

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotency-Replayed"
_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def read_key(ctx: Ctx) -> str:
    key = ctx.request.headers.get(HEADER)
    if key is None:
        raise ApiError(400, "idempotency_key_required", f"这个操作需要 {HEADER} 请求头")
    if not _KEY.match(key):
        raise ApiError(
            400, "invalid_idempotency_key", f"{HEADER} 应为 8~128 位的字母、数字或 . _ : -"
        )
    return key


def key_digest(student_id: str, key: str) -> str:
    """按用户加盐的键摘要，用于业务表里的唯一约束（不同用户用了同一个键也互不影响）。"""
    return hashlib.sha256(f"{student_id}:{key}".encode()).hexdigest()


def request_fingerprint(ctx: Ctx, body: Any) -> str:
    canonical = json.dumps(
        {"m": ctx.request.method, "p": ctx.request.url.path, "b": dump(body)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _store(ctx):
    return getattr(ctx.request.app.state, "receipt_store", None) or LegacyProtoReceiptStore()


def _lookup(ctx: Ctx, key: str):
    return _store(ctx).lookup(ctx, key, key_digest(ctx.actor_id, key))


def _replay(ctx: Ctx, record, fingerprint: str) -> JSONResponse:
    if record.fingerprint != fingerprint:
        raise conflict(
            "idempotency_key_conflict", "同一个 Idempotency-Key 已被用于另一个不同的请求"
        )
    return JSONResponse(
        status_code=record.status_code,
        content=replay_invite(ctx, record)
        if ctx.request.url.path.endswith("/me/parent-invites")
        else record.response_json,
        headers={REPLAYED_HEADER: "true"},
    )


def run_idempotent(
    ctx: Ctx, body: Any, status_code: int, action: Callable[[str], Any]
) -> JSONResponse:
    """执行一次非幂等动作。action 收到的是按用户加盐的键摘要，返回值作为响应的 data。"""
    key = read_key(ctx)
    fingerprint = request_fingerprint(ctx, body)
    existing = _lookup(ctx, key)
    if existing is not None:
        return _replay(ctx, existing, fingerprint)
    store = _store(ctx)
    digest = key_digest(ctx.actor_id, key)
    store.validate(ctx, digest, fingerprint)
    try:
        with coordinate(ctx, store, digest), store.protect(ctx):
            reserved = store.reserve(ctx, key, digest, fingerprint)
            payload = {"data": dump(action(digest))}
            stored = (
                stored_response(payload)
                if ctx.request.url.path.endswith("/me/parent-invites")
                else payload
            )
            store.finish(ctx, reserved, key, digest, fingerprint, status_code, stored)
            ctx.db.commit()
    except IntegrityError:
        # 并发的重复请求：另一方已经提交。回滚本次的全部写入，改为重放对方的结果。
        ctx.db.rollback()
        winner = _lookup(ctx, key)
        if winner is None:
            if store.durable:
                raise
            raise conflict("conflict", "与另一个并发请求冲突，请稍后重试") from None
        return _replay(ctx, winner, fingerprint)
    except ApiError:
        ctx.db.rollback()
        # 读取键后到业务取锁之间，同一请求可能已由并发重试提交。
        winner = _lookup(ctx, key)
        if winner is not None:
            return _replay(ctx, winner, fingerprint)
        raise
    except BaseException:
        ctx.db.rollback()
        raise
    return JSONResponse(status_code=status_code, content=payload)
