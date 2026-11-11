"""题目读取与地区适用性（docs/09 推荐题目筛选逻辑）。

- 只有 published 的题对学生可见；
- 带"已审核（approved）地区标记"的题只推荐给该地区、且考试年份落在标记区间内的学生；
- 没有任何已审核地区标记的题按"全国通用基础题"处理，并如实标注；
- 题目接口从不带出答案、解法、提示原文和选项分析。

本阶段题库很小，列表在内存里排序分页；题量上来之后要改成数据库侧分页。
"""

from __future__ import annotations

import base64
import binascii
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api import launch
from tutor_api.errors import ApiError, not_found
from tutor_api.models import (
    KnowledgeNode,
    Question,
    QuestionKnowledge,
    QuestionRegionApplicability,
    QuestionVersion,
    Rubric,
    Solution,
    StudentProfile,
)
from tutor_api.schemas import (
    Applicability,
    KnowledgeRef,
    QuestionAssists,
    QuestionContent,
    QuestionOut,
    QuestionPage,
    QuestionSource,
    QuestionSummary,
)
from tutor_api.services.content_seed import ENGINEERING_SAMPLE_LICENSE
from tutor_api.visuals import normalized_visual

_SOURCE_LABELS = {
    "self_authored": "自编题目",
    "textbook_licensed": "教材授权题目",
    "public_license": "公开许可题目",
    "gaokao_licensed": "高考真题（已获授权）",
    "ai_generated": "AI 生成变式（已通过校验）",
}
_JUDGING_NOTES = {
    "partial_no_wrong": (
        "多选题：全部选对才算正确；只选了部分正确选项且没有错选，记为部分正确；只要有错选就记为不正确。"
        "这是练习反馈规则，不代表任何地区的官方评分办法。"
    ),
    "all_or_nothing": (
        "多选题：全部选对才算正确，漏选或错选都记为不正确。这是练习反馈规则，不代表任何地区的官方评分办法。"
    ),
}


@dataclass(frozen=True)
class StudentScope:
    region_code: str | None
    exam_year: int | None
    subjects: tuple[str, ...] = ()


def student_scope(db: Session, student_id: str) -> StudentScope:
    profile = db.get(StudentProfile, student_id)
    if profile is None:
        return StudentScope(None, None)
    return StudentScope(profile.region_code, profile.exam_year, tuple(profile.subjects_json or ()))


def is_engineering_sample(question: Question) -> bool:
    return (
        question.source_type == "self_authored"
        and question.source_license == ENGINEERING_SAMPLE_LICENSE
    )


# ---------------------------------------------------------------- 地区适用性


def approved_tags(
    db: Session, question_ids: list[str]
) -> dict[str, list[QuestionRegionApplicability]]:
    tags: dict[str, list[QuestionRegionApplicability]] = defaultdict(list)
    if not question_ids:
        return tags
    rows = db.scalars(
        select(QuestionRegionApplicability)
        .where(
            QuestionRegionApplicability.question_id.in_(question_ids),
            QuestionRegionApplicability.review_status == "approved",
        )
        .order_by(QuestionRegionApplicability.recommended_region_code)
    )
    for row in rows:
        tags[row.question_id].append(row)
    return tags


def tag_applies(tag: QuestionRegionApplicability, scope: StudentScope) -> bool:
    if scope.region_code is None or tag.recommended_region_code != scope.region_code:
        return False
    if tag.exam_year_from is None and tag.exam_year_to is None:
        return True
    if scope.exam_year is None:
        return False  # 标记限定了年份而学生的考试年份未知：不能跨年份误用
    lower_ok = tag.exam_year_from is None or tag.exam_year_from <= scope.exam_year
    upper_ok = tag.exam_year_to is None or scope.exam_year <= tag.exam_year_to
    return lower_ok and upper_ok


def classify(tags: list[QuestionRegionApplicability], scope: StudentScope) -> str:
    """region：适用于这名学生；general：没有地区标记；other：只适用于别的地区或别的年份。"""
    if not tags:
        return "general"
    return "region" if any(tag_applies(tag, scope) for tag in tags) else "other"


def build_applicability(
    question: Question, tags: list[QuestionRegionApplicability], scope: StudentScope
) -> Applicability:
    if not tags:
        return Applicability(
            scope="general",
            label="全国通用基础题",
            recommended_regions=[],
            origin_region_code=None,
            exam_year_from=None,
            exam_year_to=None,
            disclaimer="通用基础题，不代表任何地区的高考命题风格。",
        )
    primary = next((tag for tag in tags if tag_applies(tag, scope)), tags[0])
    regions = [tag.recommended_region_code for tag in tags]
    names = "、".join(launch.REGION_NAMES.get(code, code) for code in regions)
    sample = is_engineering_sample(question)
    return Applicability(
        scope="region",
        label=f"推荐适用：{names}" + ("（工程测试标签）" if sample else ""),
        recommended_regions=regions,
        origin_region_code=primary.origin_region_code,
        exam_year_from=primary.exam_year_from,
        exam_year_to=primary.exam_year_to,
        disclaimer=(
            "自编工程样题，地区标签仅用于测试筛选，不代表该地区的高考命题规则。"
            if sample
            else "推荐适用地区来自内容审核，不代表该题就是这个地区的高考原题。"
        ),
    )


# ---------------------------------------------------------------- 序列化


def build_source(question: Question) -> QuestionSource:
    sample = is_engineering_sample(question)
    if sample:
        label = "自编工程样题 · 未经学科审校"
    else:
        label = _SOURCE_LABELS.get(question.source_type, "来源待核实")
        if question.source_name:
            label = f"{label} · {question.source_name}"
    return QuestionSource(
        source_type=question.source_type,
        source_category=question.source_category,
        source_name=question.source_name,
        source_year=question.source_year,
        source_license=question.source_license,
        source_url=question.source_url,
        is_engineering_sample=sample,
        label=label,
    )


def knowledge_refs(db: Session, question_ids: list[str]) -> dict[str, list[KnowledgeRef]]:
    refs: dict[str, list[KnowledgeRef]] = defaultdict(list)
    if not question_ids:
        return refs
    rows = db.execute(
        select(QuestionKnowledge.question_id, KnowledgeNode)
        .join(KnowledgeNode, KnowledgeNode.id == QuestionKnowledge.knowledge_id)
        .where(QuestionKnowledge.question_id.in_(question_ids))
        .order_by(KnowledgeNode.code)
    )
    for question_id, node in rows:
        refs[question_id].append(KnowledgeRef(id=node.id, code=node.code, title=node.title))
    return refs


def current_versions(db: Session, questions: list[Question]) -> dict[str, QuestionVersion]:
    if not questions:
        return {}
    wanted = {(q.id, q.version) for q in questions}
    rows = db.scalars(
        select(QuestionVersion).where(QuestionVersion.question_id.in_([q.id for q in questions]))
    )
    return {row.question_id: row for row in rows if (row.question_id, row.version) in wanted}


def get_version(db: Session, question_id: str, version: int) -> QuestionVersion:
    row = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question_id, QuestionVersion.version == version
        )
    )
    if row is None:
        raise not_found()
    return row


def get_published_question(db: Session, question_id: str) -> Question:
    question = db.get(Question, question_id)
    if question is None or question.status != "published":
        raise not_found()
    return question


def get_solution(db: Session, question_id: str, version: int, kind: str) -> Solution | None:
    return db.scalar(
        select(Solution).where(
            Solution.question_id == question_id, Solution.version == version, Solution.kind == kind
        )
    )


def reviewed_fast_solution(db: Session, question_id: str, version: int) -> Solution | None:
    """快速解法只有在审核过、且写明了适用条件时才可用（docs/06 §3）。"""
    solution = get_solution(db, question_id, version, "fast")
    if solution is None or not solution.reviewed:
        return None
    conditions = (solution.conditions_json or {}).get("conditions")
    if not conditions or not (solution.conditions_json or {}).get("boundary"):
        return None
    return solution


def get_rubric(db: Session, question_id: str, version: int) -> dict[str, Any]:
    row = db.scalar(
        select(Rubric).where(Rubric.question_id == question_id, Rubric.version == version)
    )
    return dict(row.rubric_json) if row else {}


def build_assists(db: Session, question: Question, version: QuestionVersion) -> QuestionAssists:
    teaching = version.teaching_json or {}
    standard = get_solution(db, question.id, version.version, "standard")
    return QuestionAssists(
        hint_levels=len(teaching.get("hints") or []),
        has_standard_solution=standard is not None and standard.reviewed,
        has_fast_solution=reviewed_fast_solution(db, question.id, version.version) is not None,
        visual_available=normalized_visual(teaching.get("visual")) is not None,
    )


def _summary_fields(
    question: Question,
    version: QuestionVersion,
    tags: list[QuestionRegionApplicability],
    knowledge: list[KnowledgeRef],
    scope: StudentScope,
) -> dict[str, Any]:
    return {
        "id": question.id,
        "subject": question.subject,
        "type": question.type,
        "answer_mode": question.answer_mode,
        "difficulty": question.difficulty,
        "title": version.content_json.get("title") or "",
        "source": build_source(question),
        "applicability": build_applicability(question, tags, scope),
        "knowledge": knowledge,
        "variant_of": question.variant_of_id,
    }


def serialize_question(db: Session, question: Question, scope: StudentScope) -> QuestionOut:
    version = get_version(db, question.id, question.version)
    tags = approved_tags(db, [question.id])[question.id]
    knowledge = knowledge_refs(db, [question.id])[question.id]
    content = version.content_json
    rubric = get_rubric(db, question.id, version.version)
    judging_note = None
    if question.answer_mode == "multiple_choice":
        judging_note = _JUDGING_NOTES[rubric.get("multi_choice_rule") or "all_or_nothing"]
    return QuestionOut(
        **_summary_fields(question, version, tags, knowledge, scope),
        version=version.version,
        grade=question.grade,
        # 只取渲染题面需要的字段；答案、解法、提示都留在服务端
        content=QuestionContent(
            stem=content["stem"],
            options=content.get("options") or [],
            blanks=content.get("blanks") or [],
            subquestions=content.get("subquestions") or [],
            attachments=content.get("attachments") or [],
        ),
        assists=build_assists(db, question, version),
        judging_note=judging_note,
    )


def summarize(
    db: Session, questions: list[Question], scope: StudentScope
) -> dict[str, QuestionSummary]:
    ids = [q.id for q in questions]
    versions = current_versions(db, questions)
    tags = approved_tags(db, ids)
    knowledge = knowledge_refs(db, ids)
    return {
        q.id: QuestionSummary(
            **_summary_fields(q, versions[q.id], tags[q.id], knowledge[q.id], scope)
        )
        for q in questions
        if q.id in versions
    }


# ---------------------------------------------------------------- 列表


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        offset = json.loads(base64.urlsafe_b64decode(padded.encode()))["o"]
    except (binascii.Error, ValueError, KeyError, TypeError):
        raise ApiError(400, "invalid_cursor", "游标无效，请从第一页重新开始") from None
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ApiError(400, "invalid_cursor", "游标无效，请从第一页重新开始")
    return offset


def deliverable_questions(
    db: Session,
    scope: StudentScope,
    *,
    subject: str | None = None,
    answer_mode: str | None = None,
    source_category: str | None = None,
    scope_filter: str = "all",
) -> list[tuple[Question, str]]:
    """可以发给这名学生的题目及其分类（region / general），地区适用题排在前面。"""
    query = select(Question).where(Question.status == "published")
    if subject is not None:
        query = query.where(Question.subject == subject)
    if answer_mode is not None:
        query = query.where(Question.answer_mode == answer_mode)
    if source_category is not None:
        query = query.where(Question.source_category == source_category)
    questions = list(db.scalars(query))
    tags = approved_tags(db, [q.id for q in questions])
    versions = current_versions(db, questions)

    wanted = {"region", "general"} if scope_filter == "all" else {scope_filter}
    classified = [(q, classify(tags[q.id], scope)) for q in questions if q.id in versions]
    kept = [(q, kind) for q, kind in classified if kind in wanted]
    kept.sort(
        key=lambda item: (
            0 if item[1] == "region" else 1,
            launch.SUBJECT_ORDER.get(item[0].subject, 99),
            item[0].difficulty,
            versions[item[0].id].content_json.get("title") or "",
            item[0].id,
        )
    )
    return kept


def list_questions(
    db: Session,
    scope: StudentScope,
    *,
    subject: str | None,
    answer_mode: str | None,
    source_category: str | None,
    scope_filter: str,
    cursor: str | None,
    limit: int,
) -> QuestionPage:
    offset = decode_cursor(cursor)
    kept = deliverable_questions(
        db,
        scope,
        subject=subject,
        answer_mode=answer_mode,
        source_category=source_category,
        scope_filter=scope_filter,
    )
    page = [q for q, _ in kept[offset : offset + limit]]
    summaries = summarize(db, page, scope)
    next_offset = offset + limit
    return QuestionPage(
        items=[summaries[q.id] for q in page],
        next_cursor=encode_cursor(next_offset) if next_offset < len(kept) else None,
    )
