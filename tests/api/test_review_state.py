"""Recovery reads current state even when a list intentionally omits the item."""

import uuid

import pytest

from support.flows import blank, solve
from tutor_api.models import Question, ReviewItem


def _item(student):
    return solve(student, "math-ineq-min", blank("5"))[2]["review_item"]


def test_review_state_is_compact_private_and_current(onboarded, db):
    item = _item(onboarded)
    response = onboarded.request("GET", f"/reviews/{item['id']}/state")
    assert response.status_code == 200
    state = response.json()["data"]
    assert set(state) == {
        "id",
        "question_id",
        "status",
        "stage",
        "total_stages",
        "due_at",
        "last_result",
        "last_attempt_id",
        "updated_at",
    }
    assert state["id"] == item["id"]
    assert state["question_id"] == item["question_id"]
    assert state["last_attempt_id"] is None
    assert "no-store" in response.headers["cache-control"]
    row = db.get(ReviewItem, item["id"])
    row.stage = 2
    db.commit()
    assert onboarded.data("GET", f"/reviews/{item['id']}/state")["stage"] == 2


@pytest.mark.parametrize("hidden", ["mastered", "withdrawn"])
def test_review_state_does_not_require_list_visibility(onboarded, db, hidden):
    item = _item(onboarded)
    row = db.get(ReviewItem, item["id"])
    if hidden == "mastered":
        row.status = "mastered"
        row.stage = 3
    else:
        db.get(Question, row.question_id).status = "withdrawn"
    db.commit()
    assert onboarded.data("GET", "/reviews/due", params={"scope": "all"})["items"] == []
    state = onboarded.data("GET", f"/reviews/{item['id']}/state")
    assert state["status"] == row.status
    assert state["stage"] == row.stage


def test_review_state_enforces_owner_and_role_before_resource_lookup(
    onboarded,
    new_student,
    parent,
    reviewer,
    anon,
):
    item = _item(onboarded)
    paths = [f"/reviews/{item['id']}/state", f"/reviews/{uuid.uuid4()}/state"]
    stranger = new_student()
    errors = [stranger.error("GET", path, expect=404) for path in paths]
    assert {key: value for key, value in errors[0].items() if key != "request_id"} == {
        key: value for key, value in errors[1].items() if key != "request_id"
    }
    for path in paths:
        for forbidden in (parent, reviewer):
            assert forbidden.error("GET", path, expect=403)["code"] == "forbidden"
        anon.error("GET", path, expect=401)
