"""Sensitive invite replay and the default RAM limiter compatibility export."""

import hashlib
import hmac

from sqlalchemy import select

from tutor_api.errors import conflict
from tutor_api.models import ParentInvite
from tutor_api.services.parent_invite_rate_limit import (
    InMemoryInviteRedeemLimiter as InviteRedeemLimiter,  # noqa: F401
)

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def derive_code(secret, invite_id):
    digest = hmac.new(
        secret.encode(), ("parent-invite/v1:" + invite_id).encode(), hashlib.sha256
    ).digest()
    value = int.from_bytes(digest, "big")
    result = ""
    for _ in range(10):
        value, digit = divmod(value, len(ALPHABET))
        result += ALPHABET[digit]
    return result


def stored_response(payload):
    data = dict(payload["data"])
    data.pop("code", None)
    return {"data": data}


def scrub_legacy_responses(db):
    from tutor_api.proto_models import IdempotencyRecord

    for row in db.scalars(select(IdempotencyRecord)):
        data = row.response_json.get("data", {})
        if isinstance(data, dict) and {"id", "code", "expires_at", "created_at"} <= data.keys():
            row.response_json = stored_response(row.response_json)


def replay_invite(ctx, record):
    payload = stored_response(record.response_json)
    if payload != record.response_json:
        record.response_json = payload
        ctx.db.commit()
    data = payload["data"]
    invite = ctx.db.get(ParentInvite, data["id"])
    code = derive_code(ctx.request.app.state.pseudonym_secret, data["id"])
    if (
        invite is None
        or invite.student_id != ctx.student_id
        or invite.expires_at <= ctx.now()
        or invite.revoked_at is not None
        or invite.redeemed_at is not None
        or not hmac.compare_digest(invite.code_hash, hashlib.sha256(code.encode()).hexdigest())
    ):
        raise conflict("invite_response_expired", "邀请码响应已失效，请用新的幂等键重新生成")
    return {"data": {**data, "code": code}}
