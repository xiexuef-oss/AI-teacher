"""教学编排器（docs/06）：决定教学状态和下一步动作，产出教学事件。它不修改成绩。

内容来源的优先级：审核内容 → 模型网关 → 规则降级。
- 分层提示、常规与快速解法、图解都直接引用审核内容，不调用模型；
- 只有"换种讲法"在题目没有审核文案时才走模型网关；
- 网关不可用或输出没过校验时下发 `fallback` 事件，状态进入 FALLBACK，不编造内容。

独立作答的保护：
- 提示每次只给下一层；
- 提交之前看解析必须显式确认结束独立作答，并记入会话；
- 复测会话在提交之前不提供任何辅助。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_gateway import Constraints, GatewayRequest, InputPart, ModelGateway, TaskType
from tutor_api.errors import conflict
from tutor_api.models import (
    KnowledgeEdge,
    KnowledgeNode,
    Question,
    QuestionKnowledge,
    QuestionVersion,
    StudySession,
)
from tutor_api.schemas import TutorActionIn, TutorStep
from tutor_api.services import (
    content_references,
    events,
    question_service,
    review_scheduler,
    session_service,
)
from tutor_api.settings import Settings
from tutor_api.timefmt import iso
from tutor_api.visuals import normalized_visual

_FALLBACK_REASONS = {
    "MODEL_UNAVAILABLE",
    "SCHEMA_INVALID",
    "BUDGET_EXCEEDED",
    "TIMEOUT",
    "CONTENT_BLOCKED",
}


@dataclass
class TutorContext:
    db: Session
    settings: Settings
    gateway: ModelGateway
    student_id: str
    pseudonym: str
    request_id: str
    now: datetime
    allow_gateway: bool = True


@dataclass
class _Turn:
    """一次教学动作里反复用到的东西。"""

    tc: TutorContext
    session: StudySession
    question: Question
    version: QuestionVersion
    teaching: dict[str, Any]
    submitted: int
    body: TutorActionIn

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        state_after: str | None = None,
        source: str = "reviewed_content",
        **meta: Any,
    ) -> dict[str, Any]:
        targets = []
        if event_type == "hint":
            targets = [
                "rephrase" if payload.get("style") == "rephrase" else f"hint:{payload['level']}"
            ]
        elif event_type in {"standard", "fast"}:
            targets = [
                f"solution:{event_type}:step:{i}"
                for i in range(1, len(payload.get("steps", [])) + 1)
            ]
        elif event_type == "visual":
            targets = ["visual:caption"]
        if source != "model" and targets and "references" not in meta:
            meta["references"] = content_references.catalog(self, targets)
        return events.append_event(
            self.tc.db,
            self.session,
            event_type=event_type,
            payload=payload,
            state_after=state_after or self.session.state,
            source=source,
            request_id=self.tc.request_id,
            now=self.tc.now,
            **meta,
        )

    def notice(
        self, code: str, text: str, *, state_after: str | None = None, due_at: str | None = None
    ) -> dict:
        return self.emit(
            "notice",
            {"code": code, "text": text, "due_at": due_at},
            state_after=state_after,
            source="rule_engine",
        )

    @property
    def hints(self) -> list[str]:
        return self.teaching.get("hints") or []

    @property
    def visual(self) -> dict[str, Any] | None:
        return normalized_visual(self.teaching.get("visual"))


# ---------------------------------------------------------------- 门控


def _block_in_retest(turn: _Turn) -> None:
    if turn.session.origin == "review" and turn.submitted == 0:
        raise conflict(
            "hints_disabled_in_retest", "复测要求不看提示独立完成，提交之后才能查看提示和解析"
        )


def _require_independent_ended(turn: _Turn) -> None:
    """提交之前查看解析：必须由学生明确选择结束独立作答（docs/03 P04 验收）。"""
    if turn.submitted > 0 or turn.session.independent_ended:
        return
    if not turn.body.confirm_end_independent:
        raise conflict(
            "independent_attempt_in_progress",
            "还没有提交作答。查看解析会结束独立作答，需要明确确认。",
            {"confirm_field": "confirm_end_independent"},
        )
    turn.session.independent_ended = True


# ---------------------------------------------------------------- 提示、解析、图解


def _request_hint(turn: _Turn) -> list[dict]:
    _block_in_retest(turn)
    session = turn.session
    if session.hint_level_revealed >= len(turn.hints):
        text = (
            "这道题的提示已经全部给出了。可以再试一次，或者查看常规解法。"
            if turn.hints
            else "这道题没有准备分层提示，可以看图理解或查看常规解法。"
        )
        return [turn.notice("hints_exhausted", text)]

    level = session.hint_level_revealed + 1
    session.hint_level_revealed = level
    session.assisted = True
    payload = {
        "level": level,
        "total_levels": len(turn.hints),
        "style": "layered",
        "text": turn.hints[level - 1],
        "concept": turn.teaching.get("concept"),
    }
    return [turn.emit("hint", payload, state_after="HINTED")]


def _option_analysis(turn: _Turn) -> list[dict[str, str]]:
    if turn.question.answer_mode not in {"single_choice", "multiple_choice"}:
        return []
    correct = set(turn.version.answer_json.get("value") or [])
    analysis = turn.teaching.get("option_analysis") or {}
    return [
        {
            "key": option["key"],
            "verdict": "correct" if option["key"] in correct else "wrong",
            "text": analysis[option["key"]],
        }
        for option in turn.version.content_json.get("options") or []
        if analysis.get(option["key"])
    ]


def _request_standard(turn: _Turn) -> list[dict]:
    _block_in_retest(turn)
    solution = question_service.get_solution(
        turn.tc.db, turn.question.id, turn.version.version, "standard"
    )
    if solution is None or not solution.reviewed:
        # 没有审核解析，本阶段也没有可以信任的模型来现写一份：如实说明
        payload = {
            "reason_code": "MODEL_UNAVAILABLE",
            "text": "这道题暂时没有审核过的解析，也没有可用的讲解服务。已经记下来，之后补充。",
            "suggestions": [],
        }
        return [
            turn.emit(
                "fallback", payload, state_after="FALLBACK", source="rule_engine", degraded=True
            )
        ]

    _require_independent_ended(turn)
    turn.session.used_solution = True
    turn.session.assisted = True
    content = solution.content_json
    payload = {
        "title": "常规解法",
        "steps": [{"text": step} for step in content["steps"]],
        "final_answer": content["final_answer"],
        "option_analysis": _option_analysis(turn),
        "key_points": content.get("key_points") or [],
    }
    return [turn.emit("standard", payload, state_after="STANDARD")]


def _request_fast(turn: _Turn) -> list[dict]:
    _block_in_retest(turn)
    solution = question_service.reviewed_fast_solution(
        turn.tc.db, turn.question.id, turn.version.version
    )
    if solution is None:
        return [turn.notice("fast_not_applicable", "这道题没有经过审核的快速解法，请用常规解法。")]

    _require_independent_ended(turn)
    turn.session.used_solution = True
    turn.session.assisted = True
    conditions = solution.conditions_json or {}
    payload = {
        "title": "快速解法",
        "conditions": conditions["conditions"],
        "steps": [{"text": step} for step in solution.content_json["steps"]],
        "final_answer": solution.content_json["final_answer"],
        "boundary": conditions["boundary"],
        "reviewed": True,
    }
    return [turn.emit("fast", payload, state_after="FAST")]


def _request_visual(turn: _Turn) -> list[dict]:
    _block_in_retest(turn)
    visual = turn.visual
    if visual is None:
        return [turn.notice("visual_not_available", "这道题没有合适的图解，可以先看文字提示。")]
    # A registered numeric template can still calculate this question's answer.
    # The visual action's confirmation flag is not a full-solution action.
    if turn.submitted == 0 and not turn.session.used_solution:
        return [
            turn.notice(
                "visual_not_available",
                "图解可能包含答案或关键推导，请先提交作答，或明确选择完整解析。现在可以先看分层提示。",
            )
        ]
    turn.session.assisted = True
    return [turn.emit("visual", visual, state_after="VISUAL")]


# ---------------------------------------------------------------- "没懂"的三级回退


def _concept_node(turn: _Turn) -> KnowledgeNode | None:
    nodes = list(
        turn.tc.db.scalars(
            select(KnowledgeNode)
            .join(QuestionKnowledge, QuestionKnowledge.knowledge_id == KnowledgeNode.id)
            .where(QuestionKnowledge.question_id == turn.question.id)
            .order_by(KnowledgeNode.code)
        )
    )
    concept = turn.teaching.get("concept")
    return next((node for node in nodes if node.title == concept), nodes[0] if nodes else None)


def _prerequisites(turn: _Turn) -> list[KnowledgeNode]:
    own = select(QuestionKnowledge.knowledge_id).where(
        QuestionKnowledge.question_id == turn.question.id
    )
    return list(
        turn.tc.db.scalars(
            select(KnowledgeNode)
            .join(KnowledgeEdge, KnowledgeEdge.prereq_id == KnowledgeNode.id)
            .where(KnowledgeEdge.target_id.in_(own), KnowledgeNode.id.not_in(own))
            .distinct()
            .order_by(KnowledgeNode.code)
        )
    )


def _fallback_suggestions(turn: _Turn) -> list[dict[str, Any]]:
    suggestions = []
    if turn.visual is not None:
        suggestions.append(events.suggestion("request_visual", "解析阶段看图"))
    if turn.session.hint_level_revealed < len(turn.hints):
        suggestions.append(events.suggestion("request_hint", "给点提示"))
    suggestions.append(events.suggestion("request_standard", "看常规解法"))
    return suggestions


def _rephrase(turn: _Turn) -> list[dict]:
    """第一次没懂：换一种讲法。有审核文案就用审核文案，没有才请模型，模型不行就如实降级。"""
    session, tc = turn.session, turn.tc
    reviewed = turn.teaching.get("concept_rephrase")
    if reviewed:
        session.confused_streak = 1
        session.assisted = True
        level = max(1, session.hint_level_revealed)
        payload = {
            "level": level,
            "total_levels": max(level, len(turn.hints)),
            "style": "rephrase",
            "text": reviewed,
            "concept": turn.teaching.get("concept"),
        }
        return [turn.emit("hint", payload, state_after="HINTED")]

    if not tc.allow_gateway:
        session.confused_streak = 1
        return [
            turn.emit(
                "fallback",
                {
                    "reason_code": "MODEL_UNAVAILABLE",
                    "text": "当前受控运行仅提供受审讲解；可以先看分层提示，或提交后查看解析与图解。",
                    "suggestions": _fallback_suggestions(turn),
                },
                state_after="FALLBACK",
                source="rule_engine",
                degraded=True,
            )
        ]

    tc.db.refresh(turn.version)
    turn.teaching = turn.version.teaching_json or {}
    initial_identity = (session.question_id, session.question_version, session.student_id)
    reference_catalog = content_references.catalog(turn, ["rephrase"])
    node = _concept_node(turn)
    request = GatewayRequest(
        request_id=tc.request_id,
        student_pseudonym=tc.pseudonym,
        task_type=TaskType.TUTOR_EXPLAIN,
        # 只把审核过的概念说明交给模型；不带学生的作答、草稿或任何个人信息
        input_parts=[
            InputPart(
                kind="json",
                data={
                    "subject": turn.question.subject,
                    "concept": turn.teaching.get("concept"),
                    "key_idea": node.summary if node else None,
                    "independent_attempt": turn.submitted == 0,
                },
            )
        ],
        constraints=Constraints(
            forbidden_substrings=list(turn.teaching.get("leak_markers") or []),
            reference_catalog=reference_catalog,
        ),
        trace_id=uuid.uuid4().hex,
    )
    # 到这里为止还没有任何写入。先结束读事务再调模型：模型调用期间不占数据库，
    # 网关也要用自己的事务写审计和用量。
    tc.db.commit()
    response = tc.gateway.invoke(request)
    tc.db.refresh(session)
    if session.state == "DONE":
        raise conflict("invalid_state", "这次学习已经结束")

    if initial_identity != (session.question_id, session.question_version, session.student_id):
        raise conflict("invalid_state", "学习题版本或身份已变化")
    tc.db.refresh(turn.version)
    turn.teaching = turn.version.teaching_json or {}
    turn.submitted = session_service.submitted_count(tc.db, session.id)
    _block_in_retest(turn)
    approved_references = []
    reference_valid = True
    if response.status == "ok" and response.validated_output is not None:
        try:
            approved_references = content_references.resolve_proposals(
                response.validated_output.get("references", []),
                reference_catalog,
                content_references.catalog(turn, ["rephrase"]),
            )
        except (ValueError, TypeError, KeyError):
            reference_valid = False
    session.confused_streak = 1
    if response.status == "ok" and response.validated_output is not None and reference_valid:
        session.assisted = True
        return [
            turn.emit(
                "hint",
                response.validated_output["payload"],
                state_after="HINTED",
                source="model",
                references=approved_references,
                provider=response.provider,
                model_id=response.model_id,
                prompt_version=response.prompt_version,
                trace_id=response.trace_id,
            )
        ]

    reason = (
        "SCHEMA_INVALID"
        if not reference_valid
        else (
            response.error_code if response.error_code in _FALLBACK_REASONS else "MODEL_UNAVAILABLE"
        )
    )
    payload = {
        "reason_code": reason,
        "text": "换种讲法暂时生成不了。可以先看分层提示；图解在提交作答或明确查看完整解析后提供。",
        "suggestions": _fallback_suggestions(turn),
    }
    return [
        turn.emit(
            "fallback",
            payload,
            state_after="FALLBACK",
            source="rule_engine",
            degraded=True,
            trace_id=response.trace_id,
        )
    ]


def _mark_confused(turn: _Turn) -> list[dict]:
    _block_in_retest(turn)
    session = turn.session
    if session.needs_human_help:
        return []  # 已经建议暂停并记录在案，不再无限重复生成内容

    streak = session.confused_streak + 1
    if streak == 1:
        return _rephrase(turn)

    session.confused_streak = streak
    if streak == 2:
        # 连续第二次没懂：检查前置知识，并优先推荐图解
        prerequisites = _prerequisites(turn)
        suggestions = [
            events.suggestion("review_prerequisite", f"先复习：{node.title}", knowledge_id=node.id)
            for node in prerequisites[:2]
        ]
        if turn.visual is not None:
            suggestions.append(events.suggestion("request_visual", "解析阶段看图"))
        if not suggestions:
            suggestions = _fallback_suggestions(turn)
        prompt = (
            "可能是前面的知识点没有接上。先确认下面的前置知识；提交或明确查看完整解析后可以结合图解。"
            if prerequisites
            else "换个方式试试：先看提示；提交或明确查看完整解析后可以结合图解。"
        )
        return [
            turn.emit("ask", {"prompt": prompt, "suggestions": suggestions}, source="rule_engine")
        ]

    session.needs_human_help = True
    return [
        turn.notice(
            "needs_human_help",
            "已经换过讲法、也看过前置知识了，先停一下也没关系。这道题已记录为需要老师或家长帮忙。",
        )
    ]


# ---------------------------------------------------------------- "我懂了"


def _next_variant(turn: _Turn) -> Question | None:
    """还没做过、并且可以发给这名学生的变式题。"""
    db, tc = turn.tc.db, turn.tc
    attempted = select(StudySession.question_id).where(StudySession.student_id == tc.student_id)
    candidates = list(
        db.scalars(
            select(Question)
            .where(
                Question.variant_of_id == turn.question.id,
                Question.status == "published",
                Question.id.not_in(attempted),
            )
            .order_by(Question.difficulty, Question.id)
        )
    )
    if not candidates:
        return None
    scope = question_service.student_scope(db, tc.student_id)
    tags = question_service.approved_tags(db, [q.id for q in candidates])
    return next(
        (q for q in candidates if question_service.classify(tags[q.id], scope) != "other"), None
    )


def _mark_understood(turn: _Turn) -> list[dict]:
    session = turn.session
    session.confused_streak = 0
    if turn.submitted == 0:
        return [turn.notice("keep_going", "好，继续完成作答吧。")]

    if session_service.open_attempt(turn.tc.db, session.id) is not None:
        return [turn.notice("keep_going", "还有未提交的草稿或副本，仍可继续编辑；没有关闭它们。")]

    produced = []
    variant = _next_variant(turn)
    if variant is not None:
        payload = {
            "prompt": "要不要做一道变式题，检验是不是真的掌握了？",
            "suggestions": [
                events.suggestion("start_variant", "做一道变式题", question_id=variant.id),
                events.suggestion("finish", "先到这里"),
            ],
        }
        produced.append(turn.emit("ask", payload, state_after="VARIANT", source="rule_engine"))

    if session.origin != "review":
        item = review_scheduler.find_item(turn.tc.db, turn.tc.student_id, turn.question.id)
        if item is not None and item.status == "scheduled":
            produced.append(
                turn.notice(
                    "review_scheduled",
                    "已经安排了复测，到时候不看提示再做一遍，确认是真的会了。",
                    state_after="REVIEW_SCHEDULED",
                    due_at=iso(item.due_at),
                )
            )

    produced.append(turn.notice("session_completed", "这道题先到这里。", state_after="DONE"))
    return produced


_HANDLERS = {
    "request_hint": _request_hint,
    "request_standard": _request_standard,
    "request_fast": _request_fast,
    "request_visual": _request_visual,
    "mark_confused": _mark_confused,
    "mark_understood": _mark_understood,
}


def next_step(tc: TutorContext, session_id: str, body: TutorActionIn) -> TutorStep:
    session = session_service.lock_owned_session(tc.db, tc.student_id, session_id)
    if session.state == "DONE":
        raise conflict("invalid_state", "这次学习已经结束，请重新开始一次会话")

    question = tc.db.get(Question, session.question_id)
    assert question is not None
    version = question_service.get_version(tc.db, question.id, session.question_version)
    turn = _Turn(
        tc=tc,
        session=session,
        question=question,
        version=version,
        teaching=version.teaching_json or {},
        submitted=session_service.submitted_count(tc.db, session.id),
        body=body,
    )
    produced = _HANDLERS[body.action](turn)
    session.updated_at = tc.now
    tc.db.flush()
    return TutorStep(session=session_service.serialize_session(tc.db, session), events=produced)
