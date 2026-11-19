"""SEC304 regression plan. Do not send answer-bearing visuals during independent work."""

import copy

import pytest
from sqlalchemy import select

from support.flows import CORRECT, WRONG, begin, session_of, solve, submit, tutor, tutor_error
from support.seeds import qid
from tutor_api.models import Attempt, QuestionVersion

VISUAL_KEYS = [
    "chem-conservation-co2",
    "phys-incline-accel",
    "math-ineq-rect",
    "math-mono-quadratic",
]


def assert_blocked(step):
    assert step["events"]
    assert all(event["type"] != "visual" for event in step["events"])
    for event in step["events"]:
        assert not {"template_id", "params", "caption", "static_fallback"} & event["payload"].keys()
    assert step["session"]["used_solution"] is False
    assert step["session"]["independent_ended"] is False


@pytest.mark.parametrize("key", VISUAL_KEYS)
def test_independent_request_never_releases_answer_bearing_visual_spec(onboarded, key):
    session, _ = begin(onboarded, key)
    assert_blocked(tutor(onboarded, session["id"], "request_visual"))
    assert session_of(onboarded, session["id"])["assisted"] is False


@pytest.mark.parametrize("confirm", [False, True])
def test_visual_action_confirmation_cannot_replace_explicit_full_solution_action(
    onboarded, confirm
):
    session, _ = begin(onboarded, "chem-conservation-co2")
    assert_blocked(
        tutor(onboarded, session["id"], "request_visual", confirm_end_independent=confirm)
    )


@pytest.mark.parametrize("field", ["caption", "static_fallback"])
def test_answer_text_and_untrusted_seed_safety_metadata_do_not_bypass_phase_gate(
    onboarded, db, field
):
    row = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == qid("chem-conservation-co2"),
            QuestionVersion.version == 1,
        )
    )
    teaching = copy.deepcopy(row.teaching_json)
    teaching["visual"][field] = "SEC304 secret answer is 4.4 g"
    teaching["visual"]["independent_safe"] = True
    teaching["visual"]["requires_solution"] = False
    row.teaching_json = teaching
    db.commit()
    session, _ = begin(onboarded, "chem-conservation-co2")
    step = tutor(onboarded, session["id"], "request_visual")
    assert_blocked(step)
    assert "SEC304 secret" not in str(step["events"])


@pytest.mark.parametrize("key", VISUAL_KEYS)
def test_submitted_attempt_can_use_visual_without_rewriting_its_evaluation(onboarded, db, key):
    session, attempt = begin(onboarded, key)
    result = submit(onboarded, attempt["id"], CORRECT[key])
    before = copy.deepcopy(db.get(Attempt, attempt["id"]).evaluation_json)
    step = tutor(onboarded, session["id"], "request_visual")
    assert any(event["type"] == "visual" for event in step["events"])
    db.expire_all()
    assert db.get(Attempt, attempt["id"]).evaluation_json == before
    assert result["evaluation"]["independent"] is True


@pytest.mark.parametrize("key", VISUAL_KEYS)
def test_explicit_full_solution_then_visual_is_available_and_audited(onboarded, key):
    session, _ = begin(onboarded, key)
    solution = tutor(onboarded, session["id"], "request_standard", confirm_end_independent=True)
    assert solution["session"]["used_solution"] is True
    step = tutor(onboarded, session["id"], "request_visual")
    assert any(event["type"] == "visual" for event in step["events"])
    assert step["session"]["used_solution"] is True


def test_unsubmitted_retest_restriction_precedes_visual_phase_prompt(onboarded, clock):
    _, _, result = solve(onboarded, "chem-conservation-co2", WRONG["chem-conservation-co2"])
    clock.advance(days=1)
    session, _ = begin(
        onboarded,
        "chem-conservation-co2",
        origin="review",
        review_item_id=result["review_item"]["id"],
    )
    error = tutor_error(
        onboarded, session["id"], "request_visual", expect=409, confirm_end_independent=True
    )
    assert error["code"] == "hints_disabled_in_retest"
