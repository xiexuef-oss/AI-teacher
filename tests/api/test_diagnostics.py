import json
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select

from support.flows import CORRECT, submit, tutor
from support.seeds import qid
from tutor_api.models import Attempt, Question, QuestionVersion, StudySession


def start(student, *, subject="math", key=None):
    workspace = student.data("GET", "/diagnostics")
    profile = student.data("GET", "/profile")
    return student.post(
        "/diagnostics",
        json={
            "subject": subject,
            "expected_revision": workspace["revision"],
            "expected_profile_revision": profile["revision"],
        },
        key=key,
    )


def open_item(student, run, position):
    workspace = student.data("GET", "/diagnostics")
    return student.data(
        "POST",
        f"/diagnostics/{run['id']}/items/{position}/session",
        json={"expected_revision": workspace["revision"]},
    )


@pytest.fixture
def eligible(onboarded):
    # Seed questions are G10; explicitly choose that grade rather than relaxing selection.
    onboarded.save_profile(
        json={
            "region_code": "CN-51",
            "subjects": ["math", "physics", "chemistry"],
            "grade": "G10",
            "exam_year": 2027,
        }
    )
    return onboarded


def test_read_empty_does_not_create_a_run_or_session(eligible, db):
    before = list(db.scalars(select(StudySession.id)))
    assert eligible.data("GET", "/diagnostics") == {"revision": 0, "run": None}
    assert eligible.data("GET", "/diagnostics") == {"revision": 0, "run": None}
    assert list(db.scalars(select(StudySession.id))) == before


def test_create_selects_three_fixed_objective_primary_questions(eligible, db):
    response = start(eligible, key="diagnostic-create")
    assert response.status_code == 201, response.text
    workspace = response.json()["data"]
    run = workspace["run"]
    assert workspace["revision"] == 1 and run["status"] == "active"
    assert run["scope"]["grade"] == "G10" and run["scope"]["region_code"] == "CN-51"
    assert len(run["items"]) == 3
    assert {item["position"] for item in run["items"]} == {1, 2, 3}
    for item in run["items"]:
        question = item["question"]
        assert question["subject"] == "math" and question["variant_of"] is None
        assert question["answer_mode"] not in {"written", "proof", "experiment"}
        assert item["session_id"] is None and item["submission"] is None
        assert item["question_version"] == db.get(Question, question["id"]).version
        assert question["source"]["is_engineering_sample"]
    assert not any(key in json.dumps(run) for key in ('"answer"', '"teaching"', '"strokes"'))
    replay = eligible.post(
        "/diagnostics",
        json={
            "subject": "math",
            "expected_revision": 0,
            "expected_profile_revision": run["scope"]["profile_revision"],
        },
        key="diagnostic-create",
    )
    assert replay.status_code == 201 and replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == response.json()
    assert start(eligible).status_code == 409


def test_resume_and_results_use_only_first_submission_of_linked_session(eligible):
    response = start(eligible)
    assert response.status_code == 201, response.text
    run = response.json()["data"]["run"]
    expected = {
        "submitted": 3,
        "independent_correct": 2,
        "independent_incorrect": 0,
        "assisted": 1,
        "unconfirmed": 0,
    }
    for position, item in enumerate(run["items"], 1):
        session = open_item(eligible, run, position)
        again = open_item(eligible, run, position)
        assert again["id"] == session["id"]
        if position == 2:
            tutor(eligible, session["id"], "request_hint")
        attempt = eligible.data("POST", "/attempts", expect=201, json={"session_id": session["id"]})
        key = next(key for key in CORRECT if qid(key) == item["question"]["id"])
        submit(eligible, attempt["id"], CORRECT[key])
    restored = eligible.data("GET", "/diagnostics")
    assert restored["run"]["status"] == "completed"
    assert restored["run"]["summary"] == expected
    assert eligible.data("GET", f"/diagnostics/{run['id']}")["summary"] == expected
    assert start(eligible).status_code == 201
    assert eligible.data("GET", f"/diagnostics/{run['id']}")["summary"] == expected


def test_abandon_keeps_session_and_stale_commands_cannot_touch_new_run(eligible):
    response = start(eligible)
    assert response.status_code == 201, response.text
    run = response.json()["data"]["run"]
    session = open_item(eligible, run, 1)
    revision = eligible.data("GET", "/diagnostics")["revision"]
    path = f"/diagnostics/{run['id']}/abandon"
    abandoned = eligible.data(
        "POST", path, json={"expected_revision": revision}, key="abandon-round-one"
    )
    assert abandoned["run"]["status"] == "abandoned"
    assert eligible.data("GET", f"/sessions/{session['id']}")["id"] == session["id"]
    next_run = start(eligible).json()["data"]
    assert next_run["run"]["id"] != run["id"]
    assert eligible.post(path, json={"expected_revision": revision}).status_code == 409
    replay = eligible.post(path, json={"expected_revision": revision}, key="abandon-round-one")
    assert replay.json()["data"] == abandoned
    assert eligible.data("GET", "/diagnostics") == next_run


def test_profile_and_question_changes_never_silently_replace_unopened_item(eligible, db, clock):
    response = start(eligible)
    assert response.status_code == 201, response.text
    run = response.json()["data"]["run"]
    first = run["items"][0]
    question = db.get(Question, first["question"]["id"])
    previous = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question.id, QuestionVersion.version == question.version
        )
    )
    question.version += 1
    db.add(
        QuestionVersion(
            id=str(uuid4()),
            question_id=question.id,
            version=question.version,
            content_json=deepcopy(previous.content_json),
            answer_json=deepcopy(previous.answer_json),
            teaching_json=deepcopy(previous.teaching_json),
            created_at=clock.now(),
        )
    )
    db.commit()
    path = f"/diagnostics/{run['id']}/items/1/session"
    error = eligible.error("POST", path, json={"expected_revision": 1}, expect=409)
    assert error["code"] == "question_version_conflict"
    eligible.save_profile(
        json={
            "region_code": "CN-50",
            "subjects": ["math", "physics", "chemistry"],
            "grade": "G10",
            "exam_year": 2027,
        }
    )
    error = eligible.error(
        "POST",
        f"/diagnostics/{run['id']}/items/2/session",
        json={"expected_revision": 1},
        expect=409,
    )
    assert error["code"] == "diagnostic_profile_conflict"
    assert eligible.data("GET", f"/diagnostics/{run['id']}") == run


def test_shortage_and_unselected_subject_fail_without_creating_progress(onboarded):
    # No G12 engineering sample coverage; never silently substitute G10.
    assert start(onboarded).status_code == 422
    assert onboarded.data("GET", "/diagnostics")["revision"] == 0
    onboarded.save_profile(json={"region_code": "CN-51", "subjects": ["math"], "grade": "G10"})
    assert start(onboarded, subject="physics").status_code == 422


def test_roles_ownership_cas_and_missing_key(eligible, new_student, parent, reviewer, anon):
    response = start(eligible)
    assert response.status_code == 201, response.text
    run = response.json()["data"]["run"]
    other = new_student()
    paths = [f"/diagnostics/{run['id']}", f"/diagnostics/{uuid4()}"]
    for path in paths:
        assert other.get(path).status_code == 404
    for actor in (parent, reviewer):
        assert actor.get("/diagnostics").status_code == 403
        assert actor.get(paths[0]).status_code == 403
        assert actor.post(paths[0] + "/abandon", json={"expected_revision": 1}).status_code == 403
    assert anon.get("/diagnostics").status_code == 401
    path = paths[0] + "/items/1/session"
    assert other.post(path, json={"expected_revision": 1}).status_code == 404
    assert eligible.post(path, json={"expected_revision": 0}).status_code == 409
    assert eligible.post(path, json={"expected_revision": 1}, key=False).status_code == 400
    for value in (-1, None, True, "1"):
        assert eligible.post(path, json={"expected_revision": value}).status_code == 422


@pytest.mark.parametrize("evaluation_state", ["uncertain", "pending", "error"])
def test_unconfirmed_attempts_never_count_as_right_or_wrong(eligible, db, evaluation_state):
    run = start(eligible).json()["data"]["run"]
    session = open_item(eligible, run, 1)
    attempt = eligible.data("POST", "/attempts", expect=201, json={"session_id": session["id"]})
    key = next(key for key in CORRECT if qid(key) == run["items"][0]["question"]["id"])
    submit(eligible, attempt["id"], CORRECT[key])
    row = db.get(Attempt, attempt["id"])
    row.evaluation_state = evaluation_state
    row.is_correct = True  # Even inconsistent old records must fail closed.
    db.commit()
    result = eligible.data("GET", f"/diagnostics/{run['id']}")
    assert result["summary"] == {
        "submitted": 1,
        "independent_correct": 0,
        "independent_incorrect": 0,
        "assisted": 0,
        "unconfirmed": 1,
    }
    assert result["items"][0]["submission"]["is_correct"] is None


def test_unrelated_sessions_and_later_submissions_do_not_replace_first(eligible):
    from support.flows import WRONG, solve

    run = start(eligible).json()["data"]["run"]
    item = run["items"][0]
    key = next(key for key in CORRECT if qid(key) == item["question"]["id"])
    solve(eligible, key)  # Same question, different session: not diagnostic evidence.
    assert eligible.data("GET", "/diagnostics")["run"]["summary"]["submitted"] == 0
    session = open_item(eligible, run, 1)
    first = eligible.data("POST", "/attempts", expect=201, json={"session_id": session["id"]})
    submit(eligible, first["id"], WRONG[key])
    later = eligible.data("POST", "/attempts", expect=201, json={"session_id": session["id"]})
    submit(eligible, later["id"], CORRECT[key])
    result = eligible.data("GET", "/diagnostics")["run"]
    assert result["items"][0]["submission"]["attempt_id"] == first["id"]
    assert result["summary"]["independent_incorrect"] == 1
    assert result["summary"]["independent_correct"] == 0


def test_bound_session_survives_profile_change_without_new_session(eligible):
    run = start(eligible).json()["data"]["run"]
    session = open_item(eligible, run, 1)
    eligible.save_profile(json={"region_code": "CN-50", "subjects": ["physics"]})
    assert open_item(eligible, run, 1)["id"] == session["id"]
    assert eligible.data("GET", "/diagnostics")["run"]["scope"] == run["scope"]


def test_private_subjective_variants_and_wrong_grades_cannot_fill_a_shortage(eligible, db):
    for question in db.scalars(select(Question).where(Question.subject == "math")):
        if question.variant_of_id is None and question.answer_mode not in {
            "written",
            "proof",
            "experiment",
        }:
            question.status = "draft"
    db.commit()
    assert start(eligible).status_code == 422
    assert eligible.data("GET", "/diagnostics") == {"revision": 0, "run": None}


def test_empty_history_and_export_do_not_create_a_workspace(eligible, db):
    from tutor_api.diagnostic_models import DiagnosticState

    assert eligible.data("GET", "/diagnostics/history") == {"items": [], "next_cursor": None}
    exported = eligible.data("GET", "/profile/learning-export")
    assert exported["diagnostic_runs"] == []
    assert exported["diagnostic_workspace"] == {"revision": 0, "run": None}
    assert db.get(DiagnosticState, eligible.user_id) is None


def _abandon_current(student):
    workspace = student.data("GET", "/diagnostics")
    return student.data(
        "POST",
        f"/diagnostics/{workspace['run']['id']}/abandon",
        json={"expected_revision": workspace["revision"]},
    )


def test_history_keyset_pages_same_timestamps_and_excludes_later_insert(eligible, clock):
    ids = []
    for _ in range(4):
        ids.append(start(eligible).json()["data"]["run"]["id"])
        _abandon_current(eligible)
    first = eligible.data("GET", "/diagnostics/history", params={"limit": 2})
    ordered = sorted(ids, reverse=True)
    assert [run["id"] for run in first["items"]] == ordered[:2]
    assert first["next_cursor"] == ordered[1]
    clock.advance(seconds=1)
    added = start(eligible).json()["data"]["run"]["id"]
    second = eligible.data(
        "GET", "/diagnostics/history", params={"limit": 2, "cursor": first["next_cursor"]}
    )
    assert [run["id"] for run in second["items"]] == ordered[2:]
    assert second["next_cursor"] is None
    assert added not in {run["id"] for run in second["items"]}


def test_history_cursor_never_authorizes_foreign_runs(eligible, new_student, parent, reviewer):
    private_id = start(eligible).json()["data"]["run"]["id"]
    other = new_student()
    assert other.data("GET", "/diagnostics/history")["items"] == []
    for cursor in (private_id, str(uuid4())):
        error = other.error("GET", "/diagnostics/history", params={"cursor": cursor}, expect=400)
        assert error["code"] == "invalid_cursor"
    for actor in (parent, reviewer):
        assert actor.get("/diagnostics/history", params={"cursor": private_id}).status_code == 403
    for params in ({"cursor": "invalid"}, {"limit": 0}, {"limit": 51}):
        assert eligible.get("/diagnostics/history", params=params).status_code == 422


def test_learning_export_includes_all_owned_plans_and_fixed_scope(eligible, new_student):
    first = start(eligible).json()["data"]["run"]
    _abandon_current(eligible)
    eligible.save_profile(json={"region_code": "CN-50", "grade": "G10", "subjects": ["math"]})
    second = start(eligible).json()["data"]["run"]
    other = new_student()
    other.save_profile(json={"region_code": "CN-51", "grade": "G10", "subjects": ["math"]})
    foreign = start(other).json()["data"]["run"]["id"]
    exported = eligible.data("GET", "/profile/learning-export")
    plans = {run["id"]: run for run in exported["diagnostic_runs"]}
    assert set(plans) == {first["id"], second["id"]}
    assert plans[first["id"]]["scope"]["region_code"] == "CN-51"
    assert plans[second["id"]]["scope"]["region_code"] == "CN-50"
    assert exported["diagnostic_workspace"] == eligible.data("GET", "/diagnostics")
    assert foreign not in json.dumps(exported)
    assert not any(key in json.dumps(plans) for key in ('"answer"', '"teaching"', '"strokes"'))


def test_plan_items_count_toward_whole_export_limit(eligible, monkeypatch):
    from tutor_api.services import student_learning_export

    workspace = start(eligible).json()["data"]
    monkeypatch.setattr(student_learning_export, "MAX_RECORDS", 3)
    assert eligible.get("/profile/learning-export").status_code == 413
    assert eligible.data("GET", "/diagnostics") == workspace


def test_sqlite_export_keeps_one_read_snapshot_during_concurrent_plan_creation(
    eligible, app, clock
):
    from sqlalchemy import event

    from tutor_api.schemas import DiagnosticCreateIn
    from tutor_api.services import diagnostic_service

    profile = eligible.data("GET", "/profile")
    factory = app.state.session_factory
    engine = factory.kw["bind"]
    created = []

    def another_device(connection, cursor, sql, parameters, context, many):
        if created or "FROM diagnostic_runs" not in sql:
            return
        created.append(None)
        with factory() as writer:
            result = diagnostic_service.create(
                writer,
                eligible.user_id,
                DiagnosticCreateIn(
                    subject="math",
                    expected_revision=0,
                    expected_profile_revision=profile["revision"],
                ),
                clock.now(),
            )
            writer.commit()
            created[0] = result["run"]["id"]

    event.listen(engine, "after_cursor_execute", another_device)
    try:
        output = eligible.data("GET", "/profile/learning-export")
    finally:
        event.remove(engine, "after_cursor_execute", another_device)
    assert created and created[0] is not None
    assert output["diagnostic_runs"] == []
    assert output["diagnostic_workspace"] == {"revision": 0, "run": None}
    assert eligible.data("GET", "/diagnostics")["run"]["id"] == created[0]
