"""内容审核（PRD P0 第 9 条、docs/07 §4）。

题目 draft → reviewed → published，可撤回（withdrawn，终态）：

- approve：draft → reviewed，由独立的审校员确认标准解法（快速解法要单独列出才算确认）；
- reject：draft / reviewed → draft，必须写原因，已审核的标记全部撤销；
- publish：reviewed → published，上线前再做一次程序校验；
- withdraw：published → withdrawn，必须写原因，学生立即看不到。

约束：提交内容的人不能 approve 或 publish 自己的题；用 `expected_version` 防止审核人批准了自己没看到的版本；
approve / publish 之前先过程序校验（与样题入库同一套，`content_seed.check_question`）；
每次决策都写审计日志（谁、从哪个状态到哪个状态、哪个版本、为什么），不含任何学生数据。

学生端只认 `status == published`（question_service），所以这里改完状态，学生端的可见性立刻跟着变。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tutor_api.db import new_id
from tutor_api.errors import ApiError, conflict, not_found, unprocessable
from tutor_api.models import (
    AuditLog,
    KnowledgeNode,
    Question,
    QuestionKnowledge,
    QuestionRegionApplicability,
    QuestionVersion,
    Rubric,
    Solution,
)
from tutor_api.schemas import (
    AdminAnswer,
    AdminHistoryEntry,
    AdminQuestionDetail,
    AdminQuestionEditIn,
    AdminQuestionPage,
    AdminQuestionSummary,
    AdminQuestionVersion,
    AdminRegionTag,
    AdminSolution,
    AdminStatusCounts,
    AdminTeaching,
    AdminVersionSnapshot,
    AdminVisual,
    QuestionContent,
    QuestionReviewStateOut,
    ReviewDecisionIn,
)
from tutor_api.services import content_seed, question_service

STATUSES = ("draft", "reviewed", "published", "withdrawn")
# 决策 → (允许从哪些状态出发, 到哪个状态)
TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "approve": (frozenset({"draft"}), "reviewed"),
    "reject": (frozenset({"draft", "reviewed"}), "draft"),
    "publish": (frozenset({"reviewed"}), "published"),
    "withdraw": (frozenset({"published"}), "withdrawn"),
}
COMMENT_REQUIRED = frozenset({"reject", "withdraw"})
INDEPENDENT_REVIEW = frozenset({"approve", "publish"})  # 提交者不能自己放行的两步
AUDIT_PREFIX = "question.review."
EDIT_ACTION = "question.edit"
# 已上线的内容不会被悄悄改掉：要改先下线（下线之后可以改，新版本回到 draft 重新走审核）
EDITABLE_FROM = frozenset({"draft", "reviewed", "withdrawn"})
# 一次修改里"改动了哪些部分"的名字，也是比较的顺序
EDIT_PARTS = (
    "title",
    "difficulty",
    "grade",
    "content",
    "answer",
    "teaching",
    "solutions",
    "knowledge",
    "rubric",
)


# ---------------------------------------------------------------- 程序校验


def _solutions(db: Session, question_id: str, version: int) -> dict[str, Solution]:
    rows = db.scalars(
        select(Solution).where(Solution.question_id == question_id, Solution.version == version)
    )
    return {row.kind: row for row in rows}


def _seed_shape(
    db: Session,
    question: Question,
    version: QuestionVersion,
    solutions: dict[str, Solution],
    knowledge: list[KnowledgeNode],
) -> dict[str, Any]:
    """把库里的一道题还原成样题种子的形状，好让入库用的校验直接适用。"""
    content, answer = version.content_json, version.answer_json
    teaching = version.teaching_json or {}
    seed_solutions: dict[str, Any] = {}
    for kind, row in solutions.items():
        entry = dict(row.content_json)
        if kind == "fast":
            entry["conditions"] = (row.conditions_json or {}).get("conditions")
            entry["boundary"] = (row.conditions_json or {}).get("boundary")
        seed_solutions[kind] = entry
    tags = db.scalars(
        select(QuestionRegionApplicability).where(
            QuestionRegionApplicability.question_id == question.id
        )
    )
    return {
        "key": question.id,
        "subject": question.subject,
        "type": question.type,
        "answer_mode": question.answer_mode,
        "difficulty": question.difficulty,
        "grade": question.grade,
        "title": content.get("title"),
        "knowledge": [node.code for node in knowledge],
        "content": {
            "stem": content.get("stem"),
            "options": content.get("options") or [],
            "blanks": content.get("blanks") or [],
            "subquestions": content.get("subquestions") or [],
        },
        "answer": {
            "value": answer.get("value"),
            "equivalence_rules": answer.get("equivalence_rules") or {},
            "units": answer.get("units") or {},
        },
        "teaching": teaching,
        "solutions": seed_solutions,
        "rubric": _rubric(db, question.id, version.version),
        "region_tags": [
            {
                "region": tag.recommended_region_code,
                "exam_year_from": tag.exam_year_from,
                "exam_year_to": tag.exam_year_to,
            }
            for tag in tags
        ],
    }


def _rubric(db: Session, question_id: str, version: int) -> dict[str, Any]:
    return question_service.get_rubric(db, question_id, version)


def check_problems(db: Session, question: Question) -> list[str]:
    """程序校验发现的问题；空列表表示通过。"""
    version = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question.id, QuestionVersion.version == question.version
        )
    )
    if version is None:
        return [f"{question.id}: 找不到当前版本（{question.version}）的内容"]
    knowledge = list(
        db.scalars(
            select(KnowledgeNode)
            .join(QuestionKnowledge, QuestionKnowledge.knowledge_id == KnowledgeNode.id)
            .where(QuestionKnowledge.question_id == question.id)
            .order_by(KnowledgeNode.code)
        )
    )
    shaped = _seed_shape(
        db, question, version, _solutions(db, question.id, version.version), knowledge
    )
    nodes = {node.code: {"subject": node.subject} for node in knowledge}
    problems = content_seed.check_question(
        shaped, nodes, {}, forbid_exam_claims=question_service.is_engineering_sample(question)
    )
    if question.variant_of_id is not None:
        base = db.get(Question, question.variant_of_id)
        if base is None:
            problems.append(f"{question.id}: variant_of 指向不存在的题")
        elif base.variant_of_id is not None:
            problems.append(f"{question.id}: variant_of 指向的题本身是变式")
        elif base.subject != question.subject:
            problems.append(f"{question.id}: variant_of 指向的题学科不同")
    return problems


# ---------------------------------------------------------------- 队列与详情


def _summaries(db: Session, questions: list[Question]) -> list[AdminQuestionSummary]:
    versions = question_service.current_versions(db, questions)

    def title_of(question: Question) -> str:
        version = versions.get(question.id)
        return (version.content_json.get("title") or "") if version else ""

    return [
        AdminQuestionSummary(
            id=q.id,
            subject=q.subject,
            type=q.type,
            answer_mode=q.answer_mode,
            difficulty=q.difficulty,
            title=title_of(q),
            status=q.status,
            version=q.version,
            source=question_service.build_source(q),
            created_by=q.created_by,
            reviewed_by=q.reviewed_by,
            published_at=q.published_at,
            updated_at=q.updated_at,
        )
        for q in questions
    ]


def list_questions(
    db: Session,
    *,
    status: str | None,
    subject: str | None,
    source_category: str | None,
    cursor: str | None,
    limit: int,
) -> AdminQuestionPage:
    offset = question_service.decode_cursor(cursor)
    filters = []
    if subject is not None:
        filters.append(Question.subject == subject)
    if source_category is not None:
        filters.append(Question.source_category == source_category)

    counts = dict.fromkeys(STATUSES, 0)
    for state, total in db.execute(
        select(Question.status, func.count()).where(*filters).group_by(Question.status)
    ):
        if state in counts:
            counts[state] = total

    query = select(Question).where(*filters)
    if status is not None:
        query = query.where(Question.status == status)
    rows = list(
        db.scalars(
            query.order_by(Question.updated_at.desc(), Question.id).offset(offset).limit(limit + 1)
        )
    )
    page = rows[:limit]
    return AdminQuestionPage(
        items=_summaries(db, page),
        next_cursor=question_service.encode_cursor(offset + limit) if len(rows) > limit else None,
        status_counts=AdminStatusCounts(**counts),
    )


def _history(db: Session, question_id: str) -> list[AdminHistoryEntry]:
    rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.target_type == "question",
            AuditLog.target_id == question_id,
            AuditLog.action.like("question.%"),
        )
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    entries = []
    for row in rows:
        detail = row.detail_json or {}
        is_edit = row.action == EDIT_ACTION
        entries.append(
            AdminHistoryEntry(
                id=row.id,
                action="edit" if is_edit else row.action.removeprefix(AUDIT_PREFIX),
                actor_id=row.actor_id,
                from_status=detail.get("from"),
                to_status=detail.get("to"),
                version=detail.get("version"),
                comment=detail.get("comment"),
                changes=list(detail.get("changes") or []) if is_edit else None,
                created_at=row.created_at,
            )
        )
    return entries


# ---------------------------------------------------------------- 泄题标记


def _full_markers(answer_mode: str, answer: dict[str, Any], extra: list[str]) -> list[str]:
    """库里存的完整标记 = 审校员补的 + 由答案推出来的（与样题入库同一个算法）。"""
    shaped = {
        "answer_mode": answer_mode,
        "answer": {
            "value": answer.get("value"),
            "equivalence_rules": answer.get("equivalence_rules") or {},
        },
        "teaching": {"leak_markers": list(extra)},
    }
    try:
        markers = content_seed.leak_markers(shaped)
    except (KeyError, TypeError, AttributeError):
        markers = list(extra)  # 答案的形状不对：程序校验会指出来，这里不让保存失败
    return list(dict.fromkeys(markers))


def _custom_markers(question: Question, version: QuestionVersion) -> list[str]:
    """审校员补充的标记：库里存的完整标记，去掉由答案自动推出的那部分。"""
    stored = list((version.teaching_json or {}).get("leak_markers") or [])
    automatic = set(_full_markers(question.answer_mode, version.answer_json, []))
    return [marker for marker in dict.fromkeys(stored) if marker not in automatic]


def _admin_solution(row: Solution) -> AdminSolution:
    conditions = row.conditions_json or {}
    is_fast = row.kind == "fast"
    return AdminSolution(
        kind=row.kind,
        steps=list(row.content_json.get("steps") or []),
        final_answer=str(row.content_json.get("final_answer") or ""),
        key_points=list(row.content_json.get("key_points") or []),
        conditions=list(conditions.get("conditions") or []) if is_fast else None,
        boundary=conditions.get("boundary") if is_fast else None,
        reviewed=row.reviewed,
        reviewed_by=row.reviewed_by,
    )


def _admin_teaching(question: Question, version: QuestionVersion) -> AdminTeaching:
    teaching = version.teaching_json or {}
    visual = teaching.get("visual")
    return AdminTeaching(
        concept=teaching.get("concept"),
        hints=list(teaching.get("hints") or []),
        concept_rephrase=teaching.get("concept_rephrase"),
        option_analysis=dict(teaching.get("option_analysis") or {}),
        visual=(
            AdminVisual(
                template_id=visual["template_id"],
                params=visual.get("params") or {},
                caption=visual.get("caption") or "",
            )
            if visual
            else None
        ),
        leak_markers=_custom_markers(question, version),
    )


def _knowledge_codes(db: Session, question_id: str) -> list[str]:
    return sorted(
        node.code for node in question_service.knowledge_refs(db, [question_id])[question_id]
    )


def version_snapshot(db: Session, question_id: str, version_no: int) -> AdminVersionSnapshot:
    """某一个版本的完整内容，回看和对比用。

    题面、答案、教学辅助、解法、评分细则本来就按版本存。难度、年级、知识点原来只在题目行和关联表里，
    修改题目会覆盖它们，所以修改时把它们记进旧版本、新值记进新版本（content_json 里）：
    当前版本以题目现在的状态为准（二者一致）；旧版本用当时记下的值，早于这个改动的版本没有，回退到现在的值。
    """
    question = db.get(Question, question_id)
    if question is None:
        raise not_found()
    version = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question.id, QuestionVersion.version == version_no
        )
    )
    if version is None:
        raise not_found()
    current = version.version == question.version
    content, answer = version.content_json, version.answer_json
    solutions = _solutions(db, question.id, version.version)

    def stored(key: str, fallback):
        return fallback if current or key not in content else content[key]

    return AdminVersionSnapshot(
        question_id=question.id,
        version=version.version,
        is_current=current,
        created_by=version.created_by,
        created_at=version.created_at,
        title=content.get("title") or "",
        difficulty=stored("difficulty", question.difficulty),
        grade=stored("grade", question.grade),
        content=QuestionContent(
            stem=content["stem"],
            options=content.get("options") or [],
            blanks=content.get("blanks") or [],
            subquestions=content.get("subquestions") or [],
            attachments=content.get("attachments") or [],
        ),
        answer=AdminAnswer(
            value=answer.get("value"),
            equivalence_rules=answer.get("equivalence_rules") or {},
            units=answer.get("units") or {},
        ),
        teaching=_admin_teaching(question, version),
        solutions=[
            _admin_solution(solutions[kind]) for kind in ("standard", "fast") if kind in solutions
        ],
        knowledge=list(
            stored("knowledge", None)
            if not current and "knowledge" in content
            else _knowledge_codes(db, question.id)
        ),
        rubric=_rubric(db, question.id, version.version),
    )


def question_detail(db: Session, question_id: str) -> AdminQuestionDetail:
    question = db.get(Question, question_id)
    if question is None:
        raise not_found()
    version = question_service.get_version(db, question.id, question.version)
    content, answer = version.content_json, version.answer_json
    solutions = _solutions(db, question.id, version.version)
    tags = db.scalars(
        select(QuestionRegionApplicability)
        .where(QuestionRegionApplicability.question_id == question.id)
        .order_by(QuestionRegionApplicability.recommended_region_code)
    )
    all_versions = db.scalars(
        select(QuestionVersion)
        .where(QuestionVersion.question_id == question.id)
        .order_by(QuestionVersion.version)
    )
    return AdminQuestionDetail(
        id=question.id,
        subject=question.subject,
        type=question.type,
        answer_mode=question.answer_mode,
        difficulty=question.difficulty,
        grade=question.grade,
        title=content.get("title") or "",
        status=question.status,
        version=question.version,
        source=question_service.build_source(question),
        variant_of=question.variant_of_id,
        created_by=question.created_by,
        reviewed_by=question.reviewed_by,
        published_at=question.published_at,
        updated_at=question.updated_at,
        content=QuestionContent(
            stem=content["stem"],
            options=content.get("options") or [],
            blanks=content.get("blanks") or [],
            subquestions=content.get("subquestions") or [],
            attachments=content.get("attachments") or [],
        ),
        answer=AdminAnswer(
            value=answer.get("value"),
            equivalence_rules=answer.get("equivalence_rules") or {},
            units=answer.get("units") or {},
        ),
        teaching=_admin_teaching(question, version),
        solutions=[
            _admin_solution(solutions[kind]) for kind in ("standard", "fast") if kind in solutions
        ],
        rubric=_rubric(db, question.id, version.version),
        knowledge=question_service.knowledge_refs(db, [question.id])[question.id],
        region_tags=[
            AdminRegionTag(
                recommended_region_code=tag.recommended_region_code,
                origin_region_code=tag.origin_region_code,
                exam_year_from=tag.exam_year_from,
                exam_year_to=tag.exam_year_to,
                review_status=tag.review_status,
                note=tag.note,
            )
            for tag in tags
        ],
        check_problems=check_problems(db, question),
        versions=[
            AdminQuestionVersion(
                version=v.version, created_by=v.created_by, created_at=v.created_at
            )
            for v in all_versions
        ],
        history=_history(db, question.id),
    )


# ---------------------------------------------------------------- 决策


def _require_confirmable(available: dict[str, Solution], kinds: list[str]) -> None:
    """approve 要确认的解法：必须包含标准解法，且每一种都真的存在。"""
    if "standard" not in kinds:
        raise ApiError(422, "solution_not_confirmed", "二审必须确认标准解法")
    missing = [kind for kind in kinds if kind not in available]
    if missing:
        raise ApiError(
            422,
            "solution_not_confirmed",
            f"这道题没有{'、'.join(missing)}解法，不能确认",
            {"kinds": missing},
        )


def _audit_time(db: Session, question_id: str, now: datetime) -> datetime:
    """同一道题的审计记录时间严格递增：审计表的 ID 是随机 UUID，时间相同就排不出先后（历史会乱序）。"""
    last = db.scalar(
        select(func.max(AuditLog.created_at)).where(
            AuditLog.target_type == "question", AuditLog.target_id == question_id
        )
    )
    if last is not None and last >= now:
        return last + timedelta(milliseconds=1)
    return now


def decide(
    db: Session,
    *,
    actor_id: str,
    question_id: str,
    body: ReviewDecisionIn,
    now: datetime,
    request_id: str,
) -> QuestionReviewStateOut:
    question = db.get(Question, question_id)
    if question is None:
        raise not_found()
    if body.expected_version != question.version:
        raise conflict(
            "version_conflict",
            f"题目已经是第 {question.version} 版，你看到的是第 {body.expected_version} 版，请刷新后再审",
            {"current_version": question.version},
        )

    allowed_from, target = TRANSITIONS[body.decision]
    before = question.status
    if before not in allowed_from:
        raise conflict(
            "invalid_transition",
            f"题目现在是 {before} 状态，不能执行 {body.decision}",
            {"status": before, "decision": body.decision},
        )

    comment = (body.comment or "").strip() or None
    if body.decision in COMMENT_REQUIRED and comment is None:
        raise ApiError(422, "comment_required", f"{body.decision} 必须写明原因")

    if (
        body.decision in INDEPENDENT_REVIEW
        and question.created_by is not None
        and question.created_by == actor_id
    ):
        raise ApiError(
            403, "self_review_forbidden", "提交内容的人不能审核自己的题，请换另一位审校员"
        )

    confirmed: list[str] = []
    if body.decision in INDEPENDENT_REVIEW:
        problems = check_problems(db, question)
        if problems:
            raise ApiError(
                422,
                "content_checks_failed",
                f"程序校验发现 {len(problems)} 个问题，修改后才能{body.decision}",
                {"problems": problems},
            )

    solutions = _solutions(db, question.id, question.version)
    if body.decision == "approve":
        confirmed = list(dict.fromkeys(body.solution_kinds or ["standard"]))
        _require_confirmable(solutions, confirmed)
        for kind, row in solutions.items():
            row.reviewed = kind in confirmed
            row.reviewed_by = actor_id if kind in confirmed else None
        question.reviewed_by = actor_id
    elif body.decision == "publish":
        standard = solutions.get("standard")
        if standard is None or not standard.reviewed:
            raise ApiError(422, "solution_not_confirmed", "标准解法还没有经过审核确认，不能上线")
        question.published_at = now
    elif body.decision == "reject":
        for row in solutions.values():
            row.reviewed = False
            row.reviewed_by = None
        question.reviewed_by = None

    question.status = target
    question.updated_at = now
    detail: dict[str, Any] = {
        "from": before,
        "to": target,
        "version": question.version,
        "comment": comment,
    }
    if body.decision == "approve":
        detail["solution_kinds"] = confirmed
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=actor_id,
            action=f"{AUDIT_PREFIX}{body.decision}",
            target_type="question",
            target_id=question.id,
            detail_json=detail,
            request_id=request_id,
            created_at=_audit_time(db, question.id, now),
        )
    )
    db.flush()
    return QuestionReviewStateOut(
        question_id=question.id,
        status=question.status,
        version=question.version,
        reviewed_by=question.reviewed_by,
        updated_at=question.updated_at,
    )


# ---------------------------------------------------------------- 修改题目（产生新版本）


def _solution_view(
    kind: str, steps, final_answer, key_points, conditions, boundary
) -> dict[str, Any]:
    """解法在"比较"和"保存"里的统一表示：标准解法没有适用条件，快速解法的条件缺省为空列表。"""
    is_fast = kind == "fast"
    return {
        "kind": kind,
        "steps": list(steps),
        "final_answer": final_answer,
        "key_points": list(key_points),
        "conditions": list(conditions or []) if is_fast else None,
        "boundary": boundary if is_fast else None,
    }


def _editable_snapshot(db: Session, question: Question, version: QuestionVersion) -> dict[str, Any]:
    """当前版本里"可以被修改"的部分，按详情接口给出的表示整理好，用来和一次修改请求做比较。"""
    content, answer = version.content_json, version.answer_json
    solutions = _solutions(db, question.id, version.version)
    return {
        "title": content.get("title") or "",
        "difficulty": question.difficulty,
        "grade": question.grade,
        "content": QuestionContent(
            stem=content["stem"],
            options=content.get("options") or [],
            blanks=content.get("blanks") or [],
            subquestions=content.get("subquestions") or [],
            attachments=content.get("attachments") or [],
        ).model_dump(),
        "answer": AdminAnswer(
            value=answer.get("value"),
            equivalence_rules=answer.get("equivalence_rules") or {},
            units=answer.get("units") or {},
        ).model_dump(),
        "teaching": _admin_teaching(question, version).model_dump(),
        "solutions": [
            _solution_view(
                kind,
                row.content_json.get("steps") or [],
                str(row.content_json.get("final_answer") or ""),
                row.content_json.get("key_points") or [],
                (row.conditions_json or {}).get("conditions"),
                (row.conditions_json or {}).get("boundary"),
            )
            for kind, row in sorted(solutions.items())
        ],
        "knowledge": sorted(
            node.code for node in question_service.knowledge_refs(db, [question.id])[question.id]
        ),
        "rubric": _rubric(db, question.id, version.version),
    }


def _request_snapshot(body: AdminQuestionEditIn) -> dict[str, Any]:
    return {
        "title": body.title,
        "difficulty": body.difficulty,
        "grade": body.grade,
        "content": QuestionContent(**body.content.model_dump()).model_dump(),
        "answer": AdminAnswer(**body.answer.model_dump()).model_dump(),
        "teaching": AdminTeaching(**body.teaching.model_dump()).model_dump(),
        "solutions": sorted(
            (
                _solution_view(
                    item.kind,
                    item.steps,
                    item.final_answer,
                    item.key_points,
                    item.conditions,
                    item.boundary,
                )
                for item in body.solutions
            ),
            key=lambda view: view["kind"],
        ),
        "knowledge": sorted(set(body.knowledge)),
        "rubric": body.rubric,
    }


def create_version(
    db: Session,
    *,
    actor_id: str,
    question_id: str,
    body: AdminQuestionEditIn,
    now: datetime,
    request_id: str,
) -> AdminQuestionDetail:
    question = db.get(Question, question_id)
    if question is None:
        raise not_found()
    if body.expected_version != question.version:
        raise conflict(
            "version_conflict",
            f"题目已经是第 {question.version} 版，你看到的是第 {body.expected_version} 版，请刷新后再改",
            {"current_version": question.version},
        )
    before_status = question.status
    if before_status not in EDITABLE_FROM:
        raise conflict(
            "invalid_transition",
            f"题目现在是 {before_status} 状态，已上线的题要先下线才能修改",
            {"status": before_status, "decision": "edit"},
        )

    codes = list(dict.fromkeys(body.knowledge))
    nodes = {
        node.code: node
        for node in db.scalars(
            select(KnowledgeNode).where(
                KnowledgeNode.subject == question.subject, KnowledgeNode.code.in_(codes)
            )
        )
    }
    missing = [code for code in codes if code not in nodes]
    if missing:
        raise unprocessable(
            "knowledge", f"知识点不存在，或不属于这道题的学科：{'、'.join(missing)}"
        )
    kinds = [item.kind for item in body.solutions]
    if len(set(kinds)) != len(kinds):
        raise unprocessable("solutions", "同一种解法只能有一个")

    previous = question_service.get_version(db, question.id, question.version)
    before, after = _editable_snapshot(db, question, previous), _request_snapshot(body)
    changes = [part for part in EDIT_PARTS if before[part] != after[part]]
    if not changes:
        raise ApiError(422, "no_changes", "没有任何改动，不产生新版本")

    # 难度、年级、知识点原来只在题目行和关联表里，下面会把它们覆盖掉：先记进旧版本，回看和对比才不会丢
    snapshot_keys = {key: before[key] for key in ("difficulty", "grade", "knowledge")}
    previous.content_json = {**snapshot_keys, **previous.content_json}

    new_version = question.version + 1
    content = body.content
    answer = {
        "value": body.answer.value,
        "equivalence_rules": body.answer.equivalence_rules,
        "units": body.answer.units,
    }
    teaching: dict[str, Any] = {"hints": list(body.teaching.hints)}
    if body.teaching.concept is not None:
        teaching["concept"] = body.teaching.concept
    if body.teaching.concept_rephrase is not None:
        teaching["concept_rephrase"] = body.teaching.concept_rephrase
    if body.teaching.option_analysis:
        teaching["option_analysis"] = dict(body.teaching.option_analysis)
    if body.teaching.visual is not None:
        teaching["visual"] = body.teaching.visual.model_dump()
    # 标记要跟着新答案重新算：旧答案推出的标记留着，会让提示里的新答案漏过去
    teaching["leak_markers"] = _full_markers(
        question.answer_mode, answer, list(body.teaching.leak_markers)
    )

    db.add(
        QuestionVersion(
            id=new_id(),
            question_id=question.id,
            version=new_version,
            content_json={
                "title": body.title,
                "stem": content.stem,
                "options": [item.model_dump() for item in content.options],
                "blanks": [item.model_dump() for item in content.blanks],
                "subquestions": [item.model_dump() for item in content.subquestions],
                "attachments": [item.model_dump() for item in content.attachments],
                "difficulty": body.difficulty,
                "grade": body.grade,
                "knowledge": sorted(codes),
            },
            answer_json=answer,
            teaching_json=teaching,
            created_by=actor_id,
            created_at=now,
        )
    )
    for item in body.solutions:
        is_fast = item.kind == "fast"
        db.add(
            Solution(
                id=new_id(),
                question_id=question.id,
                version=new_version,
                kind=item.kind,
                content_json={
                    "steps": list(item.steps),
                    "final_answer": item.final_answer,
                    "key_points": list(item.key_points),
                },
                conditions_json=(
                    {"conditions": list(item.conditions or []), "boundary": item.boundary}
                    if is_fast
                    else None
                ),
                reviewed=False,  # 新版本的解法一律重新审核
                reviewed_by=None,
                created_at=now,
            )
        )
    db.add(
        Rubric(
            id=new_id(),
            question_id=question.id,
            version=new_version,
            rubric_json=body.rubric,
            created_at=now,
        )
    )
    db.execute(delete(QuestionKnowledge).where(QuestionKnowledge.question_id == question.id))
    for code in codes:
        db.add(QuestionKnowledge(question_id=question.id, knowledge_id=nodes[code].id))

    question.version = new_version
    question.status = "draft"
    question.reviewed_by = None
    question.published_at = None
    question.created_by = actor_id  # 改的人成为新版本的提交者，不能自己二审
    question.difficulty = body.difficulty
    question.grade = body.grade
    question.updated_at = now

    comment = (body.comment or "").strip() or None
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=actor_id,
            action=EDIT_ACTION,
            target_type="question",
            target_id=question.id,
            detail_json={
                "from": before_status,
                "to": "draft",
                "version": new_version,
                "previous_version": new_version - 1,
                "comment": comment,
                "changes": changes,
            },
            request_id=request_id,
            created_at=_audit_time(db, question.id, now),
        )
    )
    db.flush()
    return question_detail(db, question.id)
