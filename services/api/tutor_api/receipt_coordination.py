"""Redis holds expiring coordination tokens only, never authoritative receipts."""

import logging
from contextlib import contextmanager
from uuid import uuid4

from tutor_api.errors import conflict

logger = logging.getLogger(__name__)
_RENEW = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('PEXPIRE',KEYS[1],ARGV[2]) else return 0 end"
_RELEASE = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) else return 0 end"


class RedisReceiptCoordinator:
    def __init__(self, client, *, namespace, lease_ms=30000):
        if not namespace or type(lease_ms) is not int or lease_ms < 1:
            raise ValueError("Explicit Redis namespace and positive lease required")
        self.client, self.namespace, self.lease_ms = client, namespace, lease_ms

    def _key(self, digest):
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Receipt key must be a SHA256 digest")
        return self.namespace + "receipt-lease:" + digest

    def acquire(self, digest):
        token = uuid4().hex
        return (
            token if self.client.set(self._key(digest), token, nx=True, px=self.lease_ms) else None
        )

    def renew(self, digest, token):
        return bool(self.client.eval(_RENEW, 1, self._key(digest), token, self.lease_ms))

    def release(self, digest, token):
        return bool(self.client.eval(_RELEASE, 1, self._key(digest), token))


@contextmanager
def coordinate(ctx, store, digest):
    coordinator = (
        getattr(ctx.request.app.state, "receipt_coordinator", None) if store.durable else None
    )
    token = None
    if coordinator is not None:
        try:
            token = coordinator.acquire(digest)
        except Exception:
            logger.warning("Receipt coordinator unavailable; using authoritative DB transaction")
        else:
            if token is None:
                raise conflict("conflict", "请求处理中，请使用相同幂等键重试")
    try:
        yield
    finally:
        if token is not None:
            try:
                coordinator.release(digest, token)
            except Exception:
                logger.warning("Receipt coordinator release unavailable; lease will expire")
