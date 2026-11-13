"""学情摘要（PRD §7，基础版）。

口径：
- 有效作答 = 已提交且有确定判定（verified）的作答；判不出来的另计数，不进任何分母；
- 独立正确率 = 无提示且未看解析的正确作答数 / 无提示且未看解析的有效作答数；辅助正确率另算；
- "正确"只指完全正确，多选的部分正确不算；
- 提示依赖率、复测成功率、变式迁移率只看每次会话的第一份作答；
- 分母小于 min_samples 时只给计数，rate 为 null，并标记 insufficient_data；
- 解答题不自动评分，不进任何正确率，也不算"没能判定"。它单独数：提交了几份、自查了几份、
  自查里各档要点各有几个——这些是学生自己的记录，不折算成分数。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api import launch
from tutor_api.models import Attempt, AttemptSelfCheck, Question, StudySession
from tutor_api.schemas import ProgressBucket, ProgressSummary, RateStat, SubjectiveProgress
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


def rate_stat(rows: Iterable[_Row], hit: Callable[[_Row], bool], min_samples: int) -> RateStat:
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


def is_correct(row: _Row) -> bool:
    return row.correct


def unaided_success(row: _Row) -> bool:
    return row.correct and row.independent


def load_records(
    db: Session,
    student_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[Any]:
    """这名学生已提交的作答（附会话来源、题目的学科/题型/难度）。since 含、until 不含，按提交时间；都不给就是全部。"""
    query = (
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
    )
    if since is not None:
        query = query.where(Attempt.submitted_at >= since)
    if until is not None:
        query = query.where(Attempt.submitted_at < until)
    return list(db.execute(query).all())


def verified_rows(records: Iterable[Any]) -> list[_Row]:
    """只有确定判定的作答进比例；判不出来的、解答题都不算。"""
    return [
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


def bucket(key: str, label: str, rows: list[_Row], min_samples: int) -> ProgressBucket:
    return ProgressBucket(
        key=key,
        label=label,
        independent=rate_stat((r for r in rows if r.independent), is_correct, min_samples),
        assisted=rate_stat((r for r in rows if not r.independent), is_correct, min_samples),
    )


def subject_buckets(rows: list[_Row], min_samples: int) -> list[ProgressBucket]:
    return [
        bucket(code, name, [r for r in rows if r.subject == code], min_samples)
        for code, name in launch.SUBJECTS
    ]


def _subjective(db: Session, attempt_ids: list[str]) -> SubjectiveProgress:
    """解答题只数不评：提交几份、自查几份、自查里各档要点各有几个。"""
    marks = (
        [
            row.marks_json
            for row in db.scalars(
                select(AttemptSelfCheck).where(AttemptSelfCheck.attempt_id.in_(attempt_ids))
            )
        ]
        if attempt_ids
        else []
    )
    levels = Counter(mark["level"] for row in marks for mark in row)
    return SubjectiveProgress(
        attempts=len(attempt_ids),
        self_checked=len(marks),
        points_done=levels["done"],
        points_partial=levels["partial"],
        points_missed=levels["missed"],
    )


def summarize(
    db: Session, settings: Settings, student_id: str, *, now: datetime
) -> ProgressSummary:
    min_samples = settings.progress_min_samples
    records = load_records(db, student_id)
    verified = verified_rows(records)
    first = [row for row in verified if row.attempt_no == 1]
    written = [attempt for attempt, _, _, mode, _ in records if mode == "written"]
    uncertain = [
        attempt
        for attempt, _, _, mode, _ in records
        if mode != "written" and attempt.evaluation_state != "verified"
    ]

    return ProgressSummary(
        generated_at=now,
        min_samples=min_samples,
        independent=rate_stat((r for r in verified if r.independent), is_correct, min_samples),
        assisted=rate_stat((r for r in verified if not r.independent), is_correct, min_samples),
        hint_dependency=rate_stat(first, lambda r: not r.independent, min_samples),
        retest_success=rate_stat(
            (r for r in first if r.origin == "review"), unaided_success, min_samples
        ),
        variant_transfer=rate_stat(
            (r for r in first if r.origin == "variant"), unaided_success, min_samples
        ),
        uncertain_attempts=len(uncertain),
        subjective=_subjective(db, [attempt.id for attempt in written]),
        by_subject=subject_buckets(verified, min_samples),
        by_answer_mode=[
            bucket(
                mode,
                launch.ANSWER_MODE_NAMES[mode],
                [r for r in verified if r.answer_mode == mode],
                min_samples,
            )
            for mode in _OBJECTIVE_MODES
        ],
        by_difficulty=[
            bucket(
                str(level),
                f"难度 {level}",
                [r for r in verified if r.difficulty == level],
                min_samples,
            )
            for level in range(1, 6)
        ],
        disclaimer=DISCLAIMER,
    )
