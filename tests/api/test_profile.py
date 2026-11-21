"""地区资料（REG-001，docs/09）。夹具时钟为 2026-11-10，对应 2026–27 学年。"""

from __future__ import annotations

import uuid

import pytest

SICHUAN_G12 = {
    "expected_revision": 0,
    "region_code": "CN-51",
    "grade": "G12",
    "subjects": ["math", "physics"],
}


def _codes(profile: dict) -> set[str]:
    return {notice["code"] for notice in profile["notices"]}


# ---------------------------------------------------------------- 启动配置


def test_launch_config_lists_the_two_frozen_regions(anon):
    config = anon.data("GET", "/meta/launch-config", auth=False)

    assert config["regions"] == [
        {"code": "CN-51", "name": "四川"},
        {"code": "CN-50", "name": "重庆"},
    ]
    assert [s["code"] for s in config["subjects"]] == ["math", "physics", "chemistry"]
    assert config["school_year_start_month"] == 9


def test_launch_config_estimates_exam_year_per_grade(anon, clock):
    grades = {g["code"]: g for g in anon.data("GET", "/meta/launch-config", auth=False)["grades"]}
    assert {code: g["estimated_exam_year"] for code, g in grades.items()} == {
        "G10": 2029,
        "G11": 2028,
        "G12": 2027,
    }
    assert grades["G12"]["name"] == "高三"

    clock.advance(days=320)  # 2027-09 之后进入下一学年
    grades = {g["code"]: g for g in anon.data("GET", "/meta/launch-config", auth=False)["grades"]}
    assert grades["G12"]["estimated_exam_year"] == 2028


def test_launch_config_curriculum_options_carry_no_region_binding(anon):
    config = anon.data("GET", "/meta/launch-config", auth=False)
    assert config["curriculum_versions"], "应提供可手动选择的教材选项"
    for option in config["curriculum_versions"]:
        assert set(option) == {"code", "name"}


# ---------------------------------------------------------------- 读取与保存


def test_new_student_has_an_empty_profile(student):
    profile = student.data("GET", "/profile")

    assert profile["user_id"] == student.user_id
    assert profile["region_code"] is None and profile["grade"] is None
    assert profile["subjects"] == []
    assert profile["exam_year"] is None and profile["exam_year_source"] is None
    assert profile["curriculum_version"] is None
    assert profile["onboarding_completed"] is False


def test_learning_settings_survive_legacy_profile_updates(student):
    settings = {
        "mode": "boarding",
        "weekly_minutes": 0,
        "weekdays": [1, 5],
        "school_progress": "",
        "exam_scope": "",
    }
    first = student.save_profile(json={**SICHUAN_G12, "learning_settings": settings})
    assert first["learning_settings"] == settings
    updated = student.save_profile(json={**SICHUAN_G12, "expected_revision": first["revision"]})
    assert updated["learning_settings"] == student.data("GET", "/profile")["learning_settings"]
    assert updated["learning_settings"] == settings


def test_onboarding_saves_region_grade_and_subjects(student):
    saved = student.save_profile(json=SICHUAN_G12)

    assert saved["region_code"] == "CN-51"
    assert saved["grade"] == "G12"
    assert saved["subjects"] == ["math", "physics"]
    assert saved["onboarding_completed"] is True
    assert student.data("GET", "/profile") == saved


def test_exam_year_defaults_to_the_estimate_and_says_so(student):
    saved = student.save_profile(json=SICHUAN_G12)

    assert saved["exam_year"] == 2027
    assert saved["exam_year_source"] == "estimated"
    assert "exam_year_estimated" in _codes(saved)


@pytest.mark.parametrize("region", ["CN-11", "cn-51", "四川", "", None])
def test_region_must_be_one_of_the_launch_regions(student, region):
    error = student.error(
        "PUT", "/profile", expect=422, json={**SICHUAN_G12, "region_code": region}
    )
    assert error["code"] == "validation_error"


def test_region_is_required_and_never_inferred(student):
    """地区只能由用户手动选择：不带 region_code 的保存一律拒绝，定位类请求头不起作用。"""
    headers = {
        "X-Forwarded-For": "118.112.0.1",
        "X-Geo-Region": "CN-51",
        "Accept-Language": "zh-CN",
    }
    student.error(
        "PUT", "/profile", expect=422, json={"grade": "G12", "subjects": ["math"]}, headers=headers
    )
    assert student.data("GET", "/profile", headers=headers)["region_code"] is None


@pytest.mark.parametrize(
    "subjects",
    [[], ["biology"], ["math", "math"], "math", ["math", "physics", "chemistry", "math"]],
    ids=["empty", "unsupported", "duplicate", "not-a-list", "too-many"],
)
def test_subjects_must_be_a_nonempty_set_of_launch_subjects(student, subjects):
    student.error("PUT", "/profile", expect=422, json={**SICHUAN_G12, "subjects": subjects})


def test_grade_can_be_skipped(student):
    saved = student.save_profile(json={"region_code": "CN-50", "subjects": ["chemistry"]})

    assert saved["grade"] is None
    assert saved["exam_year"] is None and saved["exam_year_source"] is None
    assert saved["onboarding_completed"] is True
    assert "grade_unknown" in _codes(saved)


# ---------------------------------------------------------------- 教材版本（Q-08）


def test_unknown_curriculum_does_not_block_learning_but_prompts_to_complete(student):
    saved = student.save_profile(json=SICHUAN_G12)

    assert saved["curriculum_version"] is None
    assert saved["onboarding_completed"] is True
    assert "curriculum_unknown" in _codes(saved)


def test_curriculum_can_be_added_later(anon, student):
    option = anon.data("GET", "/meta/launch-config", auth=False)["curriculum_versions"][0]["code"]
    student.save_profile(json=SICHUAN_G12)

    saved = student.save_profile(json={**SICHUAN_G12, "curriculum_version": option})

    assert saved["curriculum_version"] == option
    assert "curriculum_unknown" not in _codes(saved)


def test_curriculum_must_be_a_listed_option(student):
    student.error(
        "PUT", "/profile", expect=422, json={**SICHUAN_G12, "curriculum_version": "MADE-UP"}
    )


def test_region_does_not_imply_a_curriculum(anon, student):
    """docs/09：不得凭省份自动指定教材版本。"""
    for region in ("CN-51", "CN-50"):
        saved = student.save_profile(json={**SICHUAN_G12, "region_code": region})
        assert saved["curriculum_version"] is None
        assert "curriculum_unknown" in _codes(saved)

    options = anon.data("GET", "/meta/launch-config", auth=False)["curriculum_versions"]
    for option in (options[0], options[-1]):
        for region in ("CN-51", "CN-50"):
            selected = student.save_profile(
                json={
                    **SICHUAN_G12,
                    "region_code": region,
                    "curriculum_version": option["code"],
                }
            )
            assert selected["region_code"] == region
            assert selected["curriculum_version"] == option["code"]
            assert "curriculum_unknown" not in _codes(selected)


# ---------------------------------------------------------------- 考试年份


def test_manual_exam_year_is_marked_and_survives_a_grade_change(student):
    manual = student.save_profile(json={**SICHUAN_G12, "exam_year": 2028})
    assert (manual["exam_year"], manual["exam_year_source"]) == (2028, "user")
    assert "exam_year_estimated" not in _codes(manual)

    later = student.save_profile(json={**SICHUAN_G12, "grade": "G11"})

    assert (later["exam_year"], later["exam_year_source"]) == (2028, "user")


def test_estimated_exam_year_follows_a_grade_change(student):
    student.save_profile(json=SICHUAN_G12)

    later = student.save_profile(json={**SICHUAN_G12, "grade": "G10"})

    assert (later["exam_year"], later["exam_year_source"]) == (2029, "estimated")


@pytest.mark.parametrize("year", [1999, 2025, 2031, 2099])
def test_exam_year_outside_the_plausible_range_is_rejected(student, year):
    student.error("PUT", "/profile", expect=422, json={**SICHUAN_G12, "exam_year": year})


# ---------------------------------------------------------------- 考试制度版本（Q-09）


def _add_rule(db, clock, *, status: str, with_basis: bool) -> None:
    from tutor_api.models import ExamRegionRule

    db.add(
        ExamRegionRule(
            id=str(uuid.uuid4()),
            region_code="CN-51",
            exam_year=2027,
            subject="math",
            scheme_code="SCHEME-X",
            version=1,
            status=status,
            rule_json={},
            official_source="测试用依据名称" if with_basis else None,
            reviewed_by=str(uuid.uuid4()) if with_basis else None,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
    )
    db.commit()


def test_exam_scheme_stays_empty_without_any_rule(student):
    assert student.save_profile(json=SICHUAN_G12)["exam_scheme_code"] is None


@pytest.mark.parametrize(
    ("status", "with_basis"),
    [("draft", True), ("reviewed", True), ("active", False), ("retired", True)],
)
def test_rule_that_is_not_active_with_official_basis_is_ignored(
    student, db, clock, status, with_basis
):
    """docs/09：地区规则无依据不得启用。"""
    _add_rule(db, clock, status=status, with_basis=with_basis)
    assert student.save_profile(json=SICHUAN_G12)["exam_scheme_code"] is None


def test_active_rule_with_basis_applies_only_to_its_region_and_year(student, db, clock):
    _add_rule(db, clock, status="active", with_basis=True)

    assert student.save_profile(json=SICHUAN_G12)["exam_scheme_code"] == "SCHEME-X"
    other_year = student.save_profile(json={**SICHUAN_G12, "grade": "G11"})
    assert other_year["exam_scheme_code"] is None, "规则不能跨年份套用"
    other_region = student.save_profile(json={**SICHUAN_G12, "region_code": "CN-50"})
    assert other_region["exam_scheme_code"] is None, "规则不能跨地区套用"


# ---------------------------------------------------------------- 约束与隔离


def test_unknown_fields_are_rejected(student):
    body = {**SICHUAN_G12, "student_id": str(uuid.uuid4()), "role": "admin"}
    student.error("PUT", "/profile", expect=422, json=body)


def test_profiles_are_isolated_between_students(new_student):
    alice, bob = new_student(), new_student()
    alice.save_profile(json=SICHUAN_G12)

    assert bob.data("GET", "/profile")["region_code"] is None
    assert bob.data("GET", "/profile")["user_id"] == bob.user_id


def test_switching_region_is_recorded_in_the_audit_log(student, db):
    from sqlalchemy import select

    from tutor_api.models import AuditLog

    student.save_profile(json=SICHUAN_G12)
    student.save_profile(json={**SICHUAN_G12, "region_code": "CN-50"})
    student.save_profile(json={**SICHUAN_G12, "region_code": "CN-50"})

    logs = db.scalars(select(AuditLog).where(AuditLog.action == "profile.region_changed")).all()
    assert [(log.actor_id, log.detail_json) for log in logs] == [
        (student.user_id, {"from": None, "to": "CN-51"}),
        (student.user_id, {"from": "CN-51", "to": "CN-50"}),
    ]
