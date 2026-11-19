"""学生资料与地区设置（REG-001，docs/09）。

省份、考试年份、考试制度版本、教材版本分开保存，互不推断：
- 地区只接受用户手动选择；
- 考试年份默认按年级估算，用户改过之后不再被估算覆盖；
- 考试制度版本只在存在"已生效且有官方依据"的地区规则时才有值；
- 教材版本可以一直为空。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tutor_api import launch
from tutor_api.db import new_id
from tutor_api.errors import conflict, not_found, unprocessable
from tutor_api.models import AuditLog, ExamRegionRule, StudentProfile, User
from tutor_api.schemas import LaunchConfig, ProfileNotice, ProfileUpdateIn, StudentProfileOut


def school_year_start(today: date) -> int:
    """today 所在学年的起始年份。学年以 9 月为起点。"""
    return today.year if today.month >= launch.SCHOOL_YEAR_START_MONTH else today.year - 1


def estimate_exam_year(grade: str | None, today: date) -> int | None:
    """按年级估算高考年份：高三在本学年结束的那一年参加高考。"""
    if grade is None:
        return None
    return school_year_start(today) + (13 - launch.GRADE_NUMBERS[grade])


def exam_year_range(today: date) -> tuple[int, int]:
    return today.year, today.year + launch.EXAM_YEAR_WINDOW


def build_launch_config(today: date) -> LaunchConfig:
    year_min, year_max = exam_year_range(today)
    return LaunchConfig(
        regions=[{"code": code, "name": name} for code, name in launch.REGIONS],
        grades=[
            {"code": code, "name": name, "estimated_exam_year": estimate_exam_year(code, today)}
            for code, name, _ in launch.GRADES
        ],
        subjects=[{"code": code, "name": name} for code, name in launch.SUBJECTS],
        curriculum_versions=[
            {"code": code, "name": name} for code, name in launch.CURRICULUM_OPTIONS
        ],
        school_year_start_month=launch.SCHOOL_YEAR_START_MONTH,
        exam_year_min=year_min,
        exam_year_max=year_max,
    )


def resolve_scheme_code(db: Session, region_code: str | None, exam_year: int | None) -> str | None:
    """只认已生效（active）且带官方依据、有审核人的规则；规则不跨地区、不跨年份套用。"""
    if region_code is None or exam_year is None:
        return None
    codes = db.scalars(
        select(ExamRegionRule.scheme_code)
        .where(
            ExamRegionRule.region_code == region_code,
            ExamRegionRule.exam_year == exam_year,
            ExamRegionRule.status == "active",
            ExamRegionRule.official_source.is_not(None),
            ExamRegionRule.reviewed_by.is_not(None),
        )
        .distinct()
    ).all()
    return codes[0] if len(codes) == 1 else None


def get_profile(db: Session, student_id: str) -> StudentProfile:
    profile = db.get(StudentProfile, student_id)
    if profile is None:
        raise not_found()
    return profile


def serialize_profile(db: Session, profile: StudentProfile) -> StudentProfileOut:
    user = db.get(User, profile.user_id)
    subjects = sorted(
        profile.subjects_json or [], key=lambda code: launch.SUBJECT_ORDER.get(code, 99)
    )
    completed = profile.region_code is not None and bool(subjects)

    notices: list[ProfileNotice] = []
    if completed:
        if profile.grade is None:
            notices.append(
                ProfileNotice(
                    code="grade_unknown",
                    message="还没有选择年级，暂时无法估算考试年份；可以在“我的”里补充。",
                )
            )
        if profile.exam_year_source == "estimated":
            notices.append(
                ProfileNotice(
                    code="exam_year_estimated",
                    message=f"考试年份按年级估算为 {profile.exam_year} 年，可以在“我的”里修改。",
                )
            )
        if profile.curriculum_version is None:
            notices.append(
                ProfileNotice(
                    code="curriculum_unknown",
                    message="还没有设置教材版本，目前按通用知识点推荐；确认后可以在“我的”里补充。",
                )
            )

    return StudentProfileOut(
        learning_settings=profile.learning_settings_json,
        user_id=profile.user_id,
        revision=profile.revision,
        display_name=user.display_name if user else None,
        region_code=profile.region_code,
        grade=profile.grade,
        subjects=subjects,
        exam_year=profile.exam_year,
        exam_year_source=profile.exam_year_source,
        exam_scheme_code=resolve_scheme_code(db, profile.region_code, profile.exam_year),
        curriculum_version=profile.curriculum_version,
        onboarding_completed=completed,
        notices=notices,
        updated_at=profile.updated_at,
    )


def update_profile(
    db: Session, student_id: str, body: ProfileUpdateIn, *, now: datetime, request_id: str
) -> StudentProfile:
    # Lock the stable owner first. MySQL locking reads are current reads even
    # after a REPEATABLE READ snapshot; populate_existing defeats stale ORM rows.
    if db.bind.dialect.name == "sqlite":
        db.execute(
            update(User)
            .where(User.id == student_id)
            .values(updated_at=User.updated_at)
            .execution_options(synchronize_session=False)
        )
    owner = db.scalar(
        select(User)
        .where(User.id == student_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if owner is None:
        raise not_found()
    profile = db.scalar(
        select(StudentProfile)
        .where(StudentProfile.user_id == student_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if profile is None:
        raise not_found()
    if profile.revision != body.expected_revision:
        raise conflict(
            "profile_revision_conflict",
            "资料已在其他地方更新，请保留双方内容并选择后再保存",
            {
                "expected_revision": body.expected_revision,
                "server_revision": profile.revision,
                "server_profile": serialize_profile(db, profile).model_dump(mode="json"),
            },
        )
    today = now.date()

    if (
        body.curriculum_version is not None
        and body.curriculum_version not in launch.CURRICULUM_CODES
    ):
        raise unprocessable("curriculum_version", "不是可选的教材版本；不清楚时请留空")

    if body.exam_year is not None:
        year_min, year_max = exam_year_range(today)
        if not year_min <= body.exam_year <= year_max:
            raise unprocessable("exam_year", f"考试年份应在 {year_min} 到 {year_max} 之间")
        exam_year, source = body.exam_year, "user"
    elif profile.exam_year_source == "user":
        exam_year, source = profile.exam_year, "user"
    else:
        exam_year = estimate_exam_year(body.grade, today)
        source = "estimated" if exam_year is not None else None

    previous_region = profile.region_code
    result = db.execute(
        update(StudentProfile)
        .where(
            StudentProfile.user_id == student_id,
            StudentProfile.revision == body.expected_revision,
        )
        .values(
            region_code=body.region_code,
            learning_settings_json=(
                body.learning_settings.model_dump(mode="json")
                if body.learning_settings is not None
                else profile.learning_settings_json
            ),
            grade=body.grade,
            subjects_json=sorted(body.subjects, key=lambda code: launch.SUBJECT_ORDER[code]),
            exam_year=exam_year,
            exam_year_source=source,
            curriculum_version=body.curriculum_version,
            exam_scheme_code=resolve_scheme_code(db, body.region_code, exam_year),
            updated_at=now,
            revision=StudentProfile.revision + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise conflict("profile_revision_conflict", "资料版本已变化，请重新读取后选择保存")
    db.refresh(profile)
    if previous_region != body.region_code:
        # 切换地区只影响之后的推荐；已有会话保留各自的地区快照
        db.add(
            AuditLog(
                id=new_id(),
                actor_id=student_id,
                action="profile.region_changed",
                target_type="student_profile",
                target_id=student_id,
                detail_json={"from": previous_region, "to": body.region_code},
                request_id=request_id,
                created_at=now,
            )
        )

    user = owner
    if user is not None and body.display_name is not None:
        user.display_name = body.display_name
        user.updated_at = now
    return profile
