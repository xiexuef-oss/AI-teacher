"""健康检查、启动配置、本地身份 Mock。这三个操作不需要 token。"""

from __future__ import annotations

from functools import lru_cache

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from tutor_api import API_VERSION
from tutor_api.auth import LocalMockIdentityProvider
from tutor_api.deps import get_db, ok
from tutor_api.errors import not_found
from tutor_api.schemas import Health, LocalIdentityOut
from tutor_api.services.profile_service import build_launch_config
from tutor_api.settings import OPENAPI_PATH

router = APIRouter()


@lru_cache(maxsize=1)
def _contract_version() -> str:
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))["info"]["version"]


@router.get("/health")
def get_health(request: Request) -> JSONResponse:
    state = request.app.state
    return ok(
        Health(
            api_version=API_VERSION,
            contract_version=_contract_version(),
            environment=state.settings.env,
            local_identity_mock=state.settings.local_identity_mock,
            external_model_calls=state.gateway.external_calls_possible,
            server_time=state.clock(),
        )
    )


@router.get("/meta/launch-config")
def get_launch_config(request: Request) -> JSONResponse:
    return ok(build_launch_config(request.app.state.clock().date()))


@router.post("/dev/local-identities")
def create_local_identity(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    provider = request.app.state.identity_provider
    if not isinstance(provider, LocalMockIdentityProvider):
        # 未开启时与不存在的路径表现一致
        raise not_found()
    user, token = provider.issue_student(db, request.app.state.clock())
    db.commit()
    return ok(LocalIdentityOut(user_id=user.id, access_token=token), status_code=201)
