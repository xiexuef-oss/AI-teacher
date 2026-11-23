from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.deps import Ctx
from tutor_api.errors import ApiError, conflict, not_found, unprocessable
from tutor_api.models import (
    AuditLog,
    ContentFactoryQuestionType,
    ContentFactoryQuestionTypeKnowledge,
    KnowledgeNode,
)
from tutor_api.schemas import RegionCode, Subject


class QuestionTypeKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_id: UUID
    relation: Literal["primary", "prerequisite", "supporting"]


class QuestionTypeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=90, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1, max_length=200)
    subject: Subject
    province_code: RegionCode | None = None
    exam_year: int | None = Field(default=None, ge=1, le=9999)
    curriculum_version: str | None = Field(default=None, min_length=1, max_length=80)
    specification: dict[str, JsonValue]
    knowledge: list[QuestionTypeKnowledge] = Field(min_length=1, max_length=50)


class QuestionTypeReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["approve", "deprecate"]
    notes: str = Field(min_length=1, max_length=1000)


def review_question_type(ctx: Ctx, type_id: str, review: QuestionTypeReview) -> dict:
    db = ctx.db
    if db.get_bind().dialect.name == "sqlite":
        db.execute(
            update(ContentFactoryQuestionType)
            .where(ContentFactoryQuestionType.id == type_id)
            .values(status=ContentFactoryQuestionType.status)
        )
    item = db.get(ContentFactoryQuestionType, type_id, with_for_update=True)
    if item is None:
        raise not_found()
    if item.created_by == ctx.actor_id:
        raise ApiError(403, "forbidden", "不得审校本人创建的题型")
    before, after = (
        ("draft", "approved") if review.decision == "approve" else ("approved", "deprecated")
    )
    if item.status != before:
        raise conflict("content_factory_type_state_conflict", "当前题型状态不允许此操作")
    item.status = after
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=ctx.actor_id,
            action="content_factory_question_type_reviewed",
            target_type="cf_question_type",
            target_id=type_id,
            request_id=ctx.request_id,
            detail_json={"previous_status": before, "status": after, "notes": review.notes},
            created_at=ctx.now(),
        )
    )
    return question_type_detail(db, type_id)


def list_knowledge_nodes(db: Session, subject: Subject) -> list[dict[str, str]]:
    rows = db.execute(
        select(KnowledgeNode.id, KnowledgeNode.code, KnowledgeNode.title)
        .where(KnowledgeNode.subject == subject)
        .order_by(KnowledgeNode.code)
    )
    return [{"id": node_id, "code": code, "title": title} for node_id, code, title in rows]


def question_type_detail(db: Session, type_id: str) -> dict:
    item = db.get(ContentFactoryQuestionType, type_id)
    if item is None:
        raise not_found()
    link = ContentFactoryQuestionTypeKnowledge
    links = db.execute(
        select(link.knowledge_id, link.relation)
        .join(KnowledgeNode, KnowledgeNode.id == link.knowledge_id)
        .where(link.question_type_id == type_id)
        .order_by(KnowledgeNode.code, link.relation)
    )
    return {
        "id": item.id,
        "status": item.status,
        "definition": {
            "code": item.code,
            "title": item.title,
            "subject": item.subject,
            "province_code": item.province_code,
            "exam_year": item.exam_year,
            "curriculum_version": item.curriculum_version,
            "specification": item.specification_json,
            "knowledge": [{"knowledge_id": node, "relation": relation} for node, relation in links],
        },
    }


def create_question_type(ctx: Ctx, draft: QuestionTypeDraft) -> ContentFactoryQuestionType:
    links = {(str(link.knowledge_id), link.relation) for link in draft.knowledge}
    if len(links) != len(draft.knowledge):
        raise unprocessable("knowledge", "知识点关联不能重复")
    ids = {knowledge_id for knowledge_id, _ in links}
    matching = set(
        ctx.db.scalars(
            select(KnowledgeNode.id).where(
                KnowledgeNode.id.in_(ids), KnowledgeNode.subject == draft.subject
            )
        )
    )
    if matching != ids:
        raise unprocessable("knowledge", "请选择本学科的现有知识点")
    now = ctx.now()
    question_type = ContentFactoryQuestionType(
        id=new_id(),
        code=draft.code,
        title=draft.title,
        subject=draft.subject,
        province_code=draft.province_code,
        exam_year=draft.exam_year,
        curriculum_version=draft.curriculum_version,
        specification_json=draft.specification,
        status="draft",
        created_by=ctx.actor_id,
        created_at=now,
    )
    try:
        with ctx.db.begin_nested():
            ctx.db.add(question_type)
            ctx.db.flush()
    except IntegrityError:
        existing = ctx.db.scalar(
            select(ContentFactoryQuestionType.id)
            .where(ContentFactoryQuestionType.code == draft.code)
            .with_for_update()
        )
        if existing is not None:
            raise conflict("content_factory_type_code_exists", "该题型编码已存在") from None
        raise
    ctx.db.add_all(
        ContentFactoryQuestionTypeKnowledge(
            question_type_id=question_type.id, knowledge_id=node, relation=relation
        )
        for node, relation in sorted(links)
    )
    ctx.db.add(
        AuditLog(
            id=new_id(),
            actor_id=ctx.actor_id,
            action="content_factory_question_type_created",
            target_type="cf_question_type",
            target_id=question_type.id,
            request_id=ctx.request_id,
            created_at=now,
        )
    )
    return question_type
