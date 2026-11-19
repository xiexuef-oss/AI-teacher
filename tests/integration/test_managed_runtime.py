"""Managed dev/staging startup on isolated MySQL and Redis, never production."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from migration_runner import apply_migrations
from sqlalchemy import inspect, select
from starlette.testclient import TestClient
from test_durable_receipts import real_coordinator  # noqa: F401
from test_mysql_migrations import mysql_engine  # noqa: F401
from test_s3_blob_service import storage  # noqa: F401

from ai_gateway import GatewayConfig, build_gateway
from support.api import LOOPBACK, ApiClient
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    FULL_ENV,
    VISUAL_REGISTRY_PATH,
    ScriptedProvider,
    config_dict,
    external_provider,
    hint_ok,
    make_request,
)
from tutor_api.auth import Principal
from tutor_api.blob_store import FilesystemBlobStore
from tutor_api.db import create_session_factory
from tutor_api.main import create_app
from tutor_api.models import IdempotencyReceipt, StudentProfile, User
from tutor_api.receipts import SqlReceiptStore
from tutor_api.services.parent_invite_rate_limit import RedisInviteRedeemLimiter
from tutor_api.settings import Settings


@pytest.mark.parametrize("environment", ["dev", "staging"])
def test_managed_real_runtime_cannot_enable_external_sends_after_startup(dependencies, environment):
    _, _, _, settings, identity, media, limiter = dependencies
    adapter = ScriptedProvider(hint_ok())
    gateway = build_gateway(
        GatewayConfig.model_validate(
            config_dict({"x": external_provider(environments=["dev", "staging"])}, ["x"])
        ),
        env=FULL_ENV,
        environment=environment,
        allow_external_calls=True,
        event_schema_path=EVENT_SCHEMA_PATH,
        visual_registry_path=VISUAL_REGISTRY_PATH,
        adapter_overrides={"x": adapter},
    )
    plan = gateway.prepare_single_attempt(make_request())
    gateway._allow_external_calls = False
    app = create_app(
        settings.model_copy(update={"env": environment, "durable_model_invocations_enabled": True}),
        identity_provider=identity,
        media_store=media,
        parent_invite_limiter=limiter,
        receipt_store=SqlReceiptStore(),
        gateway=gateway,
    )
    with TestClient(app, client=LOOPBACK) as raw:
        assert ApiClient(raw).data("GET", "/health")["environment"] == environment
        gateway._allow_external_calls = True
        gateway.require_durable_external_calls()
        assert gateway.invoke(make_request()).status == "degraded"
        assert gateway.invoke_single_attempt(plan).error_code == "MODEL_UNAVAILABLE"
        with pytest.raises(ValueError, match="No usable candidate"):
            gateway.prepare_single_attempt(make_request())
        assert adapter.calls == []


class FakeKnownUsers:
    def __init__(self, tokens):
        self.tokens = tokens

    def authenticate(self, db, token):
        identifier = self.tokens.get(token)
        user = db.get(User, identifier) if identifier else None
        return Principal(user.id, user.role) if user and user.status == "active" else None


@pytest.fixture
def dependencies(request, tmp_path):
    engine = request.getfixturevalue("mysql_engine")
    redis = request.getfixturevalue("real_coordinator")
    paths = sorted(Path("migrations").glob("*.sql"))
    apply_migrations(engine, paths)
    factory = create_session_factory(engine)
    tokens = {
        name: str(uuid4())
        for name in ("student", "other", "parent", "unlinked", "reviewer", "reviewer2")
    }
    now = datetime.now(UTC)
    with factory() as db:
        for token, identifier in tokens.items():
            role = (
                "parent"
                if token in {"parent", "unlinked"}
                else "reviewer"
                if token.startswith("reviewer")
                else "student"
            )
            db.add(
                User(
                    id=identifier,
                    role=role,
                    status="active",
                    display_name=token,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.flush()
        for token in ("student", "other"):
            db.add(StudentProfile(user_id=tokens[token], created_at=now, updated_at=now))
        db.commit()
    root = tmp_path / "private-existing-media"
    root.mkdir()
    media = FilesystemBlobStore(root, max_bytes=1024 * 1024)
    settings = Settings(env="staging", pseudonym_secret="managed-fixture-stable-secret").model_copy(
        update={"database_url": engine.url}
    )
    limiter = RedisInviteRedeemLimiter(redis.client, namespace=redis.namespace)
    return engine, factory, tokens, settings, FakeKnownUsers(tokens), media, limiter


def build(dependencies):
    _, _, _, settings, identity, media, limiter = dependencies
    return create_app(
        settings,
        identity_provider=identity,
        media_store=media,
        parent_invite_limiter=limiter,
        receipt_store=SqlReceiptStore(),
    )


@pytest.mark.parametrize("environment", ["dev", "staging"])
def test_managed_mysql_redis_s3_startup_lists_without_writes_or_client_ownership(
    dependencies, request, environment, monkeypatch
):
    from datetime import timedelta

    from sqlalchemy import Engine, event

    _, _, tokens, settings, identity, _, limiter = dependencies
    client, bucket, prefix, media = request.getfixturevalue("storage")
    now = datetime.now(UTC)
    media.stage(
        owner=tokens["student"],
        purpose="ocr_source",
        data=b"owned-current-media",
        expires_at=now + timedelta(minutes=1),
        now=now,
    )
    before = {
        item["Key"]: item["ETag"]
        for item in client.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
    }
    limiter.check("s3-readiness-parent", settings, now)
    keys = list(limiter.client.scan_iter(match=limiter.namespace + "*"))
    quota = {key: limiter.client.zcard(key) for key in keys}
    statements, operations = [], []
    listed = client.list_objects_v2

    def capture(connection, cursor, sql, parameters, context, many):
        statements.append(sql.strip().upper())

    def list_objects(**kwargs):
        operations.append(("list", kwargs))
        return listed(**kwargs)

    def forbidden(*args, **kwargs):
        operations.append(("forbidden", kwargs))
        raise RuntimeError("readiness must not write, read object content, clean or close client")

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(client, "list_objects_v2", list_objects)
            for name in ("get_object", "put_object", "delete_object", "close"):
                patch.setattr(client, name, forbidden)
            patch.setattr(media, "cleanup", forbidden)
            app = create_app(
                settings.model_copy(update={"env": environment}),
                identity_provider=identity,
                media_store=media,
                parent_invite_limiter=limiter,
                receipt_store=SqlReceiptStore(),
            )
            for _ in range(2):
                with TestClient(app, client=LOOPBACK) as raw:
                    api = ApiClient(raw, "student", tokens["student"])
                    assert api.data("GET", "/health")["environment"] == environment
                    api.error("GET", "/profile/media-export", expect=501)
                    ApiClient(raw, "parent", tokens["parent"]).error(
                        "GET", "/profile/media-export", expect=403
                    )
            assert app.state.media_store is media
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
    assert operations == [("list", dict(Bucket=bucket, Prefix=prefix, MaxKeys=1))] * 2
    assert statements and all(sql.startswith(("SELECT", "SHOW", "SET")) for sql in statements)
    assert {key: limiter.client.zcard(key) for key in keys} == quota
    assert {
        item["Key"]: item["ETag"]
        for item in client.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
    } == before


@pytest.mark.parametrize("problem", ["unavailable", "foreign_page", "changed_endpoint"])
def test_managed_s3_startup_failure_is_redacted_and_does_not_fall_back(
    dependencies, request, problem, monkeypatch
):
    _, _, _, settings, identity, _, limiter = dependencies
    client, _, _, media = request.getfixturevalue("storage")
    app = create_app(
        settings,
        identity_provider=identity,
        media_store=media,
        parent_invite_limiter=limiter,
        receipt_store=SqlReceiptStore(),
    )
    engine = app.state.session_factory.kw["bind"]
    disposed, calls = [], []
    dispose = engine.dispose

    def record_disposal(*args, **kwargs):
        disposed.append(True)
        return dispose(*args, **kwargs)

    def fail_listing(**kwargs):
        calls.append(kwargs)
        if problem == "foreign_page":
            return {"Contents": [{"Key": "outside/private-key"}], "IsTruncated": False}
        raise RuntimeError("private object storage details")

    with monkeypatch.context() as patch:
        patch.setattr(engine, "dispose", record_disposal)
        patch.setattr(client, "list_objects_v2", fail_listing)
        if problem == "changed_endpoint":
            patch.setattr(client.meta, "_endpoint_url", "https://example.com:443")
        with (
            pytest.raises(ValueError, match="依赖校验失败") as error,
            TestClient(app, client=LOOPBACK),
        ):
            raise AssertionError("unhealthy S3 must not start")
        assert "private" not in str(error.value)
        assert app.state.media_store is media
        assert disposed == [True]
        assert len(calls) == (0 if problem == "changed_endpoint" else 1)


@pytest.mark.parametrize("environment", ["dev", "staging"])
def test_managed_export_marks_local_scan_scope_unprovided_without_querying_proto(
    dependencies, environment
):
    from sqlalchemy import event

    _, _, tokens, settings, identity, media, limiter = dependencies
    app = create_app(
        settings.model_copy(update={"env": environment}),
        identity_provider=identity,
        media_store=media,
        parent_invite_limiter=limiter,
        receipt_store=SqlReceiptStore(),
    )
    engine = app.state.session_factory.kw["bind"]
    statements = []

    def capture(connection, cursor, sql, parameters, context, many):
        statements.append(sql)

    with TestClient(app, client=LOOPBACK) as raw:
        event.listen(engine, "before_cursor_execute", capture)
        try:
            exported = ApiClient(raw, "student", tokens["student"]).data(
                "GET", "/profile/learning-export"
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert "stored_scan_records" in exported
        assert exported["stored_scan_records"] is None
        assert statements
        assert not any("proto_scan_records" in sql for sql in statements)


def test_managed_model_usage_export_filters_real_mysql_budget_buckets(dependencies):
    from tutor_api.gateway_io import pseudonym
    from tutor_api.models import ModelBudgetUsage

    _, factory, tokens, settings, _, _, _ = dependencies
    now = datetime.now(UTC)
    own = pseudonym(settings.pseudonym_secret, tokens["student"])
    other = pseudonym(settings.pseudonym_secret, tokens["other"])
    with factory() as db:
        for scope, key, count in (
            ("student", own, 3),
            ("platform", own, 999),
            ("student", other, 888),
        ):
            db.add(
                ModelBudgetUsage(
                    id=str(uuid4()),
                    scope=scope,
                    scope_key=key,
                    usage_date=now.date(),
                    request_count=count,
                    estimated_cost_micros=count,
                    updated_at=now,
                )
            )
        db.commit()
    app = build(dependencies)
    with TestClient(app, client=LOOPBACK) as raw:
        usage = ApiClient(raw, "student", tokens["student"]).data(
            "GET", "/profile/learning-export"
        )["model_usage"]
        assert usage["calls"] == []
        assert [row["request_count"] for row in usage["budget_days"]] == [3]
        assert usage["costs_are_billing"] is False
    with factory() as db:
        assert sorted(db.scalars(select(ModelBudgetUsage.request_count))) == [3, 888, 999]


@pytest.mark.parametrize("environment", ["dev", "staging"])
def test_managed_media_export_is_explicitly_unavailable_without_touching_store(
    dependencies, environment, monkeypatch
):
    _, _, tokens, settings, identity, media, limiter = dependencies

    def forbidden(**kwargs):
        pytest.fail("Managed export must not query local media")

    monkeypatch.setattr(media, "list_owned", forbidden)
    app = create_app(
        settings.model_copy(update={"env": environment}),
        identity_provider=identity,
        media_store=media,
        parent_invite_limiter=limiter,
        receipt_store=SqlReceiptStore(),
    )
    with TestClient(app, client=LOOPBACK) as raw:
        response = ApiClient(raw, "student", tokens["student"]).get("/profile/media-export")
        assert response.status_code == 501 and "data" not in response.json()
        assert response.headers["cache-control"] == "no-store"
        ApiClient(raw, "parent", tokens["parent"]).error("GET", "/profile/media-export", expect=403)


@pytest.mark.parametrize("environment", ["dev", "staging"])
def test_managed_real_startup_role_owner_and_durable_invite_replay(dependencies, environment):
    engine, factory, tokens, _, _, _, _ = dependencies
    selected = list(dependencies)
    selected[3] = selected[3].model_copy(update={"env": environment})
    app = build(selected)
    with TestClient(app, client=LOOPBACK) as raw:
        assert ApiClient(raw).data("GET", "/health")["environment"] == environment
        student = ApiClient(raw, "student", tokens["student"])
        parent = ApiClient(raw, "parent", tokens["parent"])
        outsider = ApiClient(raw, "unlinked", tokens["unlinked"])
        assert student.data("GET", "/profile")["user_id"] == tokens["student"]
        assert parent.error("GET", "/profile", expect=403)["code"] == "forbidden"
        assert (
            ApiClient(raw, "unknown").error("GET", "/profile", expect=401)["code"]
            == "unauthenticated"
        )
        first = student.data(
            "POST",
            "/me/parent-invites",
            json={"expected_parent_invite_revision": 0},
            expect=201,
            key="managed-invite-key",
        )
        assert (
            student.data(
                "POST",
                "/me/parent-invites",
                json={"expected_parent_invite_revision": 0},
                expect=201,
                key="managed-invite-key",
            )
            == first
        )
        parent.data("POST", "/parents/links", expect=201, json={"code": first["code"]})
        parent.data("GET", f"/parents/students/{tokens['student']}/weekly")
        outsider.error("GET", f"/parents/students/{tokens['student']}/weekly", expect=404)
        reviewer = ApiClient(raw, "reviewer", tokens["reviewer"])
        reviewer.error("GET", "/admin/import-jobs", expect=501)
        student.error("GET", "/admin/import-jobs", expect=403)
        student.error("POST", "/dev/local-identities", expect=404, key=False)
        student.error(
            "POST",
            "/tutor/sessions/00000000-0000-0000-0000-000000000000/next",
            expect=404,
            json={"action": "request_hint"},
        )
    assert not any(name.startswith("proto_") for name in inspect(engine).get_table_names())
    with factory() as db:
        records = db.scalars(select(IdempotencyReceipt)).all()
        assert records and all(record.state == "complete" for record in records)


def test_managed_startup_is_read_only_and_ping_does_not_charge(dependencies, monkeypatch):
    from sqlalchemy import Engine, event

    import tutor_api.main as main

    engine, _, _, settings, _, media, limiter = dependencies
    limiter.check("readiness-probe-parent", settings, datetime.now(UTC))
    keys = list(limiter.client.scan_iter(match=limiter.namespace + "*"))
    quota = {key: limiter.client.zcard(key) for key in keys}
    files = sorted(path.name for path in media.root.iterdir())

    def forbidden(*args, **kwargs):
        pytest.fail(
            "managed startup must not bootstrap, scrub, clean, seed or start prototype worker"
        )

    for name in ("seed_if_empty", "scrub_legacy_responses", "cleanup_media", "ImportWorker"):
        monkeypatch.setattr(main, name, forbidden)
    monkeypatch.setattr(main.Base.metadata, "create_all", forbidden)
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert statement.lstrip().split()[0].upper() not in {
            "CREATE",
            "ALTER",
            "DROP",
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REPLACE",
        }

    event.listen(Engine, "before_cursor_execute", observe)
    try:
        with TestClient(build(dependencies), client=LOOPBACK) as raw:
            assert raw.get("/api/v1/health").status_code == 200
            assert {key: limiter.client.zcard(key) for key in keys} == quota
    finally:
        event.remove(Engine, "before_cursor_execute", observe)
    assert statements and files == sorted(path.name for path in media.root.iterdir())
    assert not any(name.startswith("proto_") for name in inspect(engine).get_table_names())


@pytest.mark.parametrize(
    "problem", ["running", "missing_record", "checksum", "proto_table", "missing_column"]
)
def test_managed_incomplete_or_tampered_schema_refused_and_engine_disposed(
    dependencies, monkeypatch, problem
):
    from sqlalchemy import text

    import tutor_api.main as main
    from tutor_api.db import make_engine

    engine = dependencies[0]
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        if problem == "running":
            connection.execute(
                text(
                    "UPDATE schema_migration_ledger SET state='running' WHERE name='006_receipt_actor_lock_independence.sql'"
                )
            )
        elif problem == "missing_record":
            connection.execute(
                text(
                    "DELETE FROM schema_migration_ledger WHERE name='006_receipt_actor_lock_independence.sql'"
                )
            )
        elif problem == "checksum":
            connection.execute(
                text(
                    "UPDATE schema_migration_ledger SET sha256=:digest WHERE name='006_receipt_actor_lock_independence.sql'"
                ),
                {"digest": "0" * 64},
            )
        elif problem == "missing_column":
            connection.exec_driver_sql("ALTER TABLE users DROP COLUMN display_name")
        else:
            connection.exec_driver_sql("CREATE TABLE proto_unexpected_fixture (id INT)")
    disposed = []

    def tracked(url, *, settings):
        assert settings is dependencies[3]
        value = make_engine(url, settings=settings)
        original = value.dispose

        def dispose(*args, **kwargs):
            disposed.append(True)
            original(*args, **kwargs)

        value.dispose = dispose
        return value

    monkeypatch.setattr(main, "make_engine", tracked)
    with (
        pytest.raises(ValueError, match="依赖校验失败"),
        TestClient(build(dependencies), client=LOOPBACK),
    ):
        pytest.fail("dirty schema must never start")
    assert disposed == [True]


def test_managed_failed_redemption_rolls_back_receipt_and_business(dependencies):
    _, factory, tokens, _, _, _, _ = dependencies
    with TestClient(build(dependencies), client=LOOPBACK) as raw:
        parent = ApiClient(raw, "parent", tokens["parent"])
        for _ in range(2):
            parent.error(
                "POST",
                "/parents/links",
                expect=404,
                json={"code": "BAD"},
                key="managed-invalid-code",
            )
    with factory() as db:
        assert db.scalars(select(IdempotencyReceipt)).all() == []


def test_empty_mysql_is_not_bootstrapped(request, tmp_path):
    engine = request.getfixturevalue("mysql_engine")
    fixture = request.getfixturevalue("real_coordinator")
    root = tmp_path / "precreated"
    root.mkdir()
    settings = Settings(env="dev", pseudonym_secret="managed-dev-stable-secret").model_copy(
        update={"database_url": engine.url}
    )
    app = create_app(
        settings,
        identity_provider=FakeKnownUsers({}),
        receipt_store=SqlReceiptStore(),
        media_store=FilesystemBlobStore(root, max_bytes=1024),
        parent_invite_limiter=RedisInviteRedeemLimiter(fixture.client, namespace=fixture.namespace),
    )
    with pytest.raises(ValueError, match="依赖校验失败"), TestClient(app, client=LOOPBACK):
        pytest.fail("empty schema must not start")
    assert inspect(engine).get_table_names() == []


@pytest.mark.parametrize("problem", ["media_root_missing", "redis_unavailable"])
def test_managed_health_failure_never_recreates_or_falls_back(dependencies, problem):
    _, _, _, _, _, media, limiter = dependencies
    if problem == "media_root_missing":
        media.root.rmdir()
    else:

        class Unavailable:
            def ping(self):
                raise RuntimeError("protected backend details")

        limiter.client = Unavailable()
    with (
        pytest.raises(ValueError, match="依赖校验失败") as error,
        TestClient(build(dependencies), client=LOOPBACK),
    ):
        pytest.fail("unhealthy explicit dependency must not fall back")
    assert "protected backend details" not in str(error.value)
    if problem == "media_root_missing":
        assert not media.root.exists()


def test_managed_text_import_independent_batch_review_and_student_session(dependencies):
    import json

    from tutor_api.models import KnowledgeNode

    _, factory, tokens, _, _, _, _ = dependencies
    payload = json.loads(
        Path("apps/admin_web/public/examples/question-import.json").read_text(encoding="utf-8")
    )
    with factory() as db:
        for code in payload["question"]["knowledge"]:
            db.add(
                KnowledgeNode(
                    id=str(uuid4()),
                    subject="math",
                    code=code,
                    title="Self authored fixture",
                    created_at=datetime.now(UTC),
                )
            )
        db.commit()
    with TestClient(build(dependencies), client=LOOPBACK) as raw:
        author = ApiClient(raw, "reviewer", tokens["reviewer"])
        reviewer = ApiClient(raw, "reviewer2", tokens["reviewer2"])
        student = ApiClient(raw, "student", tokens["student"])
        other = ApiClient(raw, "other", tokens["other"])
        created = author.data(
            "POST", "/admin/question-imports", expect=201, json=payload, key="managed-text-import"
        )
        assert (
            author.data(
                "POST",
                "/admin/question-imports",
                expect=201,
                json=payload,
                key="managed-text-import",
            )
            == created
        )
        identifier = created["id"]
        body = {
            "items": [
                {
                    "expected_review_revision": 1,
                    "question_id": identifier,
                    "expected_version": 1,
                    "decision": "approve",
                    "confirmed": True,
                }
            ]
        }
        denied = author.data("POST", "/admin/question-reviews/batch", json=body)
        assert denied["items"][0]["error"]["code"] == "self_review_forbidden"
        approved = reviewer.data(
            "POST", "/admin/question-reviews/batch", json=body, key="managed-batch-review"
        )
        assert approved["items"][0]["status"] == "succeeded"
        assert (
            reviewer.data(
                "POST", "/admin/question-reviews/batch", json=body, key="managed-batch-review"
            )
            == approved
        )
        reviewer.data(
            "POST",
            f"/admin/questions/{identifier}/review",
            json={
                "expected_review_revision": (1) + 1,
                "expected_version": 1,
                "decision": "publish",
            },
        )
        student.data("GET", f"/questions/{identifier}")
        session = student.data(
            "POST",
            "/sessions",
            expect=201,
            json={"question_id": identifier, "origin": "practice"},
            key="managed-session-key",
        )
        other.error("GET", f"/sessions/{session['id']}", expect=404)
        before_events = student.data("GET", f"/sessions/{session['id']}/events")
        student.data(
            "POST",
            f"/tutor/sessions/{session['id']}/next",
            json={"action": "request_hint"},
        )
        ApiClient(raw, "parent", tokens["parent"]).error(
            "POST",
            f"/tutor/sessions/{session['id']}/next",
            expect=403,
            json={"action": "request_hint"},
        )
        after_events = student.data("GET", f"/sessions/{session['id']}/events")
        assert after_events["last_seq"] == before_events["last_seq"] + 1

        attempt = student.data("POST", "/attempts", expect=201, json={"session_id": session["id"]})
        student.data(
            "PUT",
            f"/attempts/{attempt['id']}/draft",
            json={"base_revision": 0, "answer": {"selected_options": ["B"]}},
        )
        result = student.data(
            "POST",
            f"/attempts/{attempt['id']}/submit",
            json={"answer": {"selected_options": ["B"]}},
            key="managed-submit-key",
        )
        assert result["evaluation"]["is_correct"] is True
        other.error("GET", f"/attempts/{attempt['id']}", expect=404)
