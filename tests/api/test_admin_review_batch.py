import pytest
from sqlalchemy import select

from support.admin import FAST_KEY, KEY, audit_rows, make_draft
from tutor_api.models import Question

PATH = "/admin/question-reviews/batch"


def item(id, **extra):
    return {"expected_review_revision": 1, 
        "question_id": id,
        "decision": "approve",
        "expected_version": 1,
        "confirmed": True,
        **extra,
    }


def test_partial_failure_replay_and_retry_subset(reviewer, app, new_reviewer):
    with app.state.session_factory() as db:
        first = make_draft(db, KEY)
        second = make_draft(db, FAST_KEY, created_by=reviewer.user_id)
    body = {"items": [item(first), item(second)]}
    result = reviewer.data("POST", PATH, json=body, key="batch-review-test")
    assert [i["status"] for i in result["items"]] == ["succeeded", "failed"]
    assert result["items"][1]["error"]["code"] == "self_review_forbidden"
    assert reviewer.data("POST", PATH, json=body, key="batch-review-test") == result
    with app.state.session_factory() as db:
        assert db.get(Question, first).status == "reviewed"
        assert len(audit_rows(db, first)) == 1
    reviewer.error("POST", PATH, json={"items": [item(first)]}, key="batch-review-test", expect=409)


@pytest.mark.parametrize(
    "change",
    [
        {"confirmed": False},
        {"confirmed": None},
        {"confirmed": 1},
        {"confirmed": "true"},
        {"expected_version": 0},
    ],
)
def test_explicit_confirmation_and_versions_are_required(reviewer, change):
    import uuid

    reviewer.error("POST", PATH, json={"items": [item(str(uuid.uuid4()), **change)]}, expect=422)


def test_duplicates_and_non_reviewers_rejected_before_resource_lookup(reviewer, onboarded):
    import uuid

    row = item(str(uuid.uuid4()))
    reviewer.error("POST", PATH, json={"items": [row, row]}, expect=422)
    onboarded.error("POST", PATH, json={"items": [row]}, expect=403)


def test_database_failure_after_first_item_rolls_back_entire_batch(reviewer, app, monkeypatch):
    from tutor_api.services import review_service

    with app.state.session_factory() as db:
        first = make_draft(db, KEY)
        second = make_draft(db, FAST_KEY)
    original = review_service.decide

    def broken(db, **kwargs):
        if kwargs["question_id"] == second:
            raise RuntimeError("simulated connection failure")
        return original(db, **kwargs)

    monkeypatch.setattr(review_service, "decide", broken)
    with pytest.raises(RuntimeError, match="simulated connection failure"):
        reviewer.request(
            "POST", PATH, json={"items": [item(first), item(second)]}, key="crash-review-test"
        )
    with app.state.session_factory() as db:
        assert db.get(Question, first).status == "draft"
    monkeypatch.setattr(review_service, "decide", original)
    result = reviewer.data(
        "POST", PATH, json={"items": [item(first), item(second)]}, key="crash-review-test"
    )
    assert all(i["status"] == "succeeded" for i in result["items"])


def test_threaded_same_key_replays_once_and_audits_once(reviewer, app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with app.state.session_factory() as db:
        question_id = make_draft(db, KEY)
    body = {"items": [item(question_id)]}
    barrier = Barrier(2)

    def run():
        barrier.wait(5)
        return reviewer.data("POST", PATH, json=body, key="threaded-review-key")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results[0] == results[1]
    assert results[0]["items"][0]["status"] == "succeeded"
    with app.state.session_factory() as db:
        assert len(audit_rows(db, question_id)) == 1


def test_threaded_different_keys_refresh_state_and_old_version_fails(reviewer, app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with app.state.session_factory() as db:
        question_id = make_draft(db, KEY)
    stale = reviewer.data("POST", PATH, json={"items": [item(question_id, expected_version=2)]})
    assert stale["items"][0]["error"]["code"] == "version_conflict"
    barrier = Barrier(2)

    def run(index):
        barrier.wait(5)
        return reviewer.data(
            "POST", PATH, json={"items": [item(question_id)]}, key=f"competing-review-{index}"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(r["items"][0]["status"] for r in results) == ["failed", "succeeded"]
    assert (
        next(r["items"][0]["error"]["code"] for r in results if r["items"][0]["status"] == "failed")
        == "review_revision_conflict"
    )


def test_publish_requires_separate_confirmation_independence_and_state(reviewer, new_reviewer, app):
    other = new_reviewer()
    with app.state.session_factory() as db:
        id = make_draft(db, KEY, created_by=reviewer.user_id)
    bad = other.data("POST", PATH, json={"items": [item(id, decision="publish")]})
    assert bad["items"][0]["error"]["code"] == "invalid_transition"
    assert (
        other.data("POST", PATH, json={"items": [item(id)]})["items"][0]["state"]["status"]
        == "reviewed"
    )
    self_publish = reviewer.data("POST", PATH, json={"items": [item(id, decision="publish", expected_review_revision=2)]})
    assert self_publish["items"][0]["error"]["code"] == "self_review_forbidden"
    result = other.data("POST", PATH, json={"items": [item(id, decision="publish", expected_review_revision=2)]})
    assert result["items"][0]["state"]["status"] == "published"


def test_missing_confirmation_and_unknown_question_are_distinct(reviewer):
    import uuid

    row = item(str(uuid.uuid4()))
    del row["confirmed"]
    reviewer.error("POST", PATH, json={"items": [row]}, expect=422)
    row["confirmed"] = True
    result = reviewer.data("POST", PATH, json={"items": [row]})
    assert result["items"][0]["error"]["status"] == 404


def test_content_and_unconfirmed_standard_solution_block_batch_publish(reviewer, app):
    from tutor_api.models import QuestionVersion

    with app.state.session_factory() as db:
        bad = make_draft(db, KEY)
        good = make_draft(db, FAST_KEY)
        version = db.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == bad, QuestionVersion.version == 1
            )
        )
        version.content_json = {**version.content_json, "stem": ""}
        db.commit()
    result = reviewer.data("POST", PATH, json={"items": [item(bad), item(good)]})
    assert result["items"][0]["error"]["code"] == "content_checks_failed"
    assert result["items"][1]["status"] == "succeeded"
    with app.state.session_factory() as db:
        make_draft(db, FAST_KEY)
        db.get(Question, good).status = "reviewed"
        db.commit()
    result = reviewer.data("POST", PATH, json={"items": [item(good, decision="publish", expected_review_revision=2)]})
    assert result["items"][0]["error"]["code"] == "solution_not_confirmed"


def test_receipt_storage_failure_cannot_commit_review_without_replay_record(
    reviewer, app, monkeypatch
):
    from tutor_api.proto_models import IdempotencyRecord

    with app.state.session_factory() as db:
        id = make_draft(db, KEY)
    original = IdempotencyRecord.__init__

    def unavailable(self, **kwargs):
        raise RuntimeError("receipt store unavailable")

    monkeypatch.setattr(IdempotencyRecord, "__init__", unavailable)
    with pytest.raises(RuntimeError, match="receipt store unavailable"):
        reviewer.request("POST", PATH, json={"items": [item(id)]}, key="receipt-failure-test")
    with app.state.session_factory() as db:
        assert db.get(Question, id).status == "draft"
        assert not audit_rows(db, id)
    monkeypatch.setattr(IdempotencyRecord, "__init__", original)
    assert (
        reviewer.data("POST", PATH, json={"items": [item(id)]}, key="receipt-failure-test")[
            "items"
        ][0]["status"]
        == "succeeded"
    )
