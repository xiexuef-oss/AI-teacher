"""题目接口与地区适用性筛选（docs/09 推荐题目筛选逻辑）。

`onboarded` 夹具是四川高三学生，考试年份 2027。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update

from support.seeds import (
    ALL_KEYS,
    CHONGQING_TAGGED,
    GENERAL_KEYS,
    KEY_BY_ID,
    SICHUAN_LATER_YEARS,
    SICHUAN_TAGGED,
    qid,
)

FORBIDDEN_KEYS = {
    "answer",
    "answer_json",
    "answer_key",
    "value",
    "hints",
    "option_analysis",
    "solutions",
    "solution",
    "rubric",
    "teaching",
    "concept_rephrase",
    "final_answer",
    "equivalence_rules",
}


def _all_keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _all_keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _all_keys(v)}
    return set()


def _list(student, **params) -> list[dict]:
    """翻完所有页。"""
    items: list[dict] = []
    cursor = None
    while True:
        query = {**params, **({"cursor": cursor} if cursor else {})}
        page = student.data("GET", "/questions", params=query)
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items


def _keys(items: list[dict]) -> list[str]:
    return [KEY_BY_ID[item["id"]] for item in items]


# ---------------------------------------------------------------- 单题


def test_question_returns_structure_for_rendering(onboarded):
    question = onboarded.data("GET", f"/questions/{qid('math-mono-quadratic')}")

    assert question["subject"] == "math"
    assert question["type"] == "single_choice" and question["answer_mode"] == "single_choice"
    assert question["version"] == 1
    assert question["title"] == "二次函数的单调递增区间"
    assert "f(x)=x^2-2x-3" in question["content"]["stem"]
    assert [o["key"] for o in question["content"]["options"]] == ["A", "B", "C", "D"]
    assert question["content"]["blanks"] == []
    assert {k["code"] for k in question["knowledge"]} == {
        "math.function.monotonicity",
        "math.quadratic.graph",
    }


@pytest.mark.parametrize("key", sorted(ALL_KEYS))
def test_question_never_carries_answers_or_teaching_material(onboarded, key):
    question = onboarded.data("GET", f"/questions/{qid(key)}")
    assert not FORBIDDEN_KEYS & _all_keys(question)


def test_fill_question_exposes_blanks_but_not_expected_values(onboarded):
    question = onboarded.data("GET", f"/questions/{qid('phys-incline-accel')}")

    assert question["answer_mode"] == "fill"
    (blank,) = question["content"]["blanks"]
    assert blank["key"] == "b1"
    assert blank["unit_hint"], "应提示需要写单位"
    assert question["content"]["options"] == []


def test_question_source_is_labelled_honestly(onboarded):
    source = onboarded.data("GET", f"/questions/{qid('math-mono-quadratic')}")["source"]

    assert source["source_type"] == "self_authored"
    assert source["source_category"] == "foundation"
    assert source["is_engineering_sample"] is True
    assert source["source_year"] is None and source["source_url"] is None
    assert source["source_license"]
    assert "自编工程样题" in source["label"]
    assert "真题" not in str(source)


def test_assists_reflect_reviewed_material(onboarded):
    rich = onboarded.data("GET", f"/questions/{qid('math-mono-quadratic')}")["assists"]
    plain = onboarded.data("GET", f"/questions/{qid('phys-newton2-force')}")["assists"]

    assert rich == {
        "hint_levels": 3,
        "has_standard_solution": True,
        "has_fast_solution": True,
        "visual_available": True,
    }
    assert plain["has_fast_solution"] is False
    assert plain["visual_available"] is False


def test_fast_solution_is_hidden_unless_reviewed_with_conditions(onboarded, db):
    from tutor_api.models import Solution

    question_id = qid("math-mono-quadratic")
    db.execute(
        update(Solution)
        .where(Solution.question_id == question_id, Solution.kind == "fast")
        .values(reviewed=False)
    )
    db.commit()
    assert (
        onboarded.data("GET", f"/questions/{question_id}")["assists"]["has_fast_solution"] is False
    )

    db.execute(
        update(Solution)
        .where(Solution.question_id == question_id, Solution.kind == "fast")
        .values(reviewed=True, conditions_json={"conditions": [], "boundary": "x"})
    )
    db.commit()
    assert (
        onboarded.data("GET", f"/questions/{question_id}")["assists"]["has_fast_solution"] is False
    )


def test_multiple_choice_question_states_how_it_is_judged(onboarded):
    multi = onboarded.data("GET", f"/questions/{qid('math-mono-judge')}")
    single = onboarded.data("GET", f"/questions/{qid('math-mono-quadratic')}")

    assert "部分" in multi["judging_note"]
    assert "官方" in multi["judging_note"], "要说明这不是官方评分办法"
    assert single["judging_note"] is None


def test_variant_points_to_its_base_question(onboarded):
    variant = onboarded.data("GET", f"/questions/{qid('math-mono-quadratic-v1')}")
    assert variant["variant_of"] == qid("math-mono-quadratic")
    assert onboarded.data("GET", f"/questions/{qid('math-mono-quadratic')}")["variant_of"] is None


def test_unknown_question_is_404_and_malformed_id_is_422(onboarded):
    assert onboarded.error("GET", f"/questions/{uuid.uuid4()}", expect=404)["code"] == "not_found"
    assert onboarded.error("GET", "/questions/not-a-uuid", expect=422)["code"] == "validation_error"


@pytest.mark.parametrize("status", ["draft", "reviewed", "withdrawn"])
def test_only_published_questions_are_delivered_to_students(onboarded, db, status):
    from tutor_api.models import Question

    question_id = qid("math-ineq-min")
    db.execute(update(Question).where(Question.id == question_id).values(status=status))
    db.commit()

    assert onboarded.error("GET", f"/questions/{question_id}", expect=404)["code"] == "not_found"
    assert "math-ineq-min" not in _keys(_list(onboarded))


def test_questions_require_authentication(anon):
    anon.error("GET", "/questions", expect=401)
    anon.error("GET", f"/questions/{qid('math-ineq-min')}", expect=401)


# ---------------------------------------------------------------- 地区适用性


def test_sichuan_student_gets_region_questions_first_then_general(onboarded):
    items = _list(onboarded)
    keys = _keys(items)

    assert set(keys) == SICHUAN_TAGGED | GENERAL_KEYS
    assert set(keys[: len(SICHUAN_TAGGED)]) == SICHUAN_TAGGED, "地区适用题排在前面"
    for item in items:
        key = KEY_BY_ID[item["id"]]
        expected_scope = "region" if key in SICHUAN_TAGGED else "general"
        assert item["applicability"]["scope"] == expected_scope, key


def test_region_and_general_questions_are_labelled_differently(onboarded):
    by_key = {KEY_BY_ID[i["id"]]: i["applicability"] for i in _list(onboarded)}

    region = by_key["math-mono-quadratic"]
    assert region["recommended_regions"] == ["CN-51"]
    assert "四川" in region["label"] and "测试" in region["label"]
    assert (region["exam_year_from"], region["exam_year_to"]) == (2027, 2029)
    assert region["origin_region_code"] is None, "自编题没有原始来源地区"
    assert "不代表" in region["disclaimer"]

    general = by_key["math-ineq-min"]
    assert general["label"] == "全国通用基础题"
    assert general["recommended_regions"] == []
    assert "不代表" in general["disclaimer"]


def test_chongqing_student_gets_a_different_region_set(student):
    student.data(
        "PUT", "/profile", json={"region_code": "CN-50", "grade": "G12", "subjects": ["math"]}
    )

    keys = set(_keys(_list(student)))

    assert keys == CHONGQING_TAGGED | GENERAL_KEYS
    assert not keys & SICHUAN_TAGGED


def test_region_tag_is_not_used_outside_its_exam_years(onboarded):
    """docs/09 验收：不能跨年份误用。"""
    assert "chem-charge-conservation" not in _keys(_list(onboarded)), (
        "2030–2031 的标签不适用于 2027 届"
    )

    onboarded.data(
        "PUT",
        "/profile",
        json={"region_code": "CN-51", "grade": "G12", "subjects": ["math"], "exam_year": 2030},
    )
    keys = set(_keys(_list(onboarded)))

    assert keys == SICHUAN_LATER_YEARS | GENERAL_KEYS
    assert not keys & SICHUAN_TAGGED, "2027–2029 的标签不适用于 2030 届"


def test_student_without_exam_year_only_gets_untagged_or_unbounded_questions(student):
    student.data("PUT", "/profile", json={"region_code": "CN-51", "subjects": ["math"]})
    assert set(_keys(_list(student))) == GENERAL_KEYS


def test_student_without_region_only_gets_general_questions(student):
    items = _list(student)
    assert set(_keys(items)) == GENERAL_KEYS
    assert {item["applicability"]["scope"] for item in items} == {"general"}


def test_scope_filter(onboarded):
    assert set(_keys(_list(onboarded, scope="region"))) == SICHUAN_TAGGED
    assert set(_keys(_list(onboarded, scope="general"))) == GENERAL_KEYS
    assert set(_keys(_list(onboarded, scope="all"))) == SICHUAN_TAGGED | GENERAL_KEYS


def test_unapproved_region_tags_are_ignored(onboarded, db):
    """地区标记经审核（approved）才参与推荐；未审核的标记等于没有。"""
    from tutor_api.models import QuestionRegionApplicability as Tag

    db.execute(
        update(Tag)
        .where(Tag.question_id == qid("math-mono-quadratic"))
        .values(review_status="draft")
    )
    db.commit()

    by_key = {KEY_BY_ID[i["id"]]: i["applicability"] for i in _list(onboarded)}
    assert by_key["math-mono-quadratic"]["scope"] == "general"
    assert by_key["math-mono-quadratic"]["recommended_regions"] == []


def test_question_tagged_for_another_region_shows_its_own_label_when_opened_directly(onboarded):
    applicability = onboarded.data("GET", f"/questions/{qid('math-ineq-rect')}")["applicability"]

    assert applicability["recommended_regions"] == ["CN-50"]
    assert "重庆" in applicability["label"]


# ---------------------------------------------------------------- 筛选与分页


def test_filter_by_subject_and_answer_mode(onboarded):
    physics = _list(onboarded, subject="physics")
    assert physics and {item["subject"] for item in physics} == {"physics"}

    fills = _list(onboarded, answer_mode="fill")
    assert fills and {item["answer_mode"] for item in fills} == {"fill"}

    both = _keys(_list(onboarded, subject="chemistry", answer_mode="multiple_choice"))
    assert both == ["chem-ion-inference"]


def test_source_category_filter_never_fakes_real_exam_questions(onboarded):
    """没有授权的高考真题时，筛选结果就是空的，不拿自编题充数。"""
    assert _list(onboarded, source_category="gaokao_real") == []
    assert _list(onboarded, source_category="mock_exam") == []
    assert _list(onboarded, source_category="ai_variant") == []
    assert len(_list(onboarded, source_category="foundation")) == len(SICHUAN_TAGGED | GENERAL_KEYS)


@pytest.mark.parametrize(
    "params",
    [
        {"subject": "biology"},
        {"answer_mode": "essay"},
        {"scope": "nearby"},
        {"limit": 0},
        {"limit": 51},
    ],
)
def test_invalid_filters_are_422(onboarded, params):
    onboarded.error("GET", "/questions", expect=422, params=params)


def test_pagination_walks_every_question_exactly_once(onboarded):
    first = onboarded.data("GET", "/questions", params={"limit": 5})
    assert len(first["items"]) == 5 and first["next_cursor"]

    everything = _list(onboarded, limit=5)

    ids = [item["id"] for item in everything]
    assert len(ids) == len(set(ids)) == len(SICHUAN_TAGGED | GENERAL_KEYS)
    assert ids == [item["id"] for item in _list(onboarded, limit=50)], "分页不改变顺序"


def test_invalid_cursor_is_400(onboarded):
    error = onboarded.error("GET", "/questions", expect=400, params={"cursor": "not-a-cursor"})
    assert error["code"] == "invalid_cursor"


# ---------------------------------------------------------------- 种子


def test_seeding_is_idempotent(app, db, clock):
    from sqlalchemy import func, select

    from tutor_api.models import Question
    from tutor_api.services.content_seed import seed_if_empty

    before = db.scalar(select(func.count()).select_from(Question))
    added = seed_if_empty(db, clock.now())
    db.commit()

    assert before == len(ALL_KEYS)
    assert added == 0
    assert db.scalar(select(func.count()).select_from(Question)) == before


def _question_count_after_startup(settings, clock, database, *, seed: bool) -> int:
    from sqlalchemy import func, select
    from starlette.testclient import TestClient

    from support.api import LOOPBACK
    from tutor_api.main import create_app
    from tutor_api.models import Question

    fresh = settings.model_copy(
        update={"database_url": f"sqlite:///{database.as_posix()}", "seed_sample_content": seed}
    )
    app = create_app(fresh, clock=clock.now)
    with TestClient(app, client=LOOPBACK), app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(Question))


def test_nothing_is_seeded_unless_explicitly_enabled(settings, clock, tmp_path):
    assert (
        _question_count_after_startup(settings, clock, tmp_path / "empty.sqlite3", seed=False) == 0
    )


def test_startup_seeds_an_empty_database_when_enabled(settings, clock, tmp_path):
    count = _question_count_after_startup(settings, clock, tmp_path / "fresh.sqlite3", seed=True)
    assert count == len(ALL_KEYS)
