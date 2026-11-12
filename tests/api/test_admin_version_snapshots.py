"""回看和对比旧版本：取某一个版本的完整内容（ADR-010）。

修改题目会覆盖题目行上的难度、年级和知识点关联；为了让旧版本能原样回看，修改时会把旧值记进旧版本、
新值记进新版本。版本里的审核标记（解法是否已审核）是那个版本当时的。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from support.admin import (
    AUTHOR,
    FAST_KEY,
    decide,
    detail_of,
    edit,
    edit_body,
    editable_parts,
    make_draft,
    snapshot,
)
from support.seeds import ALL_KEYS, DRAFT_KEYS, qid
from tutor_api.models import QuestionVersion

DRAFT_KEY = (
    "math-abs-decreasing"  # 种子里的待审样题：难度 2、高一、知识点 math.function.monotonicity
)


def _parts(shot: dict) -> dict:
    return {key: shot[key] for key in editable_parts_keys()}


def editable_parts_keys() -> tuple[str, ...]:
    return (
        "title",
        "difficulty",
        "grade",
        "content",
        "answer",
        "teaching",
        "solutions",
        "knowledge",
        "rubric",
    )


# ---------------------------------------------------------------- 没改过的题


@pytest.mark.parametrize("key", sorted(ALL_KEYS | DRAFT_KEYS))
def test_the_first_version_of_a_never_edited_question_is_what_the_detail_shows(reviewer, key):
    question_id = qid(key)
    detail = detail_of(reviewer, question_id)

    shot = snapshot(reviewer, question_id, 1)

    assert _parts(shot) == editable_parts(detail)
    assert (shot["question_id"], shot["version"], shot["is_current"]) == (question_id, 1, True)
    assert shot["created_by"] == detail["versions"][0]["created_by"]
    assert shot["created_at"] == detail["versions"][0]["created_at"]


# ---------------------------------------------------------------- 改过之后


def _edit_everything(reviewer, question_id: str) -> tuple[dict, dict]:
    """第 1 版 → 第 2 版：改题干、答案、难度、年级、知识点、标题。返回 (改之前的详情, 保存后的详情)。"""
    before = detail_of(reviewer, question_id)
    after = edit(
        reviewer,
        question_id,
        edit_body(
            before,
            title="改过的标题",
            difficulty=4,
            grade=None,
            content={**before["content"], "stem": "函数 $f(x)=|x+1|$ 的单调递减区间是（　）"},
            answer={**before["answer"], "value": ["C"]},
            knowledge=["math.function.concept", "math.function.monotonicity"],
        ),
    )
    return before, after


def test_an_old_version_keeps_its_own_content_difficulty_grade_and_knowledge(reviewer):
    question_id = qid(DRAFT_KEY)
    before, after = _edit_everything(reviewer, question_id)
    assert (before["difficulty"], before["grade"]) == (2, "G10")

    old = snapshot(reviewer, question_id, 1)
    new = snapshot(reviewer, question_id, 2)

    # 第 1 版：原样，包括被覆盖掉的难度、年级、知识点
    assert _parts(old) == {**editable_parts(before), "solutions": old["solutions"]}
    assert (old["difficulty"], old["grade"]) == (2, "G10")
    assert old["knowledge"] == ["math.function.monotonicity"]
    assert old["is_current"] is False and old["title"] == before["title"]
    # 第 2 版：改后的
    assert _parts(new) == editable_parts(after)
    assert (new["difficulty"], new["grade"]) == (4, None)
    assert new["knowledge"] == ["math.function.concept", "math.function.monotonicity"]
    assert new["is_current"] is True and new["title"] == "改过的标题"
    assert new["created_by"] == reviewer.user_id and old["created_by"] != reviewer.user_id


def test_every_version_in_a_chain_of_edits_stays_readable_with_its_own_values(reviewer):
    question_id = qid(DRAFT_KEY)
    detail = detail_of(reviewer, question_id)
    seen = {1: (detail["difficulty"], detail["title"])}
    for number, level in ((2, 3), (3, 5), (4, 1)):
        detail = edit(
            reviewer,
            question_id,
            edit_body(detail, difficulty=level, title=f"第 {number} 版的标题"),
        )
        seen[number] = (level, f"第 {number} 版的标题")

    for number, (level, title) in seen.items():
        shot = snapshot(reviewer, question_id, number)
        assert (shot["difficulty"], shot["title"]) == (level, title), number
        assert shot["is_current"] is (number == 4)
    assert [v["version"] for v in detail_of(reviewer, question_id)["versions"]] == [1, 2, 3, 4]


def test_an_old_version_keeps_the_review_marks_it_had_at_the_time(reviewer, new_reviewer, db):
    question_id = make_draft(db, FAST_KEY, created_by=AUTHOR)
    decide(reviewer, question_id, "approve", solution_kinds=["standard", "fast"])
    approved = detail_of(reviewer, question_id)
    assert all(s["reviewed"] for s in approved["solutions"])

    after = edit(new_reviewer(), question_id, edit_body(approved, title="改了标题"))

    old = snapshot(reviewer, question_id, 1)
    new = snapshot(reviewer, question_id, 2)
    assert [s["reviewed"] for s in old["solutions"]] == [True, True]
    assert {s["reviewed_by"] for s in old["solutions"]} == {reviewer.user_id}
    assert [s["reviewed"] for s in new["solutions"]] == [False, False]
    assert _parts(new) == editable_parts(after)


def test_the_versions_in_the_detail_can_all_be_fetched(reviewer):
    question_id = qid(DRAFT_KEY)
    _edit_everything(reviewer, question_id)

    for entry in detail_of(reviewer, question_id)["versions"]:
        shot = snapshot(reviewer, question_id, entry["version"])
        assert (shot["version"], shot["created_by"], shot["created_at"]) == (
            entry["version"],
            entry["created_by"],
            entry["created_at"],
        )


def test_a_version_written_before_snapshots_existed_falls_back_to_the_current_values(reviewer, db):
    """旧数据：早于"修改时记下旧版本的难度、年级、知识点"的版本没有这几项快照，回退到题目现在的值，不报错。"""
    question_id = qid(DRAFT_KEY)
    _edit_everything(reviewer, question_id)
    db.expire_all()
    row = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question_id, QuestionVersion.version == 1
        )
    )
    row.content_json = {
        key: value
        for key, value in row.content_json.items()
        if key not in {"difficulty", "grade", "knowledge"}
    }
    db.commit()

    old = snapshot(reviewer, question_id, 1)

    current = detail_of(reviewer, question_id)
    assert old["difficulty"] == current["difficulty"] and old["grade"] == current["grade"]
    assert old["knowledge"] == sorted(node["code"] for node in current["knowledge"])
    assert old["title"] != current["title"], "题面、标题这些本来就是分版本存的，不受影响"


# ---------------------------------------------------------------- 权限与错误


def test_unknown_question_or_version_is_404_and_bad_version_numbers_are_422(reviewer):
    question_id = qid(DRAFT_KEY)

    assert snapshot(reviewer, question_id, 2, expect=404)["code"] == "not_found"
    assert snapshot(reviewer, str(uuid.uuid4()), 1, expect=404)["code"] == "not_found"
    for bad in (0, -1, "abc"):
        error = reviewer.error("GET", f"/admin/questions/{question_id}/versions/{bad}", expect=422)
        assert error["code"] == "validation_error", bad


def test_only_reviewers_can_read_versions_and_students_cannot_probe(anon, onboarded):
    path = f"/admin/questions/{qid(DRAFT_KEY)}/versions/1"

    assert anon.error("GET", path, expect=401, auth=False)["code"] == "unauthenticated"
    assert onboarded.error("GET", path, expect=403)["code"] == "forbidden"
    unknown = f"/admin/questions/{uuid.uuid4()}/versions/9"
    assert onboarded.error("GET", unknown, expect=403)["code"] == "forbidden"
