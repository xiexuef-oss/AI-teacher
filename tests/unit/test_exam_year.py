"""考试年份估算：学年以 9 月为起点（ADR-006 Q-08）。"""

from __future__ import annotations

from datetime import date

import pytest

from tutor_api.services.profile_service import estimate_exam_year


@pytest.mark.parametrize(
    ("today", "grade", "expected"),
    [
        (date(2026, 11, 10), "G12", 2027),
        (date(2026, 11, 10), "G11", 2028),
        (date(2026, 11, 10), "G10", 2029),
        (date(2027, 3, 1), "G12", 2027),
        (date(2027, 6, 30), "G10", 2029),
        (date(2027, 8, 31), "G12", 2027),
        (date(2027, 9, 1), "G12", 2028),
        (date(2027, 9, 1), "G10", 2030),
    ],
)
def test_exam_year_is_estimated_from_september_school_year(today, grade, expected):
    assert estimate_exam_year(grade, today) == expected


def test_unknown_grade_gives_no_estimate():
    assert estimate_exam_year(None, date(2026, 11, 10)) is None
