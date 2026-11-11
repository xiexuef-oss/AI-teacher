"""学情摘要（PRD §7，基础版）。

口径：
- 有效作答 = 已提交且有确定判定（verified）的作答；判不出来的另计数，不进任何分母；
- 独立正确率 = 无提示且未看解析的正确作答数 / 无提示且未看解析的有效作答数；辅助正确率另算；
- "正确"只指完全正确，多选的部分正确不算；
- 提示依赖率、复测成功率、变式迁移率只看每次会话的第一份作答；
- 分母小于 min_samples 时只给计数，rate 为 null，并标记 insufficient_data。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api import launch
from tutor_api.models import Attempt, Question, StudySession
from tutor_api.schemas import ProgressBucket, ProgressSummary, RateStat
from tutor_api.settings import Settings

DISCLAIMER = "这些数字来自练习反馈，不是官方成绩，也不代表短期内一定提分。样本少的时候只显示计数。"
_OBJECTIVE_MODES = ("single_choice", "multiple_choice", "fill")


@dataclass(frozen=True)
class _Row:
    attempt_no: int
    correct: bool
    independent: bool
    origin: str
    subject: str
    answer_mode: str
    difficulty: int


def _stat(rows: Iterable[_Row], hit: Callable[[_Row], bool], min_samples: int) -> RateStat:
    rows = list(rows)
    numerator = sum(1 for row in rows if hit(row))
    denominator = len(rows)
    enough = denominator >= min_samples
    return RateStat(
        numerator=numerator,
        denominator=denominator,
        rate=round(numerator / denominator, 4) if enough else None,
        insufficient_data=not enough,
    )


def summarize(
    db: Session, settings: Settings, student_id: str, *, now: datetime
) -> ProgressSummary:
    min_samples = settings.progress_min_samples
    records = db.execute(
        select(
            Attempt,
            StudySession.origin,
            Question.subject,
            Question.answer_mode,
            Question.difficulty,
        )
        .join(StudySession, StudySession.id == Attempt.session_id)
        .join(Question, Question.id == StudySession.question_id)
        .where(StudySession.student_id == student_id, Attempt.status == "submitted")
    ).all()

    verified = [
        _Row(
            attempt_no=attempt.attempt_no,
            correct=bool(attempt.is_correct),
            independent=bool(attempt.independent),
            origin=origin,
            subject=subject,
            answer_mode=answer_mode,
            difficulty=difficulty,
        )
        for attempt, origin, subject, answer_mode, difficulty in records
        if attempt.evaluation_state == "verified"
    ]
    first = [row for row in verified if row.attempt_no == 1]

    def is_correct(row: _Row) -> bool:
        return row.correct

    def unaided_success(row: _Row) -> bool:
        return row.correct and row.independent

    def bucket(key: str, label: str, rows: list[_Row]) -> ProgressBucket:
        return ProgressBucket(
            key=key,
            label=label,
            independent=_stat((r for r in rows if r.independent), is_correct, min_samples),
            assisted=_stat((r for r in rows if not r.independent), is_correct, min_samples),
        )

    return ProgressSummary(
        generated_at=now,
        min_samples=min_samples,
        independent=_stat((r for r in verified if r.independent), is_correct, min_samples),
        assisted=_stat((r for r in verified if not r.independent), is_correct, min_samples),
        hint_dependency=_stat(first, lambda r: not r.independent, min_samples),
        retest_success=_stat(
            (r for r in first if r.origin == "review"), unaided_success, min_samples
        ),
        variant_transfer=_stat(
            (r for r in first if r.origin == "variant"), unaided_success, min_samples
        ),
        uncertain_attempts=len(records) - len(verified),
        by_subject=[
            bucket(code, name, [r for r in verified if r.subject == code])
            for code, name in launch.SUBJECTS
        ],
        by_answer_mode=[
            bucket(
                mode, launch.ANSWER_MODE_NAMES[mode], [r for r in verified if r.answer_mode == mode]
            )
            for mode in _OBJECTIVE_MODES
        ],
        by_difficulty=[
            bucket(str(level), f"难度 {level}", [r for r in verified if r.difficulty == level])
            for level in range(1, 6)
        ],
        disclaimer=DISCLAIMER,
    )
