"""家长周报（PRD P0 第 8 条、US-06、docs/03 P10）：只给已授权的家长，只有汇总。

口径与学情页一致（`progress_service`）：只有确定判定的作答进比例；独立正确率和辅助正确率分开；
样本不足 `progress_min_samples`（默认 5）只给计数。解答题不自动评分，只数提交了几份。
测试时钟是 2026-11-10 周二 08:00 UTC（北京时间 16:00），所以当前这一周是 2026-11-09（周一）到 11-15（周日）。
"""

from __future__ import annotations

import json
import uuid

import pytest

from support.contract import load_openapi
from support.flows import CORRECT, INK, WRITTEN, WRONG, begin, parts, solve, submit, tutor
from support.parents import FIVE, authorize, do_week, links_of, new_identity, revoke, weekly, z
from support.seeds import qid
from tutor_api.services.weekly_service import trend_of
from tutor_api.services.weekly_snapshots import generate_due_snapshots

WEEK = "2026-11-09"
WEEK_END = "2026-11-15"


def stat(numerator: int, denominator: int, rate: float | None = None) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": rate,
        "insufficient_data": rate is None,
    }


def _busy_week(student) -> None:
    """五份独立作答（三对两错）、一份看过提示的作答、一份解答题。"""
    solve(student, "math-mono-quadratic")
    solve(student, "math-ineq-min")
    solve(student, "phys-newton2-force")
    solve(student, "chem-conservation-co2", WRONG["chem-conservation-co2"])
    solve(student, "math-mono-judge", WRONG["math-mono-judge"])
    session, attempt = begin(student, "chem-conservation-h2")
    tutor(student, session["id"], "request_hint")
    submit(student, attempt["id"], {"selected_options": ["B"]})
    solve(student, "math-quadratic-param-written", WRITTEN["math-quadratic-param-written"])


@pytest.fixture
def linked(onboarded, parent):
    authorize(onboarded, parent)
    return onboarded, parent


# ---------------------------------------------------------------- 内容


def test_a_linked_parent_sees_this_weeks_work_as_a_summary(linked, clock):
    student, parent = linked
    _busy_week(student)

    report = weekly(parent, student.user_id)

    assert report["student_id"] == student.user_id and report["student_display_name"] is None
    assert (report["week_start"], report["week_end"], report["is_complete"]) == (
        WEEK,
        WEEK_END,
        False,
    )
    assert report["generated_at"] == z(clock.now())
    assert report["min_samples"] == 5
    assert (report["sessions_count"], report["attempts_count"], report["active_days"]) == (7, 7, 1)
    assert report["independent"] == stat(3, 5, 0.6)
    assert report["assisted"] == stat(1, 1)
    assert report["hint_dependency"] == stat(1, 6, 0.1667)
    assert report["retest_success"] == stat(0, 0)
    assert report["written_attempts"] == 1
    by_subject = {bucket["key"]: bucket for bucket in report["by_subject"]}
    assert list(by_subject) == ["math", "physics", "chemistry"]
    assert by_subject["math"]["independent"] == stat(2, 3)
    assert by_subject["physics"]["independent"] == stat(1, 1)
    assert by_subject["chemistry"]["independent"] == stat(0, 1)
    assert by_subject["chemistry"]["assisted"] == stat(1, 1)
    assert "不是官方成绩" in report["disclaimer"]


def test_few_attempts_give_counts_but_no_percentage(linked):
    student, parent = linked
    do_week(student, correct=2, keys=["math-mono-quadratic", "math-ineq-min", "phys-newton2-force"])

    report = weekly(parent, student.user_id)

    assert report["independent"] == stat(2, 3), "样本不足：只给计数，比例是 null"
    assert report["independent_trend"] == "unknown"


def test_a_week_without_any_work_is_an_empty_report_not_an_error(linked):
    student, parent = linked

    report = weekly(parent, student.user_id)

    assert (report["sessions_count"], report["attempts_count"], report["active_days"]) == (0, 0, 0)
    assert report["written_attempts"] == 0
    for name in ("independent", "assisted", "hint_dependency", "retest_success"):
        assert report[name] == stat(0, 0), name
    assert report["independent_trend"] == "unknown"
    assert report["previous_week"]["attempts_count"] == 0
    assert [b["independent"] for b in report["by_subject"]] == [stat(0, 0)] * 3


def test_written_work_is_counted_but_never_enters_a_rate(linked):
    student, parent = linked
    solve(student, "math-quadratic-param-written", WRITTEN["math-quadratic-param-written"])
    solve(student, "phys-pull-friction-written", WRITTEN["phys-pull-friction-written"])

    report = weekly(parent, student.user_id)

    assert (report["attempts_count"], report["written_attempts"]) == (2, 2)
    assert report["independent"] == stat(0, 0) and report["assisted"] == stat(0, 0)
    assert report["hint_dependency"] == stat(0, 0)


def test_retests_have_their_own_success_rate(linked, clock):
    student, parent = linked
    keys = FIVE
    for key in keys:
        solve(student, key, WRONG[key])  # 都答错：各安排一次复测
    clock.advance(days=1)
    due = student.data("GET", "/reviews/due")["items"]
    assert len(due) == 5
    for item in due:
        key = next(k for k in keys if qid(k) == item["question_id"])
        session = student.data(
            "POST",
            "/sessions",
            expect=201,
            json={
                "question_id": item["question_id"],
                "origin": "review",
                "review_item_id": item["id"],
            },
        )
        attempt = student.data("POST", "/attempts", expect=201, json={"session_id": session["id"]})
        submit(student, attempt["id"], CORRECT[key])

    report = weekly(parent, student.user_id)

    assert report["retest_success"] == stat(5, 5, 1.0)


def test_the_students_own_name_is_shown_when_they_set_one(linked):
    student, parent = linked
    student.save_profile(json={
            "region_code": "CN-51",
            "grade": "G12",
            "subjects": ["math"],
            "display_name": "小明",
        })

    assert weekly(parent, student.user_id)["student_display_name"] == "小明"


# ---------------------------------------------------------------- 哪一周


def test_a_week_runs_monday_to_sunday_in_the_configured_timezone(linked, clock):
    student, parent = linked
    solve(student, "math-mono-quadratic")  # 周二
    clock.advance(days=5, hours=7, minutes=30)  # 周日 23:30（北京时间）
    solve(student, "math-ineq-min")
    clock.advance(hours=1)  # 周一 00:30（北京时间）；这时 UTC 日期还是周日
    solve(student, "phys-newton2-force")

    current = weekly(parent, student.user_id)
    last = weekly(parent, student.user_id, week_start=WEEK)

    assert current["week_start"] == "2026-11-16", "北京时间已经是新的一周"
    assert current["attempts_count"] == 1
    assert current["previous_week"] == {
        "week_start": WEEK,
        "attempts_count": 2,
        "independent": stat(2, 2),
    }
    assert last["attempts_count"] == 2 and last["is_complete"] is True
    assert last["active_days"] == 2, "周二和周日"


def test_the_timezone_offset_is_a_setting(custom_app, clock):
    raw = custom_app(report_utc_offset_minutes=0)  # 按 UTC 划分
    student, parent = new_identity(raw), new_identity(raw, "parent")
    authorize(student, parent)
    clock.advance(days=5, hours=8, minutes=30)  # UTC 周日 16:30

    solve(student, "math-mono-quadratic")

    report = weekly(parent, student.user_id)
    assert report["week_start"] == WEEK, "UTC 的周日 16:30 还在这一周"
    assert report["attempts_count"] == 1


def test_an_earlier_week_can_be_asked_for_by_its_monday(linked, clock):
    student, parent = linked
    solve(student, "math-mono-quadratic")
    clock.advance(days=7)

    earlier = weekly(parent, student.user_id, week_start=WEEK)
    this_week = weekly(parent, student.user_id)

    assert earlier["attempts_count"] == 1 and earlier["is_complete"] is True
    assert this_week["week_start"] == "2026-11-16" and this_week["attempts_count"] == 0
    assert this_week["previous_week"]["attempts_count"] == 1


def test_a_long_ago_week_is_just_empty(linked):
    student, parent = linked

    report = weekly(parent, student.user_id, week_start="2020-01-06")

    assert report["attempts_count"] == 0 and report["is_complete"] is True


@pytest.mark.parametrize(
    ("week_start", "problem"),
    [
        ("2026-11-10", "周一"),  # 周二
        ("2026-11-15", "周一"),  # 周日
        ("2026-11-16", "还没有开始"),  # 下周一
        ("2027-01-04", "还没有开始"),
        ("nope", None),
        ("2026-13-01", None),
    ],
)
def test_week_start_must_be_a_monday_and_not_in_the_future(linked, week_start, problem):
    student, parent = linked

    error = parent.error(
        "GET",
        f"/parents/students/{student.user_id}/weekly",
        expect=422,
        params={"week_start": week_start},
    )

    assert error["code"] == "validation_error"
    first = error["details"]["errors"][0]
    assert "week_start" in first["field"]
    if problem:
        assert problem in first["message"]


# ---------------------------------------------------------------- 趋势


@pytest.mark.parametrize(
    ("previous", "current", "trend"),
    [(2, 4, "up"), (4, 2, "down"), (3, 3, "flat"), (0, 5, "up"), (5, 0, "down")],
)
def test_the_trend_compares_independent_accuracy_with_the_week_before(
    linked, clock, previous, current, trend
):
    student, parent = linked
    do_week(student, correct=previous)
    clock.advance(days=7)
    do_week(student, correct=current)

    report = weekly(parent, student.user_id)

    assert report["independent"]["rate"] == current / 5
    assert report["previous_week"]["independent"]["rate"] == previous / 5
    assert report["independent_trend"] == trend


def test_the_trend_is_unknown_when_either_week_has_too_little_data(linked, clock):
    student, parent = linked
    do_week(student, correct=1, keys=["math-mono-quadratic", "math-ineq-min"])  # 上周只有 2 份
    clock.advance(days=7)
    do_week(student, correct=5)

    report = weekly(parent, student.user_id)

    assert report["independent"]["rate"] == 1.0
    assert report["previous_week"]["independent"]["rate"] is None
    assert report["independent_trend"] == "unknown"


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (0.60, 0.64, "flat"),
        (0.60, 0.65, "up"),  # 恰好 5 个百分点算变了
        (0.65, 0.60, "down"),
        (0.60, 0.56, "flat"),
        (0.0, 1.0, "up"),
        (None, 0.5, "unknown"),
        (0.5, None, "unknown"),
        (None, None, "unknown"),
    ],
)
def test_trend_of(previous, current, expected):
    assert trend_of(previous, current) == expected


# ---------------------------------------------------------------- 只有汇总：没有题目、作答、草稿


def test_the_report_has_exactly_the_contract_fields_and_nothing_about_questions(linked):
    student, parent = linked
    secret = "只有学生自己知道的演算内容"
    session, attempt = begin(student, "math-quadratic-param-written")
    student.data(
        "PUT",
        f"/attempts/{attempt['id']}/draft",
        json={"base_revision": 0, "answer": parts({"1": secret}), "strokes": INK},
    )
    submit(student, attempt["id"], parts({"1": secret}))
    tutor(student, session["id"], "request_standard")
    solve(student, "math-mono-quadratic")
    titles = [
        student.data("GET", f"/questions/{qid(key)}")["title"]
        for key in ("math-quadratic-param-written", "math-mono-quadratic")
    ]

    report = weekly(parent, student.user_id)

    contract = load_openapi()["components"]["schemas"]["ParentWeekly"]["properties"]
    assert set(report) == set(contract)
    text = json.dumps(report, ensure_ascii=False)
    assert secret not in text
    for key in ("math-quadratic-param-written", "math-mono-quadratic"):
        assert qid(key) not in text
    for title in titles:
        assert title not in text
    for leaked in ("strokes", "points", "final_answer", "hints", "title", "question"):
        assert leaked not in text, leaked


def test_the_students_list_shows_only_who_and_since_when(linked):
    student, parent = linked

    (item,) = parent.data("GET", "/parents/students")["items"]

    assert set(item) == {"student_id", "display_name", "linked_at"}


# ---------------------------------------------------------------- 谁能看


def test_an_unlinked_parent_gets_the_same_404_as_for_a_student_that_does_not_exist(
    onboarded, parent
):
    real = parent.error("GET", f"/parents/students/{onboarded.user_id}/weekly", expect=404)
    unknown = parent.error("GET", f"/parents/students/{uuid.uuid4()}/weekly", expect=404)

    assert real["code"] == unknown["code"] == "not_found"
    assert real["message"] == unknown["message"]
    assert real["details"] == unknown["details"]


def test_a_parent_only_sees_the_students_they_were_authorized_for(linked, new_student, new_parent):
    student, parent = linked
    other_student, other_parent = new_student(), new_parent()
    authorize(other_student, other_parent)

    assert parent.error("GET", f"/parents/students/{other_student.user_id}/weekly", expect=404)
    assert other_parent.error("GET", f"/parents/students/{student.user_id}/weekly", expect=404)
    assert weekly(other_parent, other_student.user_id)["student_id"] == other_student.user_id


def test_the_week_start_is_not_checked_before_authorization(onboarded, parent):
    """没授权的家长连"这个日期合不合法"都问不出来：先 404，不是 422。"""
    error = parent.error(
        "GET",
        f"/parents/students/{onboarded.user_id}/weekly",
        expect=404,
        params={"week_start": "2026-11-10"},
    )

    assert error["code"] == "not_found"


def test_a_revoked_parent_loses_every_week_at_once(linked, clock, app, settings):
    student, parent = linked
    solve(student, "math-mono-quadratic")
    clock.advance(days=7)
    (entry,) = links_of(student)["links"]
    assert weekly(parent, student.user_id, week_start=WEEK)["attempts_count"] == 1
    assert generate_due_snapshots(app.state.session_factory, settings, clock.now()) == 1
    snapshot_path = f"/parents/students/{student.user_id}/weekly-snapshots/{WEEK}"
    snapshot = parent.request("GET", snapshot_path)
    assert snapshot.status_code == 200
    assert snapshot.headers["Cache-Control"] == "no-store"
    assert snapshot.json()["data"]["report"]["attempts_count"] == 1

    revoke(student, entry["id"])

    for params in ({}, {"week_start": WEEK}):
        parent.error(
            "GET", f"/parents/students/{student.user_id}/weekly", expect=404, params=params or None
        )
    for params in (None, {"revision": 1}):
        response = parent.request("GET", snapshot_path, params=params)
        assert response.status_code == 404
        assert response.headers["Cache-Control"] == "no-store"


def test_new_work_shows_up_without_the_parent_doing_anything(linked):
    student, parent = linked
    assert weekly(parent, student.user_id)["attempts_count"] == 0

    solve(student, "math-mono-quadratic")

    assert weekly(parent, student.user_id)["attempts_count"] == 1


def test_work_before_the_authorization_is_part_of_the_report(onboarded, parent):
    """授权管的是"从现在起能看汇总"，不是"只看授权之后做的"：一周的汇总不拆成授权前后两半。"""
    solve(onboarded, "math-mono-quadratic")

    authorize(onboarded, parent)

    assert weekly(parent, onboarded.user_id)["attempts_count"] == 1


def test_a_week_is_aggregated_per_student(linked, new_student, clock):
    student, parent = linked
    other = new_student()
    other.save_profile(json={"region_code": "CN-51", "grade": "G12", "subjects": ["math"]})
    solve(other, "math-mono-quadratic")
    solve(student, "math-ineq-min")
    solve(student, "phys-newton2-force")

    assert weekly(parent, student.user_id)["attempts_count"] == 2


def test_the_week_boundary_is_exclusive_at_the_next_monday(linked, clock, app, settings):
    student, parent = linked
    clock.advance(days=5, hours=7, minutes=59, seconds=59)  # 周日 23:59:59（北京时间）
    solve(student, "math-mono-quadratic")
    clock.advance(seconds=1)  # 周一 00:00:00（北京时间）
    solve(student, "math-ineq-min")

    assert weekly(parent, student.user_id, week_start=WEEK)["attempts_count"] == 1
    assert weekly(parent, student.user_id, week_start="2026-11-16")["attempts_count"] == 1

    clock.advance(hours=7)
    assert generate_due_snapshots(app.state.session_factory, settings, clock.now()) == 1
    path = f"/parents/students/{student.user_id}/weekly-snapshots"
    first = parent.data("GET", f"{path}/{WEEK}")["report"]
    assert first["attempts_count"] == 1
    assert first["independent"] == stat(1, 1)
    assert first["assisted"] == stat(0, 0)

    clock.advance(days=7)
    assert generate_due_snapshots(app.state.session_factory, settings, clock.now()) == 1
    second = parent.data("GET", f"{path}/2026-11-16")["report"]
    assert second["attempts_count"] == 1
    assert second["previous_week"]["attempts_count"] == 1
