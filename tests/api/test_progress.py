"""学情摘要（PRD §7）。独立正确率与辅助正确率分开；样本不足不给百分比；判不出来的不进分母。"""

from __future__ import annotations

import pytest

from support.flows import begin, blank, choice, new_attempt, solve, submit, tutor

EMPTY = {"numerator": 0, "denominator": 0, "rate": None, "insufficient_data": True}


def _progress(student) -> dict:
    return student.data("GET", "/progress/summary")


def _stat(numerator: int, denominator: int, rate: float | None = None) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": rate,
        "insufficient_data": rate is None,
    }


def _mixed_history(student) -> None:
    """独立：1 对 1 错；辅助：2 对 0 错；另有 1 次判不出来。"""
    solve(student, "math-ineq-min", blank("4"))  # 独立、对
    session, _, _ = solve(student, "phys-newton2-force", choice("D"))  # 独立、错
    retry = new_attempt(student, session["id"])
    submit(student, retry["id"], choice("B"))  # 同一会话重试：辅助、对
    session, attempt = begin(student, "math-mono-quadratic")
    tutor(student, session["id"], "request_hint")
    submit(student, attempt["id"], choice("B"))  # 看过提示：辅助、对
    solve(student, "chem-conservation-co2", blank("大约四克"))  # 判不出来


# ---------------------------------------------------------------- 空数据与样本不足


def test_new_student_sees_insufficient_data_everywhere(onboarded, clock):
    progress = _progress(onboarded)

    assert progress["generated_at"] == "2026-11-10T08:00:00Z"
    assert progress["min_samples"] == 5
    for name in (
        "independent",
        "assisted",
        "hint_dependency",
        "retest_success",
        "variant_transfer",
    ):
        assert progress[name] == EMPTY, name
    assert progress["uncertain_attempts"] == 0
    assert [b["key"] for b in progress["by_subject"]] == ["math", "physics", "chemistry"]
    assert [b["label"] for b in progress["by_subject"]] == ["数学", "物理", "化学"]
    assert [b["key"] for b in progress["by_answer_mode"]] == [
        "single_choice",
        "multiple_choice",
        "fill",
    ]
    assert [b["key"] for b in progress["by_difficulty"]] == ["1", "2", "3", "4", "5"]
    assert all(b["independent"] == EMPTY and b["assisted"] == EMPTY for b in progress["by_subject"])
    assert "不是官方" in progress["disclaimer"]


def test_counts_are_reported_but_rates_are_withheld_below_min_samples(onboarded):
    _mixed_history(onboarded)

    progress = _progress(onboarded)

    assert progress["independent"] == _stat(1, 2), "样本不足时只给计数，不给百分比"
    assert progress["assisted"] == _stat(2, 2)
    assert progress["uncertain_attempts"] == 1


# ---------------------------------------------------------------- 口径


@pytest.fixture
def learner(custom_student, settings):
    """把最小样本数调成 2，便于观察比率。"""
    _, student = custom_student(settings=settings.model_copy(update={"progress_min_samples": 2}))
    return student


def test_independent_and_assisted_accuracy_are_separate(learner):
    _mixed_history(learner)

    progress = _progress(learner)

    assert progress["min_samples"] == 2
    assert progress["independent"] == _stat(1, 2, 0.5)
    assert progress["assisted"] == _stat(2, 2, 1.0)


def test_unverifiable_answers_are_counted_separately_and_never_in_a_denominator(learner):
    solve(learner, "math-ineq-min", blank("四"))
    solve(learner, "phys-incline-accel", blank("500 cm/s²"))

    progress = _progress(learner)

    assert progress["uncertain_attempts"] == 2
    assert progress["independent"] == EMPTY and progress["assisted"] == EMPTY


def test_hint_dependency_looks_at_first_attempts_only(learner):
    _mixed_history(learner)

    # 三次有确定判定的首次作答里，一次用了提示；同一会话的重试不算
    assert _progress(learner)["hint_dependency"] == _stat(1, 3, round(1 / 3, 4))


def test_retest_success_rate_uses_real_retests(learner, clock):
    for key, wrong, right in (
        ("math-ineq-min", blank("5"), blank("4")),
        ("phys-newton2-force", choice("D"), choice("D")),
    ):
        _, _, result = solve(learner, key, wrong)
        item = result["review_item"]
        clock.advance(days=1)
        _, attempt = begin(learner, key, origin="review", review_item_id=item["id"])
        submit(learner, attempt["id"], right)
        learner.data("POST", f"/reviews/{item['id']}/complete", json={"attempt_id": attempt["id"]})

    assert _progress(learner)["retest_success"] == _stat(1, 2, 0.5)


def test_variant_transfer_counts_unaided_first_attempts_on_variants(learner):
    solve(learner, "math-mono-quadratic-v1", blank("(-∞,2]"), origin="variant")
    solve(learner, "math-ineq-product-v1", blank("15"), origin="variant")
    session, attempt = begin(learner, "phys-incline-accel-v1", origin="variant")
    tutor(learner, session["id"], "request_hint")
    submit(learner, attempt["id"], blank("g sinθ"))

    # 三道变式：一道独立做对，一道做错，一道在提示下做对（不算迁移成功）
    assert _progress(learner)["variant_transfer"] == _stat(1, 3, round(1 / 3, 4))


def test_buckets_by_subject_answer_mode_and_difficulty(learner):
    _mixed_history(learner)
    solve(learner, "math-mono-judge", choice("A", "C"))  # 数学、多选、难度 2：独立、对

    progress = _progress(learner)
    subject = {b["key"]: b for b in progress["by_subject"]}
    mode = {b["key"]: b for b in progress["by_answer_mode"]}
    difficulty = {b["key"]: b for b in progress["by_difficulty"]}

    assert subject["math"]["independent"] == _stat(2, 2, 1.0)
    assert subject["math"]["assisted"] == _stat(1, 1)
    assert subject["physics"]["independent"] == _stat(0, 1)
    assert subject["physics"]["assisted"] == _stat(1, 1)
    assert subject["chemistry"]["independent"] == EMPTY, "化学只有一次判不出来的提交"
    assert mode["fill"]["independent"] == _stat(1, 1)
    assert mode["multiple_choice"]["independent"] == _stat(1, 1)
    assert mode["single_choice"]["independent"] == _stat(0, 1)
    assert mode["single_choice"]["assisted"] == _stat(2, 2, 1.0)
    assert difficulty["1"]["independent"] == _stat(0, 1)
    assert difficulty["2"]["independent"] == _stat(2, 2, 1.0)
    assert difficulty["5"]["independent"] == EMPTY
    assert [b["label"] for b in progress["by_answer_mode"]] == ["单选题", "多选题", "填空题"]


def test_partially_correct_counts_as_not_correct(learner):
    solve(learner, "math-mono-judge", choice("A"))
    solve(learner, "math-ineq-min", blank("4"))

    assert _progress(learner)["independent"] == _stat(1, 2, 0.5)


def test_progress_is_per_student(new_student):
    alice, bob = new_student(), new_student()
    solve(alice, "math-ineq-min", blank("4"))

    assert _progress(alice)["independent"]["denominator"] == 1
    assert _progress(bob)["independent"] == EMPTY


def test_progress_requires_authentication(anon):
    anon.error("GET", "/progress/summary", expect=401)
