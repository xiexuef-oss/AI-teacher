"""鉴权。

身份来自可替换的 IdentityProvider。原型期只有本地 Mock（Q-03）：每个本地学生绑定一个随机 bearer，
库里只存哈希。真实登录、refresh 轮换与监护授权在登录方式冻结后另行实现。
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.models import StudentProfile, User
from tutor_api.proto_models import LocalIdentity


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str


class IdentityProvider(Protocol):
    def authenticate(self, db: Session, token: str) -> Principal | None: ...


class DisabledIdentityProvider:
    """没有配置任何身份来源：所有 token 都无效。"""

    def authenticate(self, db: Session, token: str) -> Principal | None:
        return None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LocalMockIdentityProvider:
    def issue_identity(self, db: Session, now: datetime, role: str = "student") -> tuple[User, str]:
        """创建一个本地用户并返回 (用户, 明文 token)。token 只在这里出现一次。

        角色只有 student、reviewer、admin：本地联调内容审核后台用；家长要等监护授权方案（Q-03）冻结。
        """
        user = User(id=new_id(), role=role, status="active", created_at=now, updated_at=now)
        db.add(user)
        db.flush()
        if role == "student":
            db.add(StudentProfile(user_id=user.id, created_at=now, updated_at=now))
        token = secrets.token_urlsafe(32)
        db.add(LocalIdentity(token_hash=_hash_token(token), user_id=user.id, created_at=now))
        return user, token

    def issue_student(self, db: Session, now: datetime) -> tuple[User, str]:
        return self.issue_identity(db, now, "student")

    def authenticate(self, db: Session, token: str) -> Principal | None:
        user = db.scalar(
            select(User)
            .join(LocalIdentity, LocalIdentity.user_id == User.id)
            .where(LocalIdentity.token_hash == _hash_token(token), User.status == "active")
        )
        return Principal(user_id=user.id, role=user.role) if user else None


def parse_bearer(header_value: str | None) -> str | None:
    if not header_value:
        return None
    scheme, _, token = header_value.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token
