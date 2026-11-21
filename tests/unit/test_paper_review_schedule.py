from datetime import UTC, date, datetime

from tutor_api.services.learning_pack_evidence import PaperEvidence
from tutor_api.services.paper_review_schedule import rebuild


def evidence(code, day, outcome, *, independence="independent", revision=0):
    return PaperEvidence(
        pack_id="pack",
        code=code,
        pack_revision=1,
        question_version_id="version",
        transcript="B",
        transcript_revision=revision,
        confirmed_at=datetime(2026, 11, 18, 18, tzinfo=UTC),
        completed_on=day,
        independence=independence,
        outcome=outcome,
        knowledge_ids=("node",),
    )


def test_late_returns_rebuild_in_actual_order_and_corrections_count_once():
    early = evidence("001", date(2026, 11, 1), "incorrect")
    first = evidence("002", date(2026, 11, 4), "correct")
    premature = evidence("004", date(2026, 11, 5), "correct")
    second = evidence("003", date(2026, 11, 11), "correct")
    schedule = rebuild([second, early, first, premature, first])["node"]
    assert (schedule.stage, schedule.due_on) == (2, date(2026, 11, 25))
    changed = evidence("003", date(2026, 11, 11), "correct", revision=1)
    assert rebuild([second, early, first, changed])["node"].stage == 1


def test_assisted_resets_and_unknown_does_not_move_the_schedule():
    first = evidence("001", date(2026, 11, 1), "correct")
    assisted = evidence("002", None, "correct", independence="assisted")
    unknown = evidence("003", None, "unknown")
    schedule = rebuild([first, assisted, unknown])["node"]
    assert (schedule.stage, schedule.due_on) == (0, date(2026, 11, 22))
    assert schedule.estimated_anchor


def test_independent_returns_progress_through_all_intervals_then_incorrect_resets():
    completed = [
        evidence("001", date(2026, 11, 1), "correct"),
        evidence("002", date(2026, 11, 4), "correct"),
        evidence("003", date(2026, 11, 11), "correct"),
        evidence("004", date(2026, 11, 25), "correct"),
        evidence("005", date(2026, 12, 25), "correct"),
        evidence("006", date(2027, 1, 24), "incorrect"),
    ]
    expected = [
        (0, date(2026, 11, 4)),
        (1, date(2026, 11, 11)),
        (2, date(2026, 11, 25)),
        (3, date(2026, 12, 25)),
        (3, date(2027, 1, 24)),
        (0, date(2027, 1, 27)),
    ]
    for count, result in enumerate(expected, start=1):
        review = rebuild(completed[:count])["node"]
        assert (review.stage, review.due_on) == result


def test_paper_plan_only_marks_waiting_knowledge_points():
    from datetime import date

    from tutor_api.services.learning_pack_worker import _review_plan
    from tutor_api.services.paper_review_schedule import PaperReview

    today = date(2026, 11, 19)
    schedule = {
        node: PaperReview(0, today, False, "source-version") for node in ("waiting", "unrelated")
    }
    reviews = _review_plan(
        schedule, {"settings": {"weekdays": [4]}}, 10, None, {"waiting"}, today, set()
    )
    assert {row["knowledge_id"]: row["deferred_reason"] for row in reviews} == {
        "waiting": "awaiting_return",
        "unrelated": "no_printable_item",
    }
