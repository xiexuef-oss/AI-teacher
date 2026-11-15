"""今日任务（PRD P0 第 2 条、US-01）。`onboarded` 是四川高三学生，三科全选，时钟 2026-11-10。"""

from __future__ import annotations

from sqlalchemy import update

from support.flows import begin, blank, choice, solve, submit, tutor
from support.seeds import CHONGQING_TAGGED, GENERAL_KEYS, KEY_BY_ID, SICHUAN_TAGGED


def _today(student) -> dict:
    return student.data("GET", "/tasks/today")


def _tasks(student) -> list[dict]:
    return _today(student)["items"]


def _summary(student) -> list[tuple[str, str]]:
    return [(task["kind"], KEY_BY_ID[task["question_id"]]) for task in _tasks(student)]


# ---------------------------------------------------------------- 首次使用（US-01）


def test_new_student_gets_one_starter_question_per_selected_subject(onboarded):
    today = _today(onboarded)

    assert today["date"] == "2026-11-10"
    assert _summary(onboarded) == [
        ("new_topic", "math-mono-quadratic"),
        ("new_topic", "phys-force-analysis"),
        ("new_topic", "chem-conservation-co2"),
    ]
    first = today["items"][0]
    assert first["subject"] == "math"
    assert first["title"] and "还没有学习记录" in first["reason"]
    assert first["review_item_id"] is None
    assert first["estimated_minutes"] >= 1
    assert first["applicability"]["scope"] == "region", "地区适用题优先"
    assert today["items"][2]["applicability"]["label"] == "全国通用基础题"


def test_student_who_has_not_configured_anything_can_still_start(student):
    """US-01：无配置也能直接开始；这时只用通用题，三科都给。"""
    tasks = _tasks(student)

    assert [task["subject"] for task in tasks] == ["math", "physics", "chemistry"]
    assert {KEY_BY_ID[task["question_id"]] for task in tasks} <= GENERAL_KEYS
    assert {task["kind"] for task in tasks} == {"new_topic"}


def test_tasks_follow_the_selected_subjects(student):
    student.data(
        "PUT", "/profile", json={"region_code": "CN-51", "grade": "G12", "subjects": ["chemistry"]}
    )
    assert [task["subject"] for task in _tasks(student)] == ["chemistry"]


def test_switching_region_changes_the_recommendations(onboarded):
    """docs/09 验收：四川、重庆各有独立配置，切换后训练推荐可变化。"""
    sichuan = {key for _, key in _summary(onboarded)}

    onboarded.data(
        "PUT",
        "/profile",
        json={"region_code": "CN-50", "grade": "G12", "subjects": ["math", "physics", "chemistry"]},
    )
    chongqing = _summary(onboarded)

    assert chongqing == [
        ("new_topic", "math-ineq-rect"),
        ("new_topic", "phys-tape-accel"),
        ("new_topic", "chem-lab-operation"),
    ]
    assert not sichuan & {key for _, key in chongqing}
    assert {key for _, key in chongqing} <= CHONGQING_TAGGED


def test_starter_never_uses_variants_or_questions_already_attempted(onboarded):
    solve(onboarded, "math-mono-quadratic")

    summary = _summary(onboarded)

    assert ("new_topic", "math-mono-quadratic") not in summary
    new_math = [key for kind, key in summary if kind == "new_topic" and key.startswith("math")]
    assert new_math and all(not key.endswith("-v1") for key in new_math)


# ---------------------------------------------------------------- 复习旧错题与复测


def test_due_mistake_comes_first_as_review_task(onboarded, clock):
    _, _, result = solve(onboarded, "math-ineq-min", blank("5"))
    assert ("review_mistake", "math-ineq-min") not in _summary(onboarded), "还没到期"

    clock.advance(days=1)
    first = _tasks(onboarded)[0]

    assert (first["kind"], KEY_BY_ID[first["question_id"]]) == ("review_mistake", "math-ineq-min")
    assert first["review_item_id"] == result["review_item"]["id"]
    assert "不看提示" in first["reason"]
    assert _today(onboarded)["date"] == "2026-11-11"


def test_later_rounds_are_labelled_as_retest(onboarded, clock):
    _, _, result = solve(onboarded, "math-ineq-min", blank("5"))
    item = result["review_item"]
    clock.advance(days=1)
    _, attempt = begin(onboarded, "math-ineq-min", origin="review", review_item_id=item["id"])
    submit(onboarded, attempt["id"], blank("4"))
    onboarded.data("POST", f"/reviews/{item['id']}/complete", json={"attempt_id": attempt["id"]})
    assert "math-ineq-min" not in {key for _, key in _summary(onboarded)}

    clock.advance(days=3)

    assert _summary(onboarded)[0] == ("retest", "math-ineq-min")


def test_due_reviews_are_shown_even_for_unselected_subjects(student, clock):
    student.data(
        "PUT",
        "/profile",
        json={"region_code": "CN-51", "grade": "G12", "subjects": ["math", "physics"]},
    )
    solve(student, "phys-newton2-force", choice("D"))
    student.data(
        "PUT", "/profile", json={"region_code": "CN-51", "grade": "G12", "subjects": ["math"]}
    )
    clock.advance(days=1)

    summary = _summary(student)

    assert summary[0] == ("review_mistake", "phys-newton2-force")
    assert {
        KEY_BY_ID[t["question_id"]][:4] for t in _tasks(student) if t["kind"] == "new_topic"
    } == {"math"}


# ---------------------------------------------------------------- 变式与薄弱点


def test_variant_is_offered_after_working_on_the_base_question(onboarded):
    solve(onboarded, "math-mono-quadratic")

    assert ("variant", "math-mono-quadratic-v1") in _summary(onboarded)

    solve(onboarded, "math-mono-quadratic-v1", blank("(-∞,2]"), origin="variant")
    assert ("variant", "math-mono-quadratic-v1") not in _summary(onboarded)


def test_a_task_that_was_opened_but_not_finished_stays_on_the_list(onboarded):
    """点开任务、没做完就离开（接电话、切去别的应用）：任务不能凭空消失（浏览器联调发现过）。"""
    before = _tasks(onboarded)
    key = KEY_BY_ID[before[1]["question_id"]]

    session, attempt = begin(onboarded, key, origin="task")
    tutor(onboarded, session["id"], "request_hint")  # 看过分层提示也还没做完

    assert _tasks(onboarded) == before, "开了会话、看了提示、但没有提交，任务应该原样还在"
    submit(onboarded, attempt["id"], choice("A"))
    assert key not in {KEY_BY_ID[t["question_id"]] for t in _tasks(onboarded)}, "提交之后才算做过"


def test_a_variant_that_was_opened_but_not_finished_is_still_offered(onboarded):
    solve(onboarded, "math-mono-quadratic")
    begin(onboarded, "math-mono-quadratic-v1", origin="variant")

    assert ("variant", "math-mono-quadratic-v1") in _summary(onboarded)


def test_a_question_whose_solution_was_already_viewed_is_not_offered_as_new_again(onboarded):
    """放弃独立作答去看了解析：答案已经看过，不能再当"新题"推给他。"""
    session, _ = begin(onboarded, "math-mono-quadratic", origin="task")
    tutor(onboarded, session["id"], "request_standard", confirm_end_independent=True)

    assert ("new_topic", "math-mono-quadratic") not in _summary(onboarded)


def test_variant_of_an_untouched_base_question_is_not_offered(onboarded):
    assert "variant" not in {kind for kind, _ in _summary(onboarded)}


def test_weak_point_recommends_another_question_on_the_same_knowledge(onboarded):
    solve(onboarded, "math-ineq-min", blank("5"))

    weak = [task for task in _tasks(onboarded) if task["kind"] == "weak_point"]

    (task,) = weak
    assert KEY_BY_ID[task["question_id"]] == "math-ineq-product-v1"
    assert "基本不等式" in task["title"] and "基本不等式" in task["reason"]


def test_weak_point_clears_after_an_independent_correct_answer_on_it(onboarded):
    solve(onboarded, "math-ineq-min", blank("5"))
    solve(onboarded, "math-ineq-product-v1", blank("16"))

    assert "weak_point" not in {kind for kind, _ in _summary(onboarded)}


def test_assisted_success_does_not_clear_a_weak_point(onboarded):
    solve(onboarded, "phys-incline-accel", blank("10 m/s²"))
    session, attempt = begin(onboarded, "phys-newton2-force")
    tutor(onboarded, session["id"], "request_hint")
    submit(onboarded, attempt["id"], choice("B"))

    weak = [KEY_BY_ID[t["question_id"]] for t in _tasks(onboarded) if t["kind"] == "weak_point"]

    assert weak, "在提示下做对不能说明薄弱点已经补上"


# ---------------------------------------------------------------- 整体约束


def test_task_list_is_bounded_deduplicated_and_only_uses_deliverable_questions(onboarded, clock):
    for key, wrong in (
        ("math-ineq-min", blank("5")),
        ("phys-newton2-force", choice("D")),
        ("chem-conservation-co2", blank("44")),
        ("math-mono-quadratic", choice("A")),
        ("phys-incline-accel", blank("1 m/s²")),
    ):
        solve(onboarded, key, wrong)
    clock.advance(days=1)

    tasks = _tasks(onboarded)

    assert 1 <= len(tasks) <= 5
    questions = [task["question_id"] for task in tasks]
    assert len(set(questions)) == len(questions)
    assert {KEY_BY_ID[q] for q in questions} <= SICHUAN_TAGGED | GENERAL_KEYS
    assert [task["kind"] for task in tasks][:3] == ["review_mistake"] * 3, (
        "到期的复习排在最前，最多 3 项"
    )


def test_task_ids_are_stable_within_a_day_and_change_the_next_day(onboarded, clock):
    today = {task["question_id"]: task["id"] for task in _tasks(onboarded)}
    assert {task["question_id"]: task["id"] for task in _tasks(onboarded)} == today

    clock.advance(days=1)
    tomorrow = {task["question_id"]: task["id"] for task in _tasks(onboarded)}

    assert set(tomorrow) == set(today)
    assert all(tomorrow[q] != today[q] for q in today)


def test_task_ids_differ_between_students(new_student):
    alice, bob = new_student(), new_student()
    assert {t["id"] for t in _tasks(alice)}.isdisjoint({t["id"] for t in _tasks(bob)})


def test_no_content_means_an_empty_list_not_an_error(onboarded, db):
    from tutor_api.models import Question

    db.execute(update(Question).values(status="withdrawn"))
    db.commit()

    assert _today(onboarded) == {"date": "2026-11-10", "items": []}


def test_tasks_require_authentication(anon):
    anon.error("GET", "/tasks/today", expect=401)
