"""内容审核最小流（PRD P0 第 9 条、docs/07 §4、docs/03 P11）。

题目 draft → reviewed → published，可撤回；提交内容的人不能审自己的题；每次决策写审计日志；
学生始终只看得到 published 的题。样题入库时就是 published，这里用 `make_draft` 把它们改回待审状态。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from support.admin import (
    AUTHOR,
    FAST_KEY,
    KEY,
    OTHER_FAST_KEY,
    audit_rows,
    decide,
    make_draft,
)
from support.seeds import ALL_KEYS, DRAFT_IDS, DRAFT_KEYS, qid
from tutor_api.models import Question, QuestionVersion, Solution
from tutor_api.services.content_seed import DRAFT_AUTHOR_KEY, seed_uuid

# ---------------------------------------------------------------- 角色与权限


def test_local_identity_can_be_a_reviewer_or_admin_but_defaults_to_student(client):
    from support.api import ApiClient

    anon = ApiClient(client)

    default = anon.data("POST", "/dev/local-identities", expect=201, auth=False, key=False)
    reviewer = anon.data(
        "POST",
        "/dev/local-identities",
        expect=201,
        auth=False,
        key=False,
        params={"role": "reviewer"},
    )
    admin = anon.data(
        "POST", "/dev/local-identities", expect=201, auth=False, key=False, params={"role": "admin"}
    )

    assert [default["role"], reviewer["role"], admin["role"]] == ["student", "reviewer", "admin"]
    anon.error(
        "POST",
        "/dev/local-identities",
        expect=422,
        auth=False,
        key=False,
        params={"role": "superuser"},
    )


def test_students_and_anonymous_callers_cannot_use_the_admin_operations(anon, onboarded):
    some = qid(KEY)
    calls = [
        ("GET", "/admin/questions", None),
        ("GET", f"/admin/questions/{some}", None),
        ("POST", f"/admin/questions/{some}/review", {"decision": "approve", "expected_version": 1}),
    ]
    for method, path, body in calls:
        anon.error(method, path, expect=401, auth=False, json=body, key=False)
        error = onboarded.error(method, path, expect=403, json=body)
        assert error["code"] == "forbidden", path


def test_the_role_check_comes_before_the_lookup(onboarded):
    """学生分不出"题不存在"和"没有权限"，不能借这个接口探测哪些题是草稿。"""
    error = onboarded.error("GET", f"/admin/questions/{uuid.uuid4()}", expect=403)
    assert error["code"] == "forbidden"


def test_reviewers_cannot_use_the_student_operations(reviewer):
    for path in ("/profile", "/tasks/today", "/progress/summary"):
        assert reviewer.error("GET", path, expect=403)["code"] == "forbidden", path


def test_admin_has_the_same_review_powers_as_a_reviewer(admin, db):
    question_id = make_draft(db)

    state = decide(admin, question_id, "approve")

    assert state["status"] == "reviewed"
    assert state["reviewed_by"] == admin.user_id


# ---------------------------------------------------------------- 队列与详情


def test_queue_lists_every_status_and_counts_them(reviewer, db):
    first = make_draft(db, "math-mono-quadratic")
    second = make_draft(db, "phys-incline-accel")
    decide(reviewer, second, "approve")

    everything = reviewer.data("GET", "/admin/questions", params={"limit": 50})

    assert everything["status_counts"] == {
        "draft": len(DRAFT_KEYS) + 1,  # 种子里的待审样题 + 刚改成草稿的那一道
        "reviewed": 1,
        "published": len(ALL_KEYS) - 2,
        "withdrawn": 0,
    }
    assert {item["id"] for item in everything["items"]} == {qid(k) for k in ALL_KEYS | DRAFT_KEYS}
    drafts = reviewer.data("GET", "/admin/questions", params={"status": "draft", "limit": 50})
    assert {item["id"] for item in drafts["items"]} == {first} | DRAFT_IDS
    by_id = {item["id"]: item for item in drafts["items"]}
    assert by_id[first]["created_by"] == AUTHOR
    assert {by_id[i]["created_by"] for i in DRAFT_IDS} == {seed_uuid("author", DRAFT_AUTHOR_KEY)}
    assert all(item["source"]["is_engineering_sample"] for item in drafts["items"])
    # 数量不受 status 筛选影响，页签上的数字不会随选中的页签变化
    assert drafts["status_counts"] == everything["status_counts"]


def test_queue_filters_by_subject_and_source_and_pages_through_everything(reviewer):
    math = reviewer.data("GET", "/admin/questions", params={"subject": "math", "limit": 50})
    assert {item["subject"] for item in math["items"]} == {"math"}
    assert sum(math["status_counts"].values()) == len(math["items"])

    empty = reviewer.data("GET", "/admin/questions", params={"source_category": "gaokao_real"})
    assert empty["items"] == [] and empty["next_cursor"] is None

    seen: list[str] = []
    cursor = None
    while True:
        page = reviewer.data(
            "GET", "/admin/questions", params={"limit": 5, **({"cursor": cursor} if cursor else {})}
        )
        assert len(page["items"]) <= 5
        seen += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == len(ALL_KEYS) + len(DRAFT_KEYS)


def test_queue_rejects_bad_filters_and_cursors(reviewer):
    assert reviewer.error("GET", "/admin/questions", expect=422, params={"status": "nope"})
    assert reviewer.error("GET", "/admin/questions", expect=422, params={"limit": 0})
    error = reviewer.error("GET", "/admin/questions", expect=400, params={"cursor": "###"})
    assert error["code"] == "invalid_cursor"


def test_detail_shows_everything_a_reviewer_needs(reviewer, db):
    question_id = make_draft(db, FAST_KEY)

    detail = reviewer.data("GET", f"/admin/questions/{question_id}")

    assert detail["status"] == "draft" and detail["version"] == 1
    assert detail["created_by"] == AUTHOR and detail["reviewed_by"] is None
    assert detail["answer"]["value"] == {"b1": "5"}
    assert detail["answer"]["equivalence_rules"]["b1"]["type"] == "numeric"
    assert (
        detail["teaching"]["hints"]
        and detail["teaching"]["visual"]["template_id"] == "force_diagram"
    )
    kinds = {s["kind"]: s for s in detail["solutions"]}
    assert set(kinds) == {"standard", "fast"}
    assert kinds["fast"]["conditions"] and kinds["fast"]["boundary"]
    assert kinds["standard"]["conditions"] is None
    assert not kinds["standard"]["reviewed"] and not kinds["fast"]["reviewed"]
    assert [k["code"] for k in detail["knowledge"]] == ["phys.force.analysis", "phys.newton.second"]
    assert detail["content"]["blanks"][0]["key"] == "b1"
    assert detail["versions"] == [
        {"version": 1, "created_by": None, "created_at": detail["versions"][0]["created_at"]}
    ]
    assert detail["history"] == []
    assert detail["check_problems"] == []


def test_detail_of_a_choice_question_has_option_analysis_and_region_tags(reviewer):
    detail = reviewer.data("GET", f"/admin/questions/{qid(KEY)}")

    assert detail["answer"]["value"] == ["B"]
    assert set(detail["teaching"]["option_analysis"]) == {"A", "B", "C", "D"}
    assert [(t["recommended_region_code"], t["review_status"]) for t in detail["region_tags"]] == [
        ("CN-51", "approved")
    ]
    assert detail["status"] == "published" and detail["published_at"] is not None


def test_every_seeded_question_passes_the_program_checks(reviewer):
    """入库用的校验和审核后台用的是同一套：样题（包括待审的）不应该有任何问题。"""
    for key in sorted(ALL_KEYS | DRAFT_KEYS):
        detail = reviewer.data("GET", f"/admin/questions/{qid(key)}")
        assert detail["check_problems"] == [], key


def test_detail_of_an_unknown_question_is_404(reviewer):
    assert (
        reviewer.error("GET", f"/admin/questions/{uuid.uuid4()}", expect=404)["code"] == "not_found"
    )
    reviewer.error("GET", "/admin/questions/not-a-uuid", expect=422)


# ---------------------------------------------------------------- 状态流转


def test_full_path_draft_to_reviewed_to_published_and_students_see_it_only_then(
    reviewer, onboarded, db
):
    question_id = make_draft(db)
    onboarded.error("GET", f"/questions/{question_id}", expect=404)
    assert question_id not in [q["id"] for q in onboarded.data("GET", "/questions")["items"]]

    reviewed = decide(reviewer, question_id, "approve")
    assert (reviewed["status"], reviewed["reviewed_by"]) == ("reviewed", reviewer.user_id)
    onboarded.error("GET", f"/questions/{question_id}", expect=404)  # 二审通过也还没上线

    published = decide(reviewer, question_id, "publish")
    assert published["status"] == "published" and published["reviewed_by"] == reviewer.user_id
    assert onboarded.data("GET", f"/questions/{question_id}")["id"] == question_id

    detail = reviewer.data("GET", f"/admin/questions/{question_id}")
    assert detail["published_at"] is not None
    assert [(h["action"], h["from_status"], h["to_status"]) for h in detail["history"]] == [
        ("approve", "draft", "reviewed"),
        ("publish", "reviewed", "published"),
    ]


def test_withdraw_takes_the_question_away_from_students_at_once_and_is_final(
    reviewer, onboarded, new_reviewer
):
    assert onboarded.data("GET", f"/questions/{qid(KEY)}")["id"] == qid(KEY)

    state = decide(reviewer, qid(KEY), "withdraw", comment="选项 C 的分析有误")

    assert state["status"] == "withdrawn"
    onboarded.error("GET", f"/questions/{qid(KEY)}", expect=404)
    assert qid(KEY) not in [q["id"] for q in onboarded.data("GET", "/questions")["items"]]
    assert qid(KEY) not in [
        t["question_id"] for t in onboarded.data("GET", "/tasks/today")["items"]
    ]
    for decision in ("approve", "reject", "publish", "withdraw"):
        error = decide(new_reviewer(), qid(KEY), decision, comment="再试一次", expect=409)
        assert error["code"] == "invalid_transition", decision


def test_reject_sends_a_draft_or_a_reviewed_question_back_and_revokes_the_marks(reviewer, db):
    question_id = make_draft(db, FAST_KEY)
    decide(reviewer, question_id, "approve", solution_kinds=["standard", "fast"])
    reviewed = {
        s.kind: s.reviewed
        for s in db.scalars(select(Solution).where(Solution.question_id == question_id))
    }
    assert reviewed == {"standard": True, "fast": True}

    state = decide(reviewer, question_id, "reject", comment="第二步缺少前提")

    assert (state["status"], state["reviewed_by"]) == ("draft", None)
    db.expire_all()
    for solution in db.scalars(select(Solution).where(Solution.question_id == question_id)):
        assert solution.reviewed is False and solution.reviewed_by is None
    # 草稿本身也可以直接退回
    again = decide(reviewer, question_id, "reject", comment="还是不行")
    assert again["status"] == "draft"


def test_reject_and_withdraw_need_a_comment(reviewer, db):
    question_id = make_draft(db)
    for blank in (None, "", "   "):
        extra = {} if blank is None else {"comment": blank}
        error = decide(reviewer, question_id, "reject", expect=422, **extra)
        assert error["code"] == "comment_required"
    decide(reviewer, qid("math-ineq-min"), "withdraw", comment="答案有争议")
    reviewer.error(
        "POST",
        f"/admin/questions/{qid('math-ineq-rect')}/review",
        expect=422,
        json={"decision": "withdraw", "expected_version": 1},
    )


@pytest.mark.parametrize(
    ("status_before", "decision"),
    [
        ("published", "approve"),
        ("published", "publish"),
        ("published", "reject"),
        ("draft", "publish"),
        ("draft", "withdraw"),
        ("reviewed", "approve"),
        ("reviewed", "withdraw"),
    ],
)
def test_decisions_the_status_does_not_allow_are_409(reviewer, db, status_before, decision):
    if status_before == "published":
        question_id = qid(KEY)
    else:
        question_id = make_draft(db)
        if status_before == "reviewed":
            decide(reviewer, question_id, "approve")

    error = decide(reviewer, question_id, decision, comment="随便写一句", expect=409)

    assert error["code"] == "invalid_transition"
    assert status_before in error["message"]


def test_stale_version_is_a_conflict_so_nobody_approves_what_they_did_not_see(reviewer, db):
    question_id = make_draft(db)

    error = decide(reviewer, question_id, "approve", version=2, expect=409)

    assert error["code"] == "version_conflict"
    assert error["details"]["current_version"] == 1
    db.expire_all()
    assert db.get(Question, question_id).status == "draft"


def test_unknown_question_is_404(reviewer):
    error = decide(reviewer, str(uuid.uuid4()), "approve", expect=404)
    assert error["code"] == "not_found"


# ---------------------------------------------------------------- 二审要独立


def test_the_author_cannot_approve_or_publish_their_own_question(reviewer, db):
    question_id = make_draft(db, created_by=reviewer.user_id)

    error = decide(reviewer, question_id, "approve", expect=403)
    assert error["code"] == "self_review_forbidden"

    # 别人审过之后，作者也不能自己点上线
    other = str(uuid.uuid4())
    question = db.get(Question, question_id)
    question.status, question.reviewed_by = "reviewed", other
    db.commit()
    error = decide(reviewer, question_id, "publish", expect=403)
    assert error["code"] == "self_review_forbidden"
    db.expire_all()
    assert db.get(Question, question_id).status == "reviewed"


def test_a_different_reviewer_can_take_over_the_same_question(reviewer, new_reviewer, db):
    question_id = make_draft(db, created_by=reviewer.user_id)
    second = new_reviewer()

    decide(second, question_id, "approve")
    state = decide(second, question_id, "publish")

    assert (state["status"], state["reviewed_by"]) == ("published", second.user_id)


def test_two_reviewers_cannot_both_approve_the_same_draft(reviewer, new_reviewer, db):
    question_id = make_draft(db)
    decide(reviewer, question_id, "approve")

    error = decide(new_reviewer(), question_id, "approve", expect=409)

    assert error["code"] == "invalid_transition"


# ---------------------------------------------------------------- 程序校验把关


def test_a_draft_that_fails_the_program_checks_cannot_be_approved(reviewer, db):
    question_id = make_draft(db)
    version = db.scalar(select(QuestionVersion).where(QuestionVersion.question_id == question_id))
    version.answer_json = {**version.answer_json, "value": ["Z"]}
    db.commit()

    detail = reviewer.data("GET", f"/admin/questions/{question_id}")
    assert any("不存在的选项" in problem for problem in detail["check_problems"])

    error = decide(reviewer, question_id, "approve", expect=422)
    assert error["code"] == "content_checks_failed"
    assert any("不存在的选项" in problem for problem in error["details"]["problems"])
    db.expire_all()
    assert db.get(Question, question_id).status == "draft"
    assert audit_rows(db, question_id) == [], "被拒绝的操作不留审批记录"


def test_publish_checks_again_in_case_the_content_changed_after_approval(reviewer, db):
    question_id = make_draft(db)
    decide(reviewer, question_id, "approve")
    version = db.scalar(select(QuestionVersion).where(QuestionVersion.question_id == question_id))
    version.answer_json = {**version.answer_json, "value": ["Z"]}
    db.commit()

    error = decide(reviewer, question_id, "publish", expect=422)

    assert error["code"] == "content_checks_failed"


def test_a_question_cannot_go_live_without_a_confirmed_standard_solution(reviewer, db):
    question_id = make_draft(db)
    decide(reviewer, question_id, "approve")
    for solution in db.scalars(select(Solution).where(Solution.question_id == question_id)):
        solution.reviewed = False
    db.commit()

    error = decide(reviewer, question_id, "publish", expect=422)

    assert error["code"] == "solution_not_confirmed"


def test_approve_must_confirm_the_standard_solution(reviewer, db):
    question_id = make_draft(db, FAST_KEY)

    error = decide(reviewer, question_id, "approve", solution_kinds=["fast"], expect=422)

    assert error["code"] == "solution_not_confirmed"


def test_a_fast_solution_reaches_students_only_if_the_reviewer_confirmed_it(
    reviewer, onboarded, db
):
    question_id = make_draft(db, FAST_KEY)
    decide(reviewer, question_id, "approve")  # 缺省只确认标准解法
    decide(reviewer, question_id, "publish")

    assists = onboarded.data("GET", f"/questions/{question_id}")["assists"]
    assert assists["has_standard_solution"] is True and assists["has_fast_solution"] is False

    both_id = make_draft(db, OTHER_FAST_KEY)
    decide(reviewer, both_id, "approve", solution_kinds=["standard", "fast"])
    decide(reviewer, both_id, "publish")
    assists = onboarded.data("GET", f"/questions/{both_id}")["assists"]
    assert assists["has_standard_solution"] is True and assists["has_fast_solution"] is True


# ---------------------------------------------------------------- 审计与幂等


def test_every_decision_is_audited_with_who_what_and_why(reviewer, db):
    question_id = make_draft(db)
    approved = reviewer.post(
        f"/admin/questions/{question_id}/review",
        json={"decision": "approve", "expected_version": 1, "comment": "解法没问题"},
        headers={"X-Request-Id": "audit-trace-1"},
    )
    assert approved.status_code == 200
    decide(reviewer, question_id, "reject", comment="还是退回吧")

    rows = audit_rows(db, question_id)

    assert [row.action for row in rows] == ["question.review.approve", "question.review.reject"]
    first = rows[0]
    assert first.actor_id == reviewer.user_id and first.request_id == "audit-trace-1"
    assert first.detail_json == {
        "from": "draft",
        "to": "reviewed",
        "version": 1,
        "comment": "解法没问题",
        "solution_kinds": ["standard"],
    }
    assert rows[1].detail_json["comment"] == "还是退回吧"
    history = reviewer.data("GET", f"/admin/questions/{question_id}")["history"]
    assert [(h["action"], h["actor_id"], h["comment"]) for h in history] == [
        ("approve", reviewer.user_id, "解法没问题"),
        ("reject", reviewer.user_id, "还是退回吧"),
    ]


def test_retrying_with_the_same_key_decides_once(reviewer, db):
    question_id = make_draft(db)
    body = {"decision": "approve", "expected_version": 1}
    path = f"/admin/questions/{question_id}/review"

    first = reviewer.post(path, json=body, key="approve-once-0001")
    second = reviewer.post(path, json=body, key="approve-once-0001")

    assert first.status_code == second.status_code == 200
    assert second.headers["idempotency-replayed"] == "true"
    assert second.json() == first.json()
    assert len(audit_rows(db, question_id)) == 1


def test_the_same_key_for_a_different_decision_is_a_conflict(reviewer, db):
    question_id = make_draft(db)
    path = f"/admin/questions/{question_id}/review"
    reviewer.post(path, json={"decision": "approve", "expected_version": 1}, key="shared-key-0001")

    response = reviewer.post(
        path,
        json={"decision": "reject", "expected_version": 1, "comment": "x"},
        key="shared-key-0001",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_conflict"


def test_review_decisions_require_an_idempotency_key(reviewer, db):
    question_id = make_draft(db)

    response = reviewer.post(
        f"/admin/questions/{question_id}/review",
        json={"decision": "approve", "expected_version": 1},
        key=False,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "idempotency_key_required"


def test_students_never_see_drafts_in_any_student_endpoint(onboarded, db):
    drafts = {
        make_draft(db, key)
        for key in ("math-mono-quadratic", "phys-force-analysis", "chem-conservation-co2")
    }

    listed = {q["id"] for q in onboarded.data("GET", "/questions", params={"limit": 50})["items"]}
    planned = {t["question_id"] for t in onboarded.data("GET", "/tasks/today")["items"]}

    assert not drafts & listed and not drafts & planned
    for question_id in drafts:
        onboarded.error("GET", f"/questions/{question_id}", expect=404)
        onboarded.error(
            "POST",
            "/sessions",
            expect=404,
            json={"question_id": question_id, "origin": "practice"},
        )


# ---------------------------------------------------------------- 种子里的待审样题


DRAFT_ANSWERS = {
    "math-abs-decreasing": {"selected_options": ["A"]},
    "phys-friction-uniform": {"blanks": [{"key": "b1", "value": "20 N"}]},
    "chem-electrolyte-identify": {"selected_options": ["B"]},
}


def test_seeded_drafts_are_invisible_to_students_until_they_are_published(onboarded):
    listed = {q["id"] for q in onboarded.data("GET", "/questions", params={"limit": 50})["items"]}
    planned = {t["question_id"] for t in onboarded.data("GET", "/tasks/today")["items"]}

    assert not DRAFT_IDS & listed and not DRAFT_IDS & planned
    for question_id in DRAFT_IDS:
        onboarded.error("GET", f"/questions/{question_id}", expect=404)


def test_seeded_drafts_go_through_review_and_then_work_in_the_student_flow(reviewer, onboarded, db):
    """待审样题不是摆设：审核通过、上线之后，学生能做、能判、提示不泄题。"""
    from support.flows import solve

    for key in sorted(DRAFT_KEYS):
        question_id = qid(key)
        decide(reviewer, question_id, "approve")
        decide(reviewer, question_id, "publish")

        shown = onboarded.data("GET", f"/questions/{question_id}")
        assert shown["assists"]["has_standard_solution"] is True
        assert shown["assists"]["hint_levels"] >= 2
        assert shown["source"]["is_engineering_sample"] is True

        _, _, result = solve(onboarded, key, DRAFT_ANSWERS[key], origin="practice")
        evaluation = result["evaluation"]
        assert (evaluation["state"], evaluation["outcome"]) == ("verified", "correct"), key
        assert evaluation["is_correct"] is True and evaluation["independent"] is True, key
