import json

import pytest
from sqlalchemy import select

from support.parents import invite
from tutor_api.proto_models import IdempotencyRecord


def test_invite_plaintext_never_persists_and_expired_replay_is_rejected(onboarded, app, clock):
    key = "security-invite-key"
    created = invite(onboarded, json={"expected_parent_invite_revision": 0}, key=key)
    with app.state.session_factory() as db:
        rows = db.scalars(select(IdempotencyRecord)).all()
        assert created["code"] not in json.dumps([row.response_json for row in rows])
    assert invite(onboarded, json={"expected_parent_invite_revision": 0}, key=key) == created
    clock.advance(hours=24)
    error = onboarded.error(
        "POST",
        "/me/parent-invites",
        json={"expected_parent_invite_revision": 0},
        expect=409,
        key=key,
    )
    assert error["code"] == "invite_response_expired"


def test_rate_limit_is_actor_scoped_and_window_resets(parent, app, clock):
    app.state.settings.parent_invite_redeem_limit = 2
    for _ in range(2):
        assert (
            parent.error("POST", "/parents/links", expect=404, json={"code": "BAD"})["code"]
            == "invite_invalid"
        )
    assert (
        parent.error("POST", "/parents/links", expect=429, json={"code": "DIFFERENT"})["code"]
        == "invite_rate_limited"
    )
    clock.advance(seconds=app.state.settings.parent_invite_redeem_window_seconds)
    assert (
        parent.error("POST", "/parents/links", expect=404, json={"code": "BAD"})["code"]
        == "invite_invalid"
    )


def test_concurrent_parents_cannot_redeem_same_invite(onboarded, parent, client, app, clock):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from support.parents import new_identity
    from tutor_api.errors import ApiError
    from tutor_api.models import ParentInvite
    from tutor_api.services.parent_service import redeem_invite

    other = new_identity(client, "parent")
    created = invite(onboarded)
    barrier = Barrier(2)

    def redeem(parent_id):
        with app.state.session_factory() as db:
            original = db.scalar
            first_read = True

            def scalar(statement, *args, **kwargs):
                nonlocal first_read
                result = original(statement, *args, **kwargs)
                if first_read and statement.column_descriptions[0].get("entity") is ParentInvite:
                    first_read = False
                    barrier.wait(timeout=3)
                return result

            db.scalar = scalar
            try:
                redeem_invite(db, parent_id, created["code"], now=clock.now(), request_id="race")
                db.commit()
                return 201
            except ApiError as error:
                db.rollback()
                assert error.code == "invite_invalid"
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(redeem, [parent.user_id, other.user_id]))
    assert sorted(statuses) == [201, 404]


@pytest.mark.parametrize("state", ["redeemed", "replaced", "secret_changed"])
def test_invalidated_invite_response_never_reconstructs_a_code(onboarded, parent, app, state):
    from support.parents import link

    key = "invite-state-key"
    created = invite(onboarded, json={"expected_parent_invite_revision": 0}, key=key)
    if state == "redeemed":
        link(parent, created["code"])
    elif state == "replaced":
        invite(onboarded)
    else:
        app.state.pseudonym_secret = "different-test-secret"
    assert (
        onboarded.error(
            "POST",
            "/me/parent-invites",
            json={"expected_parent_invite_revision": 0},
            expect=409,
            key=key,
        )["code"]
        == "invite_response_expired"
    )


def test_fixed_secret_invite_replay_survives_actual_restart(onboarded, app, settings, clock):
    from starlette.testclient import TestClient

    from support.api import LOOPBACK, ApiClient
    from tutor_api.main import create_app

    settings.pseudonym_secret = "stable-test-secret-not-production"
    app.state.pseudonym_secret = settings.pseudonym_secret
    created = invite(
        onboarded, json={"expected_parent_invite_revision": 0}, key="restart-invite-key"
    )
    # Simulate a pre-SEC301 prototype record with a plaintext response.
    with app.state.session_factory() as db:
        row = db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.idempotency_key == "restart-invite-key"
            )
        )
        row.response_json = {"data": created}
        db.commit()
    with TestClient(create_app(settings, clock=clock.now), client=LOOPBACK) as raw:
        with app.state.session_factory() as db:
            rows = db.scalars(select(IdempotencyRecord)).all()
            assert created["code"] not in json.dumps([row.response_json for row in rows])
        restored = ApiClient(raw, onboarded.token, onboarded.user_id)
        assert (
            invite(restored, json={"expected_parent_invite_revision": 0}, key="restart-invite-key")
            == created
        )
    settings.pseudonym_secret = None
    with TestClient(create_app(settings, clock=clock.now), client=LOOPBACK) as raw:
        restored = ApiClient(raw, onboarded.token, onboarded.user_id)
        assert (
            restored.error(
                "POST",
                "/me/parent-invites",
                json={"expected_parent_invite_revision": 0},
                expect=409,
                key="restart-invite-key",
            )["code"]
            == "invite_response_expired"
        )


def test_successful_redeem_replay_does_not_consume_rate_limit(onboarded, parent, app):
    from support.parents import link

    app.state.settings.parent_invite_redeem_limit = 1
    created = invite(onboarded)
    first = link(parent, created["code"], key="redeem-replay-key")
    assert link(parent, created["code"], key="redeem-replay-key") == first
    assert (
        parent.error("POST", "/parents/links", expect=429, json={"code": "BAD"})["code"]
        == "invite_rate_limited"
    )


def test_global_limit_and_role_check_precede_code_lookup(onboarded, parent, client, app):
    from support.parents import new_identity

    app.state.settings.parent_invite_redeem_global_limit = 1
    parent.error("POST", "/parents/links", expect=404, json={"code": "BAD"})
    other = new_identity(client, "parent")
    created = invite(onboarded)
    assert (
        other.error("POST", "/parents/links", expect=429, json={"code": created["code"]})["code"]
        == "invite_rate_limited"
    )
    assert (
        onboarded.error("POST", "/parents/links", expect=403, json={"code": created["code"]})[
            "code"
        ]
        == "forbidden"
    )
    assert created["code"] not in repr(app.state.parent_invite_limiter._buckets)
