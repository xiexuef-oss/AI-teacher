"""修改题目并产生新版本（PRD P0 第 9 条、docs/07："修改题干或答案后增加版本，旧版本留痕"）。

规则：draft / reviewed / withdrawn 的题可以改，已上线的要先下线；新版本回到 draft，审核标记清空；
改的人成为新版本的提交者、不能自己二审；没有改动不产生空版本；学生已经开始的会话继续按旧版本判分。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from support.admin import (
    AUTHOR,
    FAST_KEY,
    KEY,
    audit_rows,
    decide,
    edit,
    edit_body,
    make_draft,
)
from support.flows import begin, choice, submit
from support.seeds import qid
from tutor_api.models import Question, QuestionVersion, Solution

DRAFT_KEY = "math-abs-decreasing"  # 种子里的待审样题，作者是占位的"工程样题作者"，答案 A


def detail_of(who, question_id: str) -> dict:
    return who.data("GET", f"/admin/questions/{question_id}")


def stem_edit(detail: dict, stem: str) -> dict:
    return edit_body(detail, content={**detail["content"], "stem": stem})


# ---------------------------------------------------------------- 基本流程


def test_editing_a_draft_appends_a_version_and_keeps_the_old_one(reviewer):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)

    after = edit(
        reviewer,
        question_id,
        stem_edit(before, "函数 $f(x)=|x-2|$ 的单调递减区间是（　）"),
    )

    assert after["version"] == 2 and after["status"] == "draft"
    assert "|x-2|" in after["content"]["stem"]
    assert [v["version"] for v in after["versions"]] == [1, 2]
    assert after["versions"][1]["created_by"] == reviewer.user_id
    assert after["created_by"] == reviewer.user_id, "改的人成为新版本的提交者"
    # 其余内容原样带过来
    assert after["answer"] == before["answer"] and after["title"] == before["title"]
    assert [s["kind"] for s in after["solutions"]] == [s["kind"] for s in before["solutions"]]


def test_the_old_version_is_kept_as_it_was(reviewer, db):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)
    edit(reviewer, question_id, stem_edit(before, "改过的题干 $x$"))

    db.expire_all()
    rows = {
        row.version: row
        for row in db.scalars(
            select(QuestionVersion).where(QuestionVersion.question_id == question_id)
        )
    }
    assert set(rows) == {1, 2}
    assert rows[1].content_json["stem"] == before["content"]["stem"]
    assert rows[2].content_json["stem"] == "改过的题干 $x$"
    old_solutions = list(
        db.scalars(
            select(Solution).where(Solution.question_id == question_id, Solution.version == 1)
        )
    )
    assert old_solutions, "旧版本的解法也留着"


def test_the_edit_is_audited_and_shows_in_the_history_with_what_changed(reviewer):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)

    after = edit(
        reviewer,
        question_id,
        edit_body(
            before,
            title="新的标题",
            difficulty=3,
            comment="标题改得更具体",
        ),
    )

    (entry,) = after["history"]
    assert entry["action"] == "edit"
    assert (entry["from_status"], entry["to_status"], entry["version"]) == ("draft", "draft", 2)
    assert entry["actor_id"] == reviewer.user_id and entry["comment"] == "标题改得更具体"
    assert sorted(entry["changes"]) == ["difficulty", "title"]


def test_the_edit_writes_an_audit_row_without_student_data(reviewer, db):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)
    edit(
        reviewer,
        question_id,
        stem_edit(before, "另一个题干"),
        headers={"X-Request-Id": "edit-trace-1"},
    )

    (row,) = audit_rows(db, question_id)

    assert row.action == "question.edit" and row.actor_id == reviewer.user_id
    assert row.request_id == "edit-trace-1"
    assert row.detail_json["from"] == "draft" and row.detail_json["to"] == "draft"
    assert row.detail_json["version"] == 2 and row.detail_json["previous_version"] == 1
    assert row.detail_json["changes"] == ["content"]


def test_nothing_changed_is_422_and_makes_no_version(reviewer, db):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)

    error = edit(reviewer, question_id, edit_body(before), expect=422)

    assert error["code"] == "no_changes"
    db.expire_all()
    assert db.get(Question, question_id).version == 1
    assert audit_rows(db, question_id) == []


def test_a_round_trip_of_every_seeded_question_is_recognised_as_no_change(reviewer, db):
    """详情里给出的内容原样传回，必须被认作"没有改动"——说明读出来的和写进去的是同一种表示。

    20 道样题（选择题、填空题、带图解、带快速解法、带额外泄题标记……）逐道来回；已发布的先改回草稿，
    不然会先被"已上线要先下线"挡住，测不到比较本身。
    """
    from support.seeds import ALL_KEYS, DRAFT_KEYS

    for key in sorted(ALL_KEYS | DRAFT_KEYS):
        question_id = qid(key)
        if key in ALL_KEYS:
            make_draft(db, key)
        error = edit(reviewer, question_id, edit_body(detail_of(reviewer, question_id)), expect=422)
        assert error["code"] == "no_changes", key
        assert detail_of(reviewer, question_id)["version"] == 1, key


def test_every_question_can_be_edited_and_still_passes_the_checks_when_nothing_important_changed(
    reviewer, db
):
    """真正改一处（标题）之后，其余内容原样保存：校验结果和改之前一样（样题都是通过的）。"""
    from support.seeds import ALL_KEYS, DRAFT_KEYS

    for key in sorted(ALL_KEYS | DRAFT_KEYS):
        question_id = qid(key)
        if key in ALL_KEYS:
            make_draft(db, key)
        before = detail_of(reviewer, question_id)
        after = edit(reviewer, question_id, edit_body(before, title=before["title"] + "（改）"))
        assert after["version"] == 2 and after["check_problems"] == [], key
        assert after["answer"] == before["answer"], key
        assert after["teaching"] == before["teaching"], key
        assert after["solutions"] == [
            {**solution, "reviewed": False, "reviewed_by": None} for solution in before["solutions"]
        ], key


# ---------------------------------------------------------------- 状态


def test_a_reviewed_question_goes_back_to_draft_and_loses_its_review_marks(
    reviewer, new_reviewer, db
):
    question_id = make_draft(db, FAST_KEY)
    decide(reviewer, question_id, "approve", solution_kinds=["standard", "fast"])
    before = detail_of(reviewer, question_id)
    assert before["status"] == "reviewed" and before["reviewed_by"] == reviewer.user_id

    editor = new_reviewer()
    after = edit(
        editor, question_id, stem_edit(before, before["content"]["stem"] + " 请写出单位。")
    )

    assert (after["status"], after["version"], after["reviewed_by"]) == ("draft", 2, None)
    assert all(s["reviewed"] is False and s["reviewed_by"] is None for s in after["solutions"])
    db.expire_all()
    old = list(
        db.scalars(
            select(Solution).where(Solution.question_id == question_id, Solution.version == 1)
        )
    )
    assert old and all(s.reviewed for s in old), "旧版本当时的审核标记不动"


def test_a_published_question_must_be_withdrawn_before_it_can_be_edited(reviewer):
    before = detail_of(reviewer, qid(KEY))
    assert before["status"] == "published"

    error = edit(reviewer, qid(KEY), stem_edit(before, "偷偷改一下"), expect=409)

    assert error["code"] == "invalid_transition" and "下线" in error["message"]
    assert detail_of(reviewer, qid(KEY))["version"] == 1


def test_a_withdrawn_question_can_be_fixed_and_sent_through_review_again(
    reviewer, new_reviewer, onboarded
):
    question_id = qid(KEY)
    decide(reviewer, question_id, "withdraw", comment="选项 C 的分析有误")
    onboarded.error("GET", f"/questions/{question_id}", expect=404)
    before = detail_of(reviewer, question_id)
    assert before["status"] == "withdrawn"

    fixer = new_reviewer()
    after = edit(
        fixer,
        question_id,
        stem_edit(before, "函数 $f(x)=x^2-2x-3$ 的单调递增区间是（　）。（已修订）"),
        headers={},
    )
    assert (after["status"], after["version"]) == ("draft", 2)
    onboarded.error("GET", f"/questions/{question_id}", expect=404)

    # 改的人不能自己二审，另一个人可以
    assert (
        decide(fixer, question_id, "approve", version=2, expect=403)["code"]
        == "self_review_forbidden"
    )
    decide(reviewer, question_id, "approve", version=2)
    decide(reviewer, question_id, "publish", version=2)

    shown = onboarded.data("GET", f"/questions/{question_id}")
    assert shown["version"] == 2 and "已修订" in shown["content"]["stem"]


def test_the_person_who_edited_cannot_approve_their_own_edit(reviewer, db):
    question_id = make_draft(db, created_by=str(uuid.uuid4()))
    before = detail_of(reviewer, question_id)
    after = edit(reviewer, question_id, stem_edit(before, "我改过的题干"))

    error = decide(reviewer, question_id, "approve", version=after["version"], expect=403)

    assert error["code"] == "self_review_forbidden"


# ---------------------------------------------------------------- 并发、权限、幂等


def test_a_stale_version_is_a_conflict(reviewer):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)
    edit(reviewer, question_id, stem_edit(before, "第一次修改"))

    error = edit(reviewer, question_id, stem_edit(before, "基于旧版本的修改"), expect=409)

    assert error["code"] == "version_conflict" and error["details"]["current_version"] == 2


def test_only_reviewers_can_edit_and_students_cannot_even_probe(onboarded, anon, reviewer):
    body = edit_body(detail_of(reviewer, qid(DRAFT_KEY)))
    path = f"/admin/questions/{qid(DRAFT_KEY)}/versions"

    assert anon.error("POST", path, expect=401, auth=False, json=body)["code"] == "unauthenticated"
    assert onboarded.error("POST", path, expect=403, json=body)["code"] == "forbidden"
    assert (
        onboarded.error("POST", f"/admin/questions/{uuid.uuid4()}/versions", expect=403, json={})[
            "code"
        ]
        == "forbidden"
    )


def test_unknown_question_is_404(reviewer):
    body = edit_body(detail_of(reviewer, qid(DRAFT_KEY)))

    assert edit(reviewer, str(uuid.uuid4()), body, expect=404)["code"] == "not_found"


def test_retrying_with_the_same_key_makes_one_version(reviewer, db):
    question_id = qid(DRAFT_KEY)
    body = stem_edit(detail_of(reviewer, question_id), "只改一次")
    path = f"/admin/questions/{question_id}/versions"

    first = reviewer.post(path, json=body, key="edit-once-0001")
    second = reviewer.post(path, json=body, key="edit-once-0001")

    assert first.status_code == second.status_code == 201
    assert second.headers["idempotency-replayed"] == "true" and second.json() == first.json()
    db.expire_all()
    assert db.get(Question, question_id).version == 2
    assert len(audit_rows(db, question_id)) == 1


def test_editing_requires_an_idempotency_key(reviewer):
    question_id = qid(DRAFT_KEY)
    body = stem_edit(detail_of(reviewer, question_id), "没带幂等键")

    response = reviewer.post(f"/admin/questions/{question_id}/versions", json=body, key=False)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "idempotency_key_required"


# ---------------------------------------------------------------- 内容校验


def test_unknown_knowledge_and_duplicate_solutions_are_rejected_at_save(reviewer):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)

    unknown = edit(
        reviewer, question_id, edit_body(before, knowledge=["math.no.such.node"]), expect=422
    )
    assert unknown["code"] == "validation_error"
    assert "math.no.such.node" in str(unknown["details"])

    other_subject = edit(
        reviewer, question_id, edit_body(before, knowledge=["phys.friction"]), expect=422
    )
    assert other_subject["code"] == "validation_error"

    twice = before["solutions"] + before["solutions"]
    duplicated = edit(
        reviewer,
        question_id,
        edit_body(
            before,
            solutions=[
                {
                    k: s[k]
                    for k in (
                        "kind",
                        "steps",
                        "final_answer",
                        "key_points",
                        "conditions",
                        "boundary",
                    )
                }
                for s in twice
            ],
        ),
        expect=422,
    )
    assert duplicated["code"] == "validation_error"
    assert detail_of(reviewer, question_id)["version"] == 1


def test_unknown_fields_and_oversized_text_are_rejected(reviewer):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)

    assert (
        edit(reviewer, question_id, {**edit_body(before), "status": "published"}, expect=422)[
            "code"
        ]
        == "validation_error"
    )
    huge = {**before["content"], "stem": "长" * 4001}
    assert (
        edit(reviewer, question_id, edit_body(before, content=huge), expect=422)["code"]
        == "validation_error"
    )
    assert (
        edit(reviewer, question_id, edit_body(before, title=""), expect=422)["code"]
        == "validation_error"
    )
    assert (
        edit(reviewer, question_id, edit_body(before, difficulty=9), expect=422)["code"]
        == "validation_error"
    )


def test_a_half_finished_draft_can_be_saved_but_not_approved(reviewer, new_reviewer):
    """保存不做程序校验（草稿可以是半成品）；校验结果在详情里，二审之前必须清零。"""
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)

    saved = edit(
        reviewer, question_id, edit_body(before, answer={**before["answer"], "value": ["Z"]})
    )

    assert any("不存在的选项" in problem for problem in saved["check_problems"])
    error = decide(new_reviewer(), question_id, "approve", version=2, expect=422)
    assert error["code"] == "content_checks_failed"

    fixed = edit(
        reviewer, question_id, edit_body(saved, answer={**saved["answer"], "value": ["A"]})
    )
    assert fixed["check_problems"] == [] and fixed["version"] == 3
    assert decide(new_reviewer(), question_id, "approve", version=3)["status"] == "reviewed"


def test_changing_the_answer_recomputes_the_leak_markers(reviewer, db):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)
    edit(reviewer, question_id, edit_body(before, answer={**before["answer"], "value": ["C"]}))

    db.expire_all()
    stored = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question_id, QuestionVersion.version == 2
        )
    ).teaching_json["leak_markers"]

    assert "选C" in stored and "选A" not in stored, "标记要跟着新答案走，不能还是旧答案的"


def test_reviewer_supplied_leak_markers_survive_a_round_trip(reviewer, db):
    """表达式答案的写法太多，程序列不全，审校员补的标记要留着；系统自动加的不当成"审校员补的"。"""
    question_id = make_draft(db, "phys-incline-accel-v1")
    before = detail_of(reviewer, question_id)
    assert "gsinθ" in before["teaching"]["leak_markers"]

    after = edit(
        reviewer, question_id, edit_body(before, title="用字母表示光滑斜面上的加速度（改）")
    )

    assert after["teaching"]["leak_markers"] == before["teaching"]["leak_markers"]
    db.expire_all()
    stored = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question_id, QuestionVersion.version == 2
        )
    ).teaching_json["leak_markers"]
    assert "gsinθ" in stored


def test_the_solutions_of_a_new_version_start_unreviewed_even_if_nothing_about_them_changed(
    reviewer,
):
    question_id = qid(DRAFT_KEY)
    before = detail_of(reviewer, question_id)

    after = edit(reviewer, question_id, stem_edit(before, "改题干，解法不动"))

    assert [s["reviewed"] for s in after["solutions"]] == [False]


# ---------------------------------------------------------------- 学生那边


def test_a_session_that_started_before_the_edit_is_still_judged_by_the_old_version(
    reviewer, new_reviewer, onboarded
):
    """学生做到一半，题被下线修改并重新上线：这次作答仍然按开始时的版本判分，新开的会话才用新版本。"""
    key = DRAFT_KEY
    question_id = qid(key)
    publisher = new_reviewer()
    decide(publisher, question_id, "approve")
    decide(publisher, question_id, "publish")
    session, attempt = begin(onboarded, key)  # 开始时是第 1 版，答案是 A

    decide(publisher, question_id, "withdraw", comment="换一种问法")
    before = detail_of(publisher, question_id)
    editor = new_reviewer()
    edit(
        editor,
        question_id,
        edit_body(
            before,
            content={**before["content"], "stem": "函数 $f(x)=|x+1|$ 的单调递减区间是（　）"},
            answer={**before["answer"], "value": ["C"]},
            solutions=[
                {
                    **{k: s[k] for k in ("kind", "steps", "key_points", "conditions", "boundary")},
                    "final_answer": "C",
                }
                for s in before["solutions"]
            ],
        ),
    )
    decide(publisher, question_id, "approve", version=2)
    decide(publisher, question_id, "publish", version=2)

    old = submit(onboarded, attempt["id"], choice("A"))  # 旧会话：按第 1 版，A 是对的
    assert old["evaluation"]["is_correct"] is True
    assert onboarded.data("GET", f"/sessions/{session['id']}")["question_version"] == 1

    _, fresh = begin(onboarded, key)  # 新会话：第 2 版，C 才是对的
    assert submit(onboarded, fresh["id"], choice("A"))["evaluation"]["is_correct"] is False
    shown = onboarded.data("GET", f"/questions/{question_id}")
    assert shown["version"] == 2 and "|x+1|" in shown["content"]["stem"]


def test_a_withdrawn_question_disappears_from_the_students_due_reviews_and_comes_back_when_republished(
    reviewer, new_reviewer, onboarded, clock
):
    key = "math-ineq-min"
    from support.flows import blank, solve

    solve(onboarded, key, blank("5"))  # 答错，安排复测
    clock.advance(days=1)
    assert [r["question_id"] for r in onboarded.data("GET", "/reviews/due")["items"]] == [qid(key)]

    decide(reviewer, qid(key), "withdraw", comment="题干有歧义")
    assert onboarded.data("GET", "/reviews/due")["items"] == []
    assert onboarded.data("GET", "/reviews/due", params={"scope": "all"})["items"] == []

    before = detail_of(reviewer, qid(key))
    edit(new_reviewer(), qid(key), stem_edit(before, before["content"]["stem"] + "（已澄清）"))
    decide(reviewer, qid(key), "approve", version=2)
    decide(reviewer, qid(key), "publish", version=2)

    assert [r["question_id"] for r in onboarded.data("GET", "/reviews/due")["items"]] == [qid(key)]


def test_nothing_in_the_edit_path_gives_students_access_to_drafts(onboarded, reviewer):
    question_id = qid(DRAFT_KEY)
    edit(reviewer, question_id, stem_edit(detail_of(reviewer, question_id), "新题干"))

    onboarded.error("GET", f"/questions/{question_id}", expect=404)
    assert AUTHOR  # 常量被引用，避免静态检查把它当成未使用
