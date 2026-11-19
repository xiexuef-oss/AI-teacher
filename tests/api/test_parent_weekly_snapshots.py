from datetime import UTC, date, datetime

from support.parents import authorize, links_of, revoke
from tutor_api.services.weekly_snapshots import save_snapshot


def test_authorized_parent_can_read_old_snapshot_until_revoked(db, onboarded, parent, settings):
    week = date(2026, 11, 2)
    now = datetime(2026, 11, 10, tzinfo=UTC)
    save_snapshot(db, settings, onboarded.user_id, week, now)
    changed = settings.model_copy(update={"progress_min_samples": settings.progress_min_samples + 1})
    save_snapshot(db, changed, onboarded.user_id, week, now)
    db.commit()
    path = f"/parents/students/{onboarded.user_id}/weekly-snapshots/{week}"
    parent.error("GET", path, expect=404)
    authorize(onboarded, parent)
    assert parent.data("GET", path)["revision"] == 2
    old = parent.data("GET", path, params={"revision": 1})
    assert old["revision"] == 1
    assert old["report"]["min_samples"] == settings.progress_min_samples
    parent.error("GET", path, params={"revision": 3}, expect=404)
    revoke(onboarded, links_of(onboarded)["links"][0]["id"])
    parent.error("GET", path, params={"revision": 1}, expect=404)
