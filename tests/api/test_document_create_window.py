from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select, update

from support.contract import validate_response
from tutor_api.proto_models import DocumentImportJob, IdempotencyRecord
from tutor_api.receipts import SqlReceiptStore
from tutor_api.services.document_import_service import cleanup_expired


def body(deadline):
    return {
        "creation_deadline": deadline,
        "title": "self-authored window probe",
        "defaults": {
            "subject": "math",
            "answer_mode": "written",
            "source": {
                "source_type": "self_authored",
                "source_category": "foundation",
                "source_name": "self-authored test",
                "source_year": None,
                "source_license": "internal-engineering-sample",
                "source_url": None,
            },
        },
    }


def post(client, reviewer, payload, key="window-original-key"):
    response = client.post(
        "/api/v1/admin/import-jobs",
        json=payload,
        headers={"Authorization": "Bearer " + reviewer.token, "Idempotency-Key": key},
    )
    validate_response("POST", "/api/v1/admin/import-jobs", response.status_code, response.json())
    return response


def test_full_response_loss_cleanup_never_recreates(client, reviewer, clock, db):
    deadline = clock.now() + timedelta(minutes=5)
    payload = body(deadline.isoformat())
    first = post(client, reviewer, payload)
    assert first.status_code == 201
    original = db.scalars(select(DocumentImportJob)).one().id
    clock.advance(minutes=6)
    assert cleanup_expired(db, clock.now()) == 1
    db.commit()
    again = post(client, reviewer, payload)
    assert again.status_code == 410
    assert again.json()["error"]["code"] == "import_creation_window_expired"
    assert db.scalar(select(func.count()).select_from(DocumentImportJob)) == 0
    assert (
        db.scalar(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(IdempotencyRecord.idempotency_key == "window-original-key")
        )
        == 0
    )
    assert db.get(DocumentImportJob, original) is None


def test_existing_success_receipt_replays_after_deadline(client, reviewer, clock):
    payload = body((clock.now() + timedelta(minutes=5)).isoformat())
    first = post(client, reviewer, payload)
    assert first.status_code == 201
    clock.advance(minutes=6)
    again = post(client, reviewer, payload)
    assert (
        again.status_code == 201
        and again.json() == first.json()
        and again.headers["Idempotency-Replayed"] == "true"
    )


@pytest.mark.parametrize(
    "value",
    [None, True, 1794297900, "2026-11-10", "2026-11-10T08:05:00", "2026-11-10 08:05:00Z", "bad"],
)
def test_strict_aware_rfc3339(client, reviewer, value):
    assert post(client, reviewer, body(value)).status_code == 422


def test_missing_deadline_is_not_legacy_recreated(client, reviewer):
    payload = body(None)
    del payload["creation_deadline"]
    assert post(client, reviewer, payload).status_code == 422


def test_options_one_clock_and_fixed_millisecond_window(reviewer, clock, settings):
    result = reviewer.data("GET", "/admin/import-options")
    now = datetime.fromisoformat(result["server_time"])
    deadline = datetime.fromisoformat(result["creation_deadline"])
    assert now == clock.now().replace(microsecond=clock.now().microsecond // 1000 * 1000)
    assert deadline - now == timedelta(minutes=settings.import_temporary_ttl_minutes)
    assert now.microsecond % 1000 == deadline.microsecond % 1000 == 0


def test_fixed_expiry_timezone_canonical_replay_and_body_conflict(client, reviewer, clock):
    deadline = clock.now() + timedelta(minutes=5, microseconds=123456)
    payload = body(deadline.isoformat())
    first = post(client, reviewer, payload)
    assert first.status_code == 201
    assert datetime.fromisoformat(first.json()["data"]["expires_at"]) == deadline.replace(
        microsecond=123000
    )
    equivalent = body(deadline.astimezone(timezone(timedelta(hours=8))).isoformat())
    clock.advance(minutes=6)
    assert post(client, reviewer, equivalent).json() == first.json()
    changed = {**payload, "title": "another self-authored title"}
    assert post(client, reviewer, changed).status_code == 409


def test_expired_and_too_far_create_no_job(client, reviewer, clock, settings, db):
    assert post(client, reviewer, body(clock.now().isoformat())).status_code == 410
    assert (
        post(
            client,
            reviewer,
            body(
                (
                    clock.now()
                    + timedelta(minutes=settings.import_temporary_ttl_minutes, seconds=1)
                ).isoformat()
            ),
            "far-window-key",
        ).status_code
        == 422
    )
    assert db.scalar(select(func.count()).select_from(DocumentImportJob)) == 0


def test_waiting_for_sqlite_writer_checks_fresh_clock(client, reviewer, clock, app):
    reached = Event()
    engine = app.state.session_factory.kw["bind"]

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE proto_document_import_jobs"):
            reached.set()

    with app.state.session_factory() as blocker:
        blocker.execute(
            update(DocumentImportJob)
            .where(DocumentImportJob.id == "blocker")
            .values(revision=DocumentImportJob.revision)
        )
        event.listen(engine, "before_cursor_execute", before_execute)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    post, client, reviewer, body((clock.now() + timedelta(seconds=1)).isoformat())
                )
                try:
                    assert reached.wait(5), "create did not attempt its actual write lock"
                    assert not future.done()
                    clock.advance(seconds=2)
                finally:
                    blocker.commit()
                assert future.result(timeout=10).status_code == 410
        finally:
            event.remove(engine, "before_cursor_execute", before_execute)


def test_competing_same_key_has_one_job(client, reviewer, clock, db):
    payload = body((clock.now() + timedelta(minutes=5)).isoformat())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(client, reviewer, payload), range(2)))
    assert [r.status_code for r in results] == [201, 201]
    assert results[0].json() == results[1].json()
    assert db.scalar(select(func.count()).select_from(DocumentImportJob)) == 1


def test_configuration_changes_do_not_extend_or_discard_success_receipt(
    client, reviewer, clock, custom_app
):
    options = reviewer.data("GET", "/admin/import-options")
    original = body(options["creation_deadline"])
    first = post(client, reviewer, original)
    assert first.status_code == 201
    short = custom_app(import_temporary_ttl_minutes=5)
    # Existing success is authoritative even when its original window is now
    # outside the shorter current configuration.
    replay = post(short, reviewer, original)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert post(short, reviewer, original, "new-short-window-key").status_code == 422
    longer = custom_app(import_temporary_ttl_minutes=240)
    second = post(longer, reviewer, original, "new-long-window-key")
    assert second.status_code == 201
    assert second.json()["data"]["expires_at"] == first.json()["data"]["expires_at"]


def test_options_normalizes_offset_clock_and_submilliseconds(client, reviewer, clock, app):
    instant = clock.now().astimezone(timezone(timedelta(hours=-7))).replace(microsecond=987654)
    app.state.clock = lambda: instant
    result = reviewer.data("GET", "/admin/import-options")
    server = datetime.fromisoformat(result["server_time"])
    assert server.utcoffset() == timedelta(0)
    assert server == instant.astimezone(UTC).replace(microsecond=987000)
    payload = body(result["creation_deadline"])
    response = post(client, reviewer, payload)
    assert response.status_code == 201
    assert datetime.fromisoformat(response.json()["data"]["expires_at"]) == datetime.fromisoformat(
        payload["creation_deadline"]
    )


@pytest.mark.parametrize(
    "value", ["2026-11-10T08:05:00+00:60", "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"]
)
def test_invalid_offset_and_utc_overflow_are_validation_errors(client, reviewer, value):
    assert post(client, reviewer, body(value)).status_code == 422


def test_legacy_missing_deadline_never_replays_or_rewrites_receipt(client, reviewer, clock, db):
    payload = body((clock.now() + timedelta(minutes=5)).isoformat())
    assert post(client, reviewer, payload).status_code == 201
    legacy = {k: v for k, v in payload.items() if k != "creation_deadline"}
    assert post(client, reviewer, legacy).status_code == 422
    assert db.scalar(select(func.count()).select_from(DocumentImportJob)) == 1
    assert post(client, reviewer, payload).headers["Idempotency-Replayed"] == "true"


def test_formal_receipt_validation_remains_fail_closed_for_doc_create():
    ctx = SimpleNamespace(
        request=SimpleNamespace(url=SimpleNamespace(path="/api/v1/admin/import-jobs"))
    )
    with pytest.raises(RuntimeError, match="prototype"):
        SqlReceiptStore().validate(ctx, "digest", "fingerprint")
