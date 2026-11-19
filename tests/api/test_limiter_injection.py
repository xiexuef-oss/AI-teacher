from starlette.testclient import TestClient

from support.api import LOOPBACK, ApiClient
from tutor_api.errors import ApiError
from tutor_api.main import create_app


def test_injected_limiter_is_used_after_role_check(settings, clock, parent, student):
    calls = []

    class Limiter:
        def check(self, actor, settings, now):
            calls.append(actor)
            raise ApiError(
                429, "invite_rate_limited", "请求过于频繁，请稍后再试", headers={"Retry-After": "1"}
            )

    app = create_app(settings, clock=clock.now, parent_invite_limiter=Limiter())
    with TestClient(app, client=LOOPBACK) as raw:
        actor = ApiClient(raw, token=parent.token, user_id=parent.user_id)
        assert actor.request("POST", "/parents/links", json={"code": "A" * 24}).status_code == 429
        other = ApiClient(raw, token=student.token, user_id=student.user_id)
        assert other.request("POST", "/parents/links", json={"code": "A" * 24}).status_code == 403
    assert calls == [parent.user_id]
