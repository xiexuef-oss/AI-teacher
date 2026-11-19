from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab import __file__ as reportlab_path

from support.clock import FakeClock
from tutor_api.models import LearningPackPublication
from tutor_api.services.learning_jobs import cancel, claim, enqueue
from tutor_api.services.learning_pack_publication import PrintedQuestion, publish


def test_publication_commits_pair_and_respects_cancel(db, student):
    now = datetime(2026, 11, 18, tzinfo=UTC)
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    items = [PrintedQuestion("version-1", "Compute 2 + 2.", "Answer: four")]
    job = enqueue(db, student.user_id, "publish", now)
    lease = claim(db, job, now)
    assert lease is not None
    with pytest.raises(ValueError):
        publish(db, job, lease, [], font, lambda: now)
    assert db.get(LearningPackPublication, job) is None
    assert publish(db, job, lease, items, font, lambda: now)
    db.commit()
    pair = db.get_one(LearningPackPublication, job)
    assert pair.student_pdf.startswith(b"%PDF")
    assert pair.solution_pdf.startswith(b"%PDF")
    assert pair.manifest_json["items"][0]["question_version_id"] == "version-1"
    assert not publish(db, job, lease, items, font, lambda: now)

    job = enqueue(db, student.user_id, "cancel", now)
    lease = claim(db, job, now)
    assert lease is not None and cancel(db, student.user_id, job)
    assert not publish(db, job, lease, items, font, lambda: now)
    assert db.get(LearningPackPublication, job) is None


def test_continuation_pages_have_distinct_tokens(db, student):
    now = datetime(2026, 11, 18, tzinfo=UTC)
    font = Path(reportlab_path).parent / "fonts" / "Vera.ttf"
    item = PrintedQuestion("version-1", "Continue reading. " * 1200, "Answer: four")
    job = enqueue(db, student.user_id, "multi-page", now)
    lease = claim(db, job, now)
    assert lease is not None and publish(db, job, lease, [item], font, lambda: now)
    pack = db.get_one(LearningPackPublication, job)
    manifest_item = pack.manifest_json["items"][0]
    tokens = [manifest_item["page_token"], *manifest_item["continuation_tokens"]]
    assert len(set(tokens)) == len(PdfReader(BytesIO(pack.student_pdf)).pages) > 1


@pytest.mark.parametrize("renders_before_expiry", [0, 1, 2])
def test_expired_lease_skips_remaining_render(db, student, monkeypatch, renders_before_expiry):
    from tutor_api.services import learning_pack_publication as publication
    from tutor_api.services.learning_jobs import LEASE

    clock = FakeClock()
    job = enqueue(db, student.user_id, "expired", clock.now())
    token = claim(db, job, clock.now())
    assert token is not None
    renders = 0

    def render(*args, **kwargs):
        nonlocal renders
        renders += 1
        assert renders <= renders_before_expiry
        if renders == renders_before_expiry:
            clock.advance(LEASE.total_seconds())
        return b"%PDF"

    if renders_before_expiry == 0:
        clock.advance(LEASE.total_seconds())
    monkeypatch.setattr(publication, "render_student", render)
    monkeypatch.setattr(publication, "render_solutions", render)
    items = [PrintedQuestion("version-1", "Question", "Solution")]
    assert not publish(db, job, token, items, Path("unused"), clock.now)
    assert renders == renders_before_expiry
    assert db.get(LearningPackPublication, job) is None


@pytest.mark.parametrize("cancel_after", [1, 2])
def test_cancellation_during_pdf_render_does_not_publish(db, student, monkeypatch, cancel_after):
    from tutor_api.models import LearningJob
    from tutor_api.services import learning_pack_publication as publication

    clock = FakeClock()
    job = enqueue(db, student.user_id, "cancel-during-render", clock.now())
    token = claim(db, job, clock.now())
    assert token is not None
    renders = 0

    def render(*args, **kwargs):
        nonlocal renders
        renders += 1
        if renders == cancel_after:
            assert cancel(db, student.user_id, job)
        return b"%PDF"

    monkeypatch.setattr(publication, "render_student", render)
    monkeypatch.setattr(publication, "render_solutions", render)
    items = [PrintedQuestion("version-1", "Question", "Solution")]
    assert not publish(db, job, token, items, Path("unused"), clock.now)
    assert renders == cancel_after
    assert db.get_one(LearningJob, job).status == "cancelled"
    assert db.get(LearningPackPublication, job) is None
