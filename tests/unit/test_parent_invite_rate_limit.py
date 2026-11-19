from types import SimpleNamespace

import pytest

from tutor_api.errors import ApiError
from tutor_api.services.parent_invite_rate_limit import (
    InMemoryInviteRedeemLimiter,
    RedisInviteRedeemLimiter,
)


def settings(mode="fixed", actor=2, global_limit=10):
    return SimpleNamespace(
        parent_invite_redeem_limit=actor,
        parent_invite_redeem_global_limit=global_limit,
        parent_invite_redeem_window_seconds=1,
        parent_invite_redeem_window_mode=mode,
    )


@pytest.mark.parametrize("mode", ["fixed", "sliding"])
def test_memory_window_semantics_and_unknown_mode_rejection(clock, mode):
    limiter = InMemoryInviteRedeemLimiter()
    config = settings(mode)
    limiter.check("parent", config, clock.now())
    clock.advance(seconds=0.75)
    limiter.check("parent", config, clock.now())
    clock.advance(seconds=0.35)
    limiter.check("parent", config, clock.now())
    if mode == "fixed":
        limiter.check("parent", config, clock.now())
    else:
        with pytest.raises(ApiError):
            limiter.check("parent", config, clock.now())


def test_redis_failure_is_failclosed_and_redacted(clock):
    class Broken:
        def eval(self, *args):
            raise RuntimeError("private redis password or URI")

    limiter = RedisInviteRedeemLimiter(Broken(), namespace="fixture:")
    with pytest.raises(ApiError) as error:
        limiter.check("private-parent", settings(), clock.now())
    assert error.value.status_code == 429 and error.value.code == "invite_rate_limited"
    assert "private" not in str(error.value)


@pytest.mark.parametrize("change", ["mode", "window", "limit"])
def test_memory_configuration_change_does_not_reset_existing_window(clock, change):
    limiter = InMemoryInviteRedeemLimiter()
    old = settings()
    limiter.check("parent", old, clock.now())
    new = settings()
    if change == "mode":
        new.parent_invite_redeem_window_mode = "sliding"
    elif change == "window":
        new.parent_invite_redeem_window_seconds = 2
    else:
        new.parent_invite_redeem_limit = 3
    with pytest.raises(ApiError):
        limiter.check("parent", new, clock.now())
    clock.advance(seconds=1)
    limiter.check("parent", new, clock.now())
