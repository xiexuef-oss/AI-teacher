"""内容审核后台里的解答题：小问、自查要点、参考答案都能看、能改，程序校验会把关。"""

from __future__ import annotations

from sqlalchemy import select

from support.admin import decide, detail_of, edit, edit_body, make_draft
from support.seeds import qid
from tutor_api.models import Question, Rubric
from tutor_api.services.content_seed import load_seed

MATH = "math-quadratic-param-written"
CHEM = "chem-ion-equation-written"


def _seed(key: str) -> dict:
    return next(q for q in load_seed().questions if q["key"] == key)


def test_the_detail_shows_subquestions_reference_answers_and_checklist_points(reviewer):
    seed = _seed(MATH)

    detail = reviewer.data("GET", f"/admin/questions/{qid(MATH)}")

    assert detail["answer_mode"] == "written" and detail["type"] == "solution"
    assert [(s["key"], s["stem"]) for s in detail["content"]["subquestions"]] == [
        (s["key"], s["stem"]) for s in seed["content"]["subquestions"]
    ]
    assert {s["answer_mode"] for s in detail["content"]["subquestions"]} == {"written"}
    assert detail["answer"]["value"] == seed["answer"]["value"]
    assert detail["rubric"] == {"points": seed["rubric"]["points"]}
    assert detail["teaching"]["leak_markers"] == seed["teaching"]["leak_markers"]
    assert [s["kind"] for s in detail["solutions"]] == ["standard"]
    assert detail["check_problems"] == []


def test_the_queue_can_be_filtered_down_to_the_written_questions(reviewer):
    page = reviewer.data("GET", "/admin/questions", params={"limit": 50})

    written = [item for item in page["items"] if item["answer_mode"] == "written"]
    assert len(written) == 3
    assert {item["type"] for item in written} == {"solution"}


def test_a_checklist_that_skips_a_subquestion_blocks_approval(reviewer, db):
    question_id = make_draft(db, MATH)
    row = db.scalar(select(Rubric).where(Rubric.question_id == question_id, Rubric.version == 1))
    row.rubric_json = {"points": [p for p in row.rubric_json["points"] if p["part"] != "2"]}
    db.commit()

    detail = detail_of(reviewer, question_id)
    assert any(
        "rubric.points" in problem and "2" in problem for problem in detail["check_problems"]
    )

    error = decide(reviewer, question_id, "approve", expect=422)
    assert error["code"] == "content_checks_failed"
    db.expire_all()
    assert db.get(Question, question_id).status == "draft"


def test_a_reference_answer_missing_for_a_subquestion_is_flagged(reviewer, db):
    from tutor_api.models import QuestionVersion

    question_id = make_draft(db, CHEM)
    version = db.scalar(select(QuestionVersion).where(QuestionVersion.question_id == question_id))
    version.answer_json = {**version.answer_json, "value": {"1": version.answer_json["value"]["1"]}}
    db.commit()

    problems = detail_of(reviewer, question_id)["check_problems"]

    assert any("answer.value" in problem for problem in problems)


def test_editing_a_subquestion_makes_a_new_version_that_still_passes_the_checks(reviewer, db):
    question_id = make_draft(db, MATH)
    before = detail_of(reviewer, question_id)
    changed = [
        {**before["content"]["subquestions"][0], "stem": "（改）求 $a$ 的取值范围；"},
        before["content"]["subquestions"][1],
    ]

    after = edit(
        reviewer,
        question_id,
        edit_body(before, content={**before["content"], "subquestions": changed}),
    )

    assert after["version"] == 2 and after["check_problems"] == []
    assert after["content"]["subquestions"][0]["stem"].startswith("（改）")
    assert after["rubric"] == before["rubric"]
    assert after["history"][-1]["changes"] == ["content"]


def test_editing_the_checklist_is_recorded_as_a_change_to_the_rubric(reviewer, db):
    question_id = make_draft(db, CHEM)
    before = detail_of(reviewer, question_id)
    points = [dict(point) for point in before["rubric"]["points"]]
    points[0]["text"] = "（改）碳酸钙写化学式，没有拆成离子"

    after = edit(reviewer, question_id, edit_body(before, rubric={"points": points}))

    assert after["rubric"]["points"][0]["text"].startswith("（改）")
    assert after["history"][-1]["changes"] == ["rubric"]
    assert after["check_problems"] == []


def test_a_checklist_with_scores_in_it_is_flagged(reviewer, new_reviewer, db):
    """自查要点只是清单，不带分值：带了分，学生就会把它当成评分。"""
    question_id = make_draft(db, CHEM)
    before = detail_of(reviewer, question_id)
    points = [dict(point) for point in before["rubric"]["points"]]
    points[0]["weight"] = 2

    after = edit(reviewer, question_id, edit_body(before, rubric={"points": points}))

    assert any(
        "rubric.points" in problem and "分值" in problem for problem in after["check_problems"]
    )
    error = decide(new_reviewer(), question_id, "approve", version=2, expect=422)
    assert error["code"] == "content_checks_failed"


def test_a_written_question_with_a_hint_that_gives_the_result_away_is_flagged(reviewer, db):
    question_id = make_draft(db, MATH)
    before = detail_of(reviewer, question_id)
    teaching = {**before["teaching"], "hints": [*before["teaching"]["hints"], "所以最大值为 3。"]}

    after = edit(reviewer, question_id, edit_body(before, teaching=teaching))

    assert any("可能泄题" in problem for problem in after["check_problems"])
