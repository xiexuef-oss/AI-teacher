"""Real SQL receipts and Redis leases. Opt-in isolated infrastructure only."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from test_mysql_migrations import mysql_engine  # noqa: F401
from test_mysql_runtime import runtime  # noqa: F401

from tutor_api.errors import ApiError
from tutor_api.idempotency import run_idempotent
from tutor_api.models import IdempotencyReceipt, User
from tutor_api.receipt_coordination import RedisReceiptCoordinator
from tutor_api.receipts import SqlReceiptStore


def context(
    db, actor, store, *, coordinator=None, key="durable-test-key", path="/api/v1/test-write"
):
    state = SimpleNamespace(receipt_store=store, receipt_coordinator=coordinator)
    request = SimpleNamespace(
        headers={"Idempotency-Key": key},
        method="POST",
        url=SimpleNamespace(path=path),
        app=SimpleNamespace(state=state),
    )
    return SimpleNamespace(
        db=db, actor_id=actor, student_id=actor, request=request, now=lambda: datetime.now(UTC)
    )


def add_actor(factory):
    actor = str(uuid4())
    now = datetime.now(UTC)
    with factory() as db:
        db.add(
            User(
                id=actor,
                role="student",
                status="active",
                display_name="0",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    return actor


def increment(db, actor):
    user = db.get(User, actor)
    user.display_name = str(int(user.display_name) + 1)
    return {"counter": user.display_name}


def test_real_sql_unique_receipt_prevents_duplicate_actions(request):
    engine, factory = request.getfixturevalue("runtime")
    actor = add_actor(factory)
    barrier, calls = Barrier(2), []

    class SynchronizedStore(SqlReceiptStore):
        def lookup(self, ctx, key, digest):
            result = super().lookup(ctx, key, digest)
            if not getattr(ctx, "passed", False):
                ctx.passed = True
                barrier.wait(timeout=5)
            return result

    def invoke(_):
        with factory() as db:
            ctx = context(db, actor, SynchronizedStore())

            def action(digest):
                calls.append("action")
                time.sleep(0.05)
                return increment(db, actor)

            return run_idempotent(ctx, {}, 200, action).body

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(invoke, range(2)))
    assert responses[0] == responses[1] and calls == ["action"]
    with factory() as db:
        assert db.get(User, actor).display_name == "1"
        assert db.scalar(select(func.count()).select_from(IdempotencyReceipt)) == 1
    assert not any(name.startswith("proto_") for name in inspect(engine).get_table_names())


def test_real_sql_rollback_failed_commit_and_restart_replay(request):
    _, factory = request.getfixturevalue("runtime")
    actor = add_actor(factory)
    with factory() as db:
        ctx = context(db, actor, SqlReceiptStore())

        def fail(digest):
            increment(db, actor)
            raise ApiError(404, "not_found", "not found")

        with pytest.raises(ApiError):
            run_idempotent(ctx, {}, 200, fail)
        assert db.scalar(select(func.count()).select_from(IdempotencyReceipt)) == 0
        assert db.get(User, actor).display_name == "0"

        def early_commit(digest):
            increment(db, actor)
            db.commit()

        with pytest.raises(RuntimeError, match="must not commit"):
            run_idempotent(ctx, {}, 200, early_commit)
        assert db.get(User, actor).display_name == "0"
        first = run_idempotent(ctx, {}, 200, lambda _: increment(db, actor)).body
    with factory() as db:
        ctx = context(db, actor, SqlReceiptStore())
        second = run_idempotent(
            ctx,
            {},
            200,
            lambda _: pytest.fail("committed receipt must survive coordinator loss/restart"),
        ).body
        assert second == first
        with pytest.raises(ApiError) as error:
            run_idempotent(ctx, {"changed": True}, 200, lambda _: None)
        assert error.value.code == "idempotency_key_conflict"


def test_formal_sql_rejects_prototype_actions_and_does_not_swallow_integrity(request):
    _, factory = request.getfixturevalue("runtime")
    actor = add_actor(factory)
    with factory() as db:
        ctx = context(db, actor, SqlReceiptStore(), path="/api/v1/admin/import-jobs")
        with pytest.raises(RuntimeError, match="prototype"):
            run_idempotent(ctx, {}, 200, lambda _: pytest.fail("prototype action must not run"))
        ctx = context(db, actor, SqlReceiptStore())

        def fatal(digest):
            now = datetime.now(UTC)
            db.add(User(id=actor, role="student", status="active", created_at=now, updated_at=now))
            db.flush()

        with pytest.raises(IntegrityError):
            run_idempotent(ctx, {}, 200, fatal)
        assert db.scalar(select(func.count()).select_from(IdempotencyReceipt)) == 0


@pytest.fixture
def real_coordinator():
    location = os.environ.get("TUTOR_REDIS_RECEIPT_TEST_CONFIG")
    if not location:
        pytest.skip("Explicit isolated Redis credentials required")
    redis = pytest.importorskip("redis")
    config = json.loads(Path(location).read_text(encoding="utf-8-sig"))
    if (
        config.get("host") != "127.0.0.1"
        or config.get("port") != 16379
        or config.get("test_namespace") != "tutor-test:"
    ):
        pytest.fail("Only explicitly authorized isolated Redis is allowed")
    client = redis.Redis(
        host=config["host"],
        port=config["port"],
        password=config["password"],
        db=config["db"],
        decode_responses=True,
        socket_timeout=3,
    )
    namespace = config["test_namespace"] + "receipts-" + uuid4().hex + ":"
    coordinator = RedisReceiptCoordinator(client, namespace=namespace, lease_ms=60)
    try:
        assert client.ping()
        yield coordinator
    finally:
        keys = list(client.scan_iter(match=namespace + "*"))
        if keys:
            client.delete(*keys)
        client.close()


def test_real_redis_token_compare_blocks_stale_owner(real_coordinator):
    coordinator = real_coordinator
    digest = "a" * 64
    first = coordinator.acquire(digest)
    assert first and coordinator.acquire(digest) is None
    assert coordinator.renew(digest, first)
    time.sleep(0.1)
    second = coordinator.acquire(digest)
    assert second and second != first
    assert not coordinator.renew(digest, first)
    assert not coordinator.release(digest, first)
    assert coordinator.client.get(coordinator._key(digest)) == second
    assert coordinator.release(digest, second)


def test_real_redis_expired_lease_still_cannot_duplicate_sql_action(request, real_coordinator):
    _, factory = request.getfixturevalue("runtime")
    actor = add_actor(factory)
    entered, finish, second_acquired = Event(), Event(), Event()
    calls = []
    original = real_coordinator.acquire
    acquisitions = []

    def acquire(digest):
        token = original(digest)
        acquisitions.append(token)
        if len(acquisitions) == 2 and token:
            second_acquired.set()
        return token

    real_coordinator.acquire = acquire

    def invoke(_):
        with factory() as db:
            ctx = context(db, actor, SqlReceiptStore(), coordinator=real_coordinator)

            def action(digest):
                calls.append("action")
                entered.set()
                assert finish.wait(5)
                return increment(db, actor)

            return run_idempotent(ctx, {}, 200, action).body

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, 0)
        try:
            assert entered.wait(3)
            time.sleep(0.1)
            second = pool.submit(invoke, 1)
            assert second_acquired.wait(3)
        finally:
            finish.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert calls == ["action"]


def test_real_upgrade_005_to_006_removes_only_actor_fk(request):
    from migration_runner import apply_migrations

    engine = request.getfixturevalue("mysql_engine")
    before = sorted(
        path
        for path in Path("migrations").glob("*.sql")
        if path.name < "006_receipt_actor_lock_independence.sql"
    )
    path = Path("migrations/006_receipt_actor_lock_independence.sql")
    apply_migrations(engine, before)
    assert inspect(engine).get_foreign_keys("idempotency_receipts")
    assert apply_migrations(engine, [*before, path]) == [path.name]
    assert inspect(engine).get_foreign_keys("idempotency_receipts") == []
    indexes = inspect(engine).get_unique_constraints("idempotency_receipts")
    assert any(item["column_names"] == ["actor_id", "key_digest"] for item in indexes)


def test_real_savepoint_release_is_allowed_but_session_commit_inside_is_not(request):
    _, factory = request.getfixturevalue("runtime")
    actor = add_actor(factory)
    with factory() as db:
        ctx = context(db, actor, SqlReceiptStore(), key="savepoint-valid-key")

        def allowed(digest):
            with db.begin_nested():
                result = increment(db, actor)
            return result

        assert run_idempotent(ctx, {}, 200, allowed).status_code == 200
    with factory() as db:
        ctx = context(db, actor, SqlReceiptStore(), key="savepoint-early-commit-key")

        def forbidden(digest):
            with db.begin_nested():
                increment(db, actor)
                db.commit()

        with pytest.raises(RuntimeError, match="must not commit"):
            run_idempotent(ctx, {}, 200, forbidden)
        assert db.get(User, actor).display_name == "1"
        assert db.scalar(select(func.count()).select_from(IdempotencyReceipt)) == 1
