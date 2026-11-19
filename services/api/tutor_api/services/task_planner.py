"""今日任务（PRD P0 第 2 条）。任务不落库，每次按当前状态即时计算。

顺序与上限：
1. 到期的复习：第一档叫"复习旧错题"，之后各档叫"间隔复测"，最多 3 项，不受所选学科限制；
2. 变式：做过母题、还没碰过的变式题，最多 1 项；
3. 薄弱点：某个知识点上"没有独立做对"的次数多于"独立做对"的次数，就再推一道同知识点的新题，最多 2 项；
4. 新题：每个所选学科一道没做过的非变式题，地区适用题优先。
总数不超过 5，同一道题只出现一次。只推荐可以发给这名学生的题（见 question_service）。

薄弱点的判断是最朴素的计数规则，样本很少时也会触发；它只用来决定"再练一道"，不对外展示为掌握度。

什么算"做过"：提交过作答，或者已经结束独立作答去看了解析。只是点开了题、画了几笔、看了提示，
没提交就离开的，还算"没做完"，仍然留在今日任务里（否则接个电话回来，任务就不见了）。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tutor_api import launch
from tutor_api.models import (
    Attempt,
    KnowledgeNode,
    Question,
    QuestionKnowledge,
    ReviewItem,
    StudySession,
)
from tutor_api.schemas import StudyTask, TodayTasks
from tutor_api.services import grading, question_service

MAX_TASKS = 5
MAX_REVIEWS = 3
MAX_VARIANTS = 1
MAX_WEAK_POINTS = 2
_TASK_NAMESPACE = uuid.UUID("0d6c2a55-3d0e-4f66-9a0b-7c1b8f1f2a90")


def estimated_minutes(question: Question) -> int:
    """估计用时。选择题和填空题几分钟；解答题要写出完整步骤、还要对照要点自查，时间长得多；
    实验题还要读表、算数、填数据，更长一点；证明题要想构造、每一步写依据，最长。"""
    if question.answer_mode == "written":
        return 8 + 2 * question.difficulty
    if question.answer_mode == "experiment":
        return 10 + 2 * question.difficulty
    if question.answer_mode == "proof":
        return 9 + 3 * question.difficulty
    return 3 + question.difficulty


def _objective_first(questions: list[Question]) -> list[Question]:
    """新题先推可以自动判定的题；解答题、实验题和证明题排在后面。先熟悉作答和反馈，再去写完整步骤、填数据表、写证明。
    顺序其余不变。"""
    return [q for q in questions if q.answer_mode not in grading.SUBJECTIVE_MODES] + [
        q for q in questions if q.answer_mode in grading.SUBJECTIVE_MODES
    ]


def _weak_nodes(db: Session, student_id: str) -> list[KnowledgeNode]:
    """按知识点统计有确定判定的首次作答：没有独立做对的次数多于独立做对的次数，记为薄弱。"""
    rows = db.execute(
        select(QuestionKnowledge.knowledge_id, Attempt.is_correct, Attempt.independent)
        .join(StudySession, StudySession.question_id == QuestionKnowledge.question_id)
        .join(Attempt, Attempt.session_id == StudySession.id)
        .where(
            StudySession.student_id == student_id,
            Attempt.submission_no == 1,
            Attempt.status == "submitted",
            Attempt.evaluation_state == "verified",
        )
    )
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for knowledge_id, is_correct, independent in rows:
        tally[knowledge_id][0 if (is_correct and independent) else 1] += 1
    weak = [
        knowledge_id for knowledge_id, (succeeded, failed) in tally.items() if failed > succeeded
    ]
    if not weak:
        return []
    return list(
        db.scalars(
            select(KnowledgeNode).where(KnowledgeNode.id.in_(weak)).order_by(KnowledgeNode.code)
        )
    )


def today_tasks(db: Session, student_id: str, *, now: datetime) -> TodayTasks:
    today = now.date()
    scope = question_service.student_scope(db, student_id)
    subjects = [code for code, _ in launch.SUBJECTS if code in scope.subjects] or [
        code for code, _ in launch.SUBJECTS
    ]
    deliverable = [question for question, _ in question_service.deliverable_questions(db, scope)]
    # 新题和薄弱点补练都先推可以自动判定的题，解答题排在后面
    ordered = _objective_first(deliverable)

    worked_on = set(
        db.scalars(
            select(StudySession.question_id)
            .join(Attempt, Attempt.session_id == StudySession.id)
            .where(StudySession.student_id == student_id, Attempt.status == "submitted")
            .distinct()
        )
    )
    # 没提交、但已经放弃独立作答去看了解析的：答案看过了，也不能再当新题推
    viewed_solution = set(
        db.scalars(
            select(StudySession.question_id)
            .where(
                StudySession.student_id == student_id,
                or_(StudySession.independent_ended.is_(True), StudySession.used_solution.is_(True)),
            )
            .distinct()
        )
    )
    attempted = worked_on | viewed_solution
    scheduled = list(
        db.scalars(
            select(ReviewItem)
            .where(ReviewItem.student_id == student_id, ReviewItem.status == "scheduled")
            .order_by(ReviewItem.due_at, ReviewItem.id)
        )
    )
    in_review = {item.question_id for item in scheduled}

    # (类别, 题目, 标题模板, 推荐理由, 复测项 ID)
    picked: list[tuple[str, Question, str, str, str | None]] = []
    used: set[str] = set()

    def add(
        kind: str, question: Question, title: str, reason: str, review_item_id: str | None = None
    ) -> None:
        if len(picked) < MAX_TASKS and question.id not in used:
            picked.append((kind, question, title, reason, review_item_id))
            used.add(question.id)

    # 1. 到期的复习
    due = [item for item in scheduled if item.due_at <= now]
    for item in due[:MAX_REVIEWS]:
        question = db.get(Question, item.question_id)
        if question is None or question.status != "published":
            continue
        if item.stage == 0:
            add(
                "review_mistake",
                question,
                "复习旧错题：{title}",
                "这道题之前没有独立做对，到了复习时间。不看提示再做一遍。",
                item.id,
            )
        else:
            add(
                "retest",
                question,
                "间隔复测：{title}",
                f"第 {item.stage + 1} 次间隔复测，不看提示做一遍，确认还记得。",
                item.id,
            )

    # 2. 变式
    variants = [
        q
        for q in deliverable
        if q.variant_of_id in worked_on and q.id not in attempted and q.subject in subjects
    ]
    for question in variants[:MAX_VARIANTS]:
        add(
            "variant",
            question,
            "变式：{title}",
            "你做过它的母题，换个问法检验一下是不是真的掌握了。",
        )

    # 3. 薄弱点
    linked: dict[str, set[str]] = defaultdict(set)
    if deliverable:
        for question_id, knowledge_id in db.execute(
            select(QuestionKnowledge.question_id, QuestionKnowledge.knowledge_id).where(
                QuestionKnowledge.question_id.in_([q.id for q in deliverable])
            )
        ):
            linked[knowledge_id].add(question_id)
    weak_added = 0
    for node in _weak_nodes(db, student_id):
        if weak_added >= MAX_WEAK_POINTS:
            break
        candidate = next(
            (
                q
                for q in ordered
                if q.id in linked[node.id]
                and q.id not in attempted
                and q.id not in used
                and q.id not in in_review
                and q.subject in subjects
            ),
            None,
        )
        if candidate is not None:
            before = len(picked)
            add(
                "weak_point",
                candidate,
                f"薄弱点：{node.title}",
                f"在“{node.title}”上独立做对的次数还不够，再练一道同类题。",
            )
            weak_added += len(picked) - before

    # 4. 新题
    new_reason = "按你选择的学科继续练习。" if attempted else "还没有学习记录，先从基础题开始。"
    for subject in subjects:
        candidate = next(
            (
                q
                for q in ordered
                if q.subject == subject
                and q.variant_of_id is None
                and q.id not in attempted
                and q.id not in used
            ),
            None,
        )
        if candidate is not None:
            add("new_topic", candidate, "{title}", new_reason)

    questions = [question for _, question, _, _, _ in picked]
    versions = question_service.current_versions(db, questions)
    tags = question_service.approved_tags(db, [q.id for q in questions])
    items = []
    for kind, question, title, reason, review_item_id in picked:
        question_title = versions[question.id].content_json.get("title") or ""
        items.append(
            StudyTask(
                id=str(
                    uuid.uuid5(
                        _TASK_NAMESPACE, f"{student_id}|{today.isoformat()}|{kind}|{question.id}"
                    )
                ),
                kind=kind,
                title=title.format(title=question_title),
                reason=reason,
                subject=question.subject,
                question_id=question.id,
                review_item_id=review_item_id,
                applicability=question_service.build_applicability(
                    question, tags[question.id], scope
                ),
                estimated_minutes=estimated_minutes(question),
            )
        )
    return TodayTasks(date=today, items=items, cold_start=not attempted)
