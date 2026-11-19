from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier

import pytest

from support.parents import authorize
from tutor_api.services.weekly_snapshots import generate_due_snapshots, save_snapshot


def test_closed_week_is_immutable_and_same_payload_does_not_create_a_revision(
    db, student, settings
):
    week = date(2026, 11, 9)
    now = datetime(2026, 11, 18, tzinfo=UTC)
    first = save_snapshot(db, settings, student.user_id, week, now)
    assert first.revision == 1
    assert save_snapshot(db, settings, student.user_id, week, now).revision == 1
    assert "student_display_name" not in first.summary_json
    updated_settings = settings.model_copy(
        update={"progress_min_samples": settings.progress_min_samples + 1}
    )
    newer = save_snapshot(db, updated_settings, student.user_id, week, now)
    assert newer.revision == 2
    assert first.summary_json["min_samples"] == settings.progress_min_samples
    with pytest.raises(ValueError):
        save_snapshot(db, settings, student.user_id, date(2026, 11, 16), now)


def test_weekly_generation_waits_for_monday_morning_and_is_idempotent(
    app,
    onboarded,
    parent,
    settings,
    db,
):
    authorize(onboarded, parent)
    factory = app.state.session_factory
    before = datetime(2026, 11, 15, 22, 59, tzinfo=UTC)
    due = datetime(2026, 11, 15, 23, tzinfo=UTC)
    assert generate_due_snapshots(factory, settings, before) == 0
    assert generate_due_snapshots(factory, settings, due) == 1
    assert generate_due_snapshots(factory, settings, due) == 0
    snapshot = parent.data(
        "GET", f"/parents/students/{onboarded.user_id}/weekly-snapshots/2026-11-09"
    )
    assert snapshot["revision"] == 1


def test_identical_concurrent_weekly_writes_share_revision(app, student, settings):
    barrier = Barrier(2)
    week = date(2026, 11, 9)
    now = datetime(2026, 11, 18, tzinfo=UTC)

    def write():
        with app.state.session_factory() as session:
            barrier.wait(timeout=5)
            snapshot = save_snapshot(session, settings, student.user_id, week, now)
            session.commit()
            return snapshot.revision

    with ThreadPoolExecutor(max_workers=2) as pool:
        writes = [pool.submit(write) for _ in range(2)]
        assert [write.result(timeout=15) for write in writes] == [1, 1]
