"""家长与学生的绑定：学生明确授权、可撤销（PRD §3、US-06、docs/04 parent_student_links）。

原型阶段的授权方式（监护授权方案 Q-03 没有冻结，这不是对它的回答）：学生自己生成一次性邀请码，
家长输入后建立绑定。没有任何年龄判断，也不代表法定的监护人核验。几条贯穿始终的规则：

- 邀请码明文只在创建时返回一次，库里只存 SHA-256；用一次就作废；学生再生成一个，他之前没用掉的立刻作废；
- 邀请码不对、过期、用过、被顶替——对外一律 404 `invite_invalid`，不告诉调用方是哪一种；
- 绑定只有学生能撤销，撤销立即生效；家长读取学生的任何东西，都要求绑定存在且没有撤销，否则 404
  （与"学生不存在"的响应完全一样，防枚举）；
- 授权、绑定、撤销都写审计日志（谁、什么时候），不含邀请码。
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.errors import ApiError, conflict, not_found
from tutor_api.models import AuditLog, ParentInvite, ParentStudentLink, User
from tutor_api.schemas import (
    ParentLinkOut,
    ParentLinksOut,
    ParentStudentOut,
    ParentStudentsOut,
    PendingParentInviteOut,
)
from tutor_api.settings import Settings
from tutor_api.timefmt import iso

# 去掉了容易看错的 0 O 1 I L。十位、31 个字符：约 50 位随机，加上 24 小时有效期、一次有效，够本机原型用；
# 真实上线前还要补对兑换接口的限流（docs/05 §5）
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 10


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str | None:
    """家长输入的邀请码：忽略空格、短横线和大小写；格式不对返回 None。"""
    code = re.sub(r"[\s\-]", "", raw).upper()
    if len(code) != CODE_LENGTH or not set(code) <= set(CODE_ALPHABET):
        return None
    return code


def _invalid() -> ApiError:
    return ApiError(404, "invite_invalid", "邀请码不对，或者已经过期、已经被用过")


def _audit(
    db: Session,
    *,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict[str, Any],
    request_id: str,
    now: datetime,
) -> None:
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail_json=detail,
            request_id=request_id,
            created_at=now,
        )
    )


def _link_out(link: ParentStudentLink, parent: User) -> ParentLinkOut:
    return ParentLinkOut(
        id=link.id,
        parent_id=link.parent_id,
        parent_label=parent.display_name,
        consent_at=link.consent_at,
        linked_at=link.created_at,
        revoked_at=link.revoked_at,
    )


# ---------------------------------------------------------------- 学生：授权与撤销


def create_invite(
    db: Session, settings: Settings, student_id: str, *, now: datetime, request_id: str
) -> tuple[ParentInvite, str]:
    """生成邀请码，返回 (记录, 明文)。明文只在这一次出现。"""
    for old in db.scalars(
        select(ParentInvite).where(
            ParentInvite.student_id == student_id,
            ParentInvite.redeemed_at.is_(None),
            ParentInvite.revoked_at.is_(None),
        )
    ):
        old.revoked_at = now  # 再生成一个，旧的立刻作废

    code = new_code()
    invite = ParentInvite(
        id=new_id(),
        student_id=student_id,
        code_hash=_hash(code),
        expires_at=now + timedelta(minutes=settings.parent_invite_ttl_minutes),
        created_at=now,
    )
    db.add(invite)
    _audit(
        db,
        actor_id=student_id,
        action="parent.invite_created",
        target_type="parent_invite",
        target_id=invite.id,
        detail={"expires_at": iso(invite.expires_at)},
        request_id=request_id,
        now=now,
    )
    db.flush()
    return invite, code


def list_links(db: Session, student_id: str, *, now: datetime) -> ParentLinksOut:
    rows = db.execute(
        select(ParentStudentLink, User)
        .join(User, User.id == ParentStudentLink.parent_id)
        .where(ParentStudentLink.student_id == student_id, ParentStudentLink.revoked_at.is_(None))
        .order_by(ParentStudentLink.created_at, ParentStudentLink.id)
    ).all()
    pending = db.scalar(
        select(ParentInvite)
        .where(
            ParentInvite.student_id == student_id,
            ParentInvite.redeemed_at.is_(None),
            ParentInvite.revoked_at.is_(None),
            ParentInvite.expires_at > now,
        )
        .order_by(ParentInvite.created_at.desc(), ParentInvite.id)
        .limit(1)
    )
    return ParentLinksOut(
        links=[_link_out(link, parent) for link, parent in rows],
        pending_invite=(
            PendingParentInviteOut(
                id=pending.id, created_at=pending.created_at, expires_at=pending.expires_at
            )
            if pending
            else None
        ),
    )


def revoke_link(
    db: Session, student_id: str, link_id: str, *, now: datetime, request_id: str
) -> ParentLinkOut:
    """撤销立即生效。别人的、不存在的、已经撤销过的授权都是 404。"""
    link = db.get(ParentStudentLink, link_id)
    if link is None or link.student_id != student_id or link.revoked_at is not None:
        raise not_found()
    link.revoked_at = now
    _audit(
        db,
        actor_id=student_id,
        action="parent.link_revoked",
        target_type="parent_student_link",
        target_id=link.id,
        detail={"parent_id": link.parent_id},
        request_id=request_id,
        now=now,
    )
    db.flush()
    parent = db.get(User, link.parent_id)
    assert parent is not None
    return _link_out(link, parent)


# ---------------------------------------------------------------- 家长：绑定与查看


def redeem_invite(
    db: Session, parent_id: str, raw_code: str, *, now: datetime, request_id: str
) -> ParentStudentOut:
    code = normalize_code(raw_code)
    invite = (
        db.scalar(select(ParentInvite).where(ParentInvite.code_hash == _hash(code)))
        if code
        else None
    )
    if (
        invite is None
        or invite.redeemed_at is not None
        or invite.revoked_at is not None
        or invite.expires_at <= now
    ):
        raise _invalid()
    student = db.get(User, invite.student_id)
    if student is None or student.status != "active" or student.role != "student":
        raise _invalid()

    link = db.scalar(
        select(ParentStudentLink).where(
            ParentStudentLink.parent_id == parent_id,
            ParentStudentLink.student_id == invite.student_id,
        )
    )
    if link is not None and link.revoked_at is None:
        raise conflict("already_linked", "已经绑定着这位学生了")
    if link is None:
        link = ParentStudentLink(
            id=new_id(),
            parent_id=parent_id,
            student_id=invite.student_id,
            consent_at=invite.created_at,
            created_at=now,
        )
        db.add(link)
    else:
        # 同一对家长和学生只有一行：撤销之后重新授权，就重新打开它，同意和绑定的时间都换成这一次的
        link.revoked_at = None
        link.consent_at = invite.created_at
        link.created_at = now
    invite.redeemed_at = now
    invite.redeemed_by = parent_id
    _audit(
        db,
        actor_id=parent_id,
        action="parent.link_created",
        target_type="parent_student_link",
        target_id=link.id,
        detail={"student_id": invite.student_id, "invite_id": invite.id},
        request_id=request_id,
        now=now,
    )
    db.flush()
    return ParentStudentOut(
        student_id=student.id, display_name=student.display_name, linked_at=link.created_at
    )


def list_students(db: Session, parent_id: str) -> ParentStudentsOut:
    rows = db.execute(
        select(ParentStudentLink, User)
        .join(User, User.id == ParentStudentLink.student_id)
        .where(
            ParentStudentLink.parent_id == parent_id,
            ParentStudentLink.revoked_at.is_(None),
            User.status == "active",
        )
        .order_by(ParentStudentLink.created_at, ParentStudentLink.id)
    ).all()
    return ParentStudentsOut(
        items=[
            ParentStudentOut(
                student_id=student.id, display_name=student.display_name, linked_at=link.created_at
            )
            for link, student in rows
        ]
    )


def require_link(db: Session, parent_id: str, student_id: str) -> tuple[ParentStudentLink, User]:
    """这位家长现在能不能看这个学生。不能（没绑定、已撤销、学生不存在）一律 404，三者无法区分。"""
    row = db.execute(
        select(ParentStudentLink, User)
        .join(User, User.id == ParentStudentLink.student_id)
        .where(
            ParentStudentLink.parent_id == parent_id,
            ParentStudentLink.student_id == student_id,
            ParentStudentLink.revoked_at.is_(None),
            User.status == "active",
        )
    ).first()
    if row is None:
        raise not_found()
    return row[0], row[1]
