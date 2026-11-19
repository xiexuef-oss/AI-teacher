"""Configurable invite redemption windows; Redis failures never fall back to RAM."""

import hashlib
from collections import deque
from threading import Lock
from uuid import uuid4

from tutor_api.errors import ApiError


def _denied():
    return ApiError(429, "invite_rate_limited", "兑换尝试过于频繁，请稍后重试")


def _configuration(settings):
    mode = settings.parent_invite_redeem_window_mode
    window = settings.parent_invite_redeem_window_seconds
    limits = [settings.parent_invite_redeem_limit, settings.parent_invite_redeem_global_limit]
    if mode not in {"fixed", "sliding"} or type(window) is not int or not 1 <= window <= 3600:
        raise _denied()
    if any(type(limit) is not int or limit < 1 for limit in limits):
        raise _denied()
    return mode, window, limits


def _actor(actor_id):
    return hashlib.sha256(actor_id.encode()).hexdigest()


class InMemoryInviteRedeemLimiter:
    def __init__(self):
        self._lock = Lock()
        self._buckets = {}

    def check(self, actor_id, settings, now):
        mode, window, limits = _configuration(settings)
        with self._lock:
            for key, bucket in list(self._buckets.items()):
                old_mode, old_window, _, start, entries = bucket
                if old_mode == "sliding":
                    while entries and (now - entries[0]).total_seconds() >= old_window:
                        entries.popleft()
                if (
                    old_mode == "fixed" and (now - start).total_seconds() >= old_window
                ) or not entries:
                    del self._buckets[key]
            keys = [("actor", _actor(actor_id)), ("global", "")]
            for key, limit in zip(keys, limits, strict=True):
                current = self._buckets.get(key)
                if current is not None and current[:3] != (mode, window, limit):
                    raise _denied()
            if any(
                key in self._buckets and len(self._buckets[key][4]) >= limit
                for key, limit in zip(keys, limits, strict=True)
            ):
                raise _denied()
            for key, limit in zip(keys, limits, strict=True):
                bucket = self._buckets.setdefault(key, (mode, window, limit, now, deque()))
                bucket[4].append(now)


_LIMIT = """
local mode=ARGV[1]
local window=tonumber(ARGV[2])
local stamp=redis.call('TIME')
local now=tonumber(stamp[1])*1000+math.floor(tonumber(stamp[2])/1000)
for i=1,2 do
  local kind=redis.call('TYPE',KEYS[i]).ok
  if kind ~= 'none' and kind ~= 'zset' then return 0 end
  local marker='meta:'..mode..':'..ARGV[2]..':'..ARGV[i+2]
  if kind == 'zset' then
    local first=redis.call('ZRANGE',KEYS[i],0,0)
    if first[1] ~= marker then return 0 end
  end
end
for i=1,2 do
  if mode == 'sliding' then redis.call('ZREMRANGEBYSCORE',KEYS[i],0,now-window) end
  local count=redis.call('ZCARD',KEYS[i])
  if count > 0 and count-1 >= tonumber(ARGV[i+2]) then return 0 end
end
for i=1,2 do
  local fresh=redis.call('EXISTS',KEYS[i]) == 0
  redis.call('ZADD',KEYS[i],-1,'meta:'..mode..':'..ARGV[2]..':'..ARGV[i+2])
  redis.call('ZADD',KEYS[i],now,ARGV[5])
  if fresh or mode == 'sliding' then redis.call('PEXPIRE',KEYS[i],window) end
end
return 1
"""


class RedisInviteRedeemLimiter:
    def __init__(self, client, *, namespace):
        if not namespace:
            raise ValueError("Explicit isolated Redis namespace required")
        self.client, self.namespace = client, namespace

    def check(self, actor_id, settings, now):
        mode, window, limits = _configuration(settings)
        # Shared hash tag supports a single Redis Cluster slot if configured later.
        prefix = self.namespace + "{parent-invite-limits}:"
        keys = [prefix + "actor:" + _actor(actor_id), prefix + "global"]
        try:
            result = self.client.eval(_LIMIT, 2, *keys, mode, window * 1000, *limits, uuid4().hex)
        except Exception:
            raise _denied() from None
        if result != 1:
            raise _denied()
