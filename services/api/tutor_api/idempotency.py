"""Idempotency-Key 处理（docs/05 §1）。

同一用户、同一个键：
- 请求完全相同 → 重放首次的成功响应，带 `Idempotency-Replayed: true`；
- 请求不同（包括用在别的操作上）→ 409 `idempotency_key_conflict`；
- 首次请求失败 → 不留记录，重试时重新执行。

去重记录与业务写入在同一个事务里提交，所以不会出现"业务生效了但记录没写上"的情况。
原型期记录存在 SQLite（proto_idempotency_records）；生产环境按 docs/02 放 Redis。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tutor_api.db import new_id
from tutor_api.deps import Ctx, dump
from tutor_api.errors import ApiError, conflict
from tutor_api.proto_models import IdempotencyRecord

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


def _fingerprint(ctx: Ctx, body: Any) -> str:
    canonical = json.dumps(
        {"m": ctx.request.method, "p": ctx.request.url.path, "b": dump(body)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _lookup(ctx: Ctx, key: str) -> IdempotencyRecord | None:
    return ctx.db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == ctx.student_id, IdempotencyRecord.idempotency_key == key
        )
    )


def _replay(record: IdempotencyRecord, fingerprint: str) -> JSONResponse:
    if record.fingerprint != fingerprint:
        raise conflict(
            "idempotency_key_conflict", "同一个 Idempotency-Key 已被用于另一个不同的请求"
        )
    return JSONResponse(
        status_code=record.status_code,
        content=record.response_json,
        headers={REPLAYED_HEADER: "true"},
    )


def run_idempotent(
    ctx: Ctx, body: Any, status_code: int, action: Callable[[str], Any]
) -> JSONResponse:
    """执行一次非幂等动作。action 收到的是按用户加盐的键摘要，返回值作为响应的 data。"""
    key = read_key(ctx)
    fingerprint = _fingerprint(ctx, body)
    existing = _lookup(ctx, key)
    if existing is not None:
        return _replay(existing, fingerprint)

    try:
        payload = {"data": dump(action(key_digest(ctx.student_id, key)))}
        ctx.db.add(
            IdempotencyRecord(
                id=new_id(),
                user_id=ctx.student_id,
                idempotency_key=key,
                fingerprint=fingerprint,
                status_code=status_code,
                response_json=payload,
                created_at=ctx.now(),
            )
        )
        ctx.db.commit()
    except IntegrityError:
        # 并发的重复请求：另一方已经提交。回滚本次的全部写入，改为重放对方的结果。
        ctx.db.rollback()
        winner = _lookup(ctx, key)
        if winner is None:
            raise conflict("conflict", "与另一个并发请求冲突，请稍后重试") from None
        return _replay(winner, fingerprint)
    except BaseException:
        ctx.db.rollback()
        raise
    return JSONResponse(status_code=status_code, content=payload)
