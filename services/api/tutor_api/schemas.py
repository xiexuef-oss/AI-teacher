"""请求与响应模型。形状以 contracts/openapi.yaml 为准；测试会把每个真实响应按契约再校验一遍。

请求模型一律 extra="forbid"：多出来的字段（包括别人的 student_id）直接 422。
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_serializer,
)

RegionCode = Literal["CN-51", "CN-50"]
Grade = Literal["G10", "G11", "G12"]
Subject = Literal["math", "physics", "chemistry"]
AnswerMode = Literal["single_choice", "multiple_choice", "fill", "written", "experiment", "proof"]
SourceCategory = Literal["gaokao_real", "mock_exam", "foundation", "ai_variant"]
QuestionScope = Literal["all", "region", "general"]
SessionOrigin = Literal["task", "practice", "review", "variant"]
TutorActionType = Literal[
    "request_hint",
    "request_standard",
    "request_fast",
    "request_visual",
    "mark_understood",
    "mark_confused",
]
ReviewScope = Literal["due", "all"]
LocalRole = Literal["student", "parent", "reviewer", "admin"]
QuestionStatus = Literal["draft", "reviewed", "published", "withdrawn"]
ReviewDecisionType = Literal["approve", "reject", "publish", "withdraw"]
SolutionKind = Literal["standard", "fast"]
HistoryAction = Literal["approve", "reject", "publish", "withdraw", "edit", "import"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- 系统


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    api_version: str
    contract_version: str
    environment: str
    local_identity_mock: bool
    external_model_calls: bool
    server_time: datetime


class RegionOption(BaseModel):
    code: str
    name: str


class GradeOption(BaseModel):
    code: str
    name: str
    estimated_exam_year: int


class SubjectOption(BaseModel):
    code: str
    name: str


class CurriculumOption(BaseModel):
    code: str
    name: str


class LaunchConfig(BaseModel):
    regions: list[RegionOption]
    grades: list[GradeOption]
    subjects: list[SubjectOption]
    curriculum_versions: list[CurriculumOption]
    school_year_start_month: int
    exam_year_min: int
    exam_year_max: int


# ---------------------------------------------------------------- 身份与资料


class LocalIdentityOut(BaseModel):
    user_id: str
    role: LocalRole = "student"
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"


class ProfileNotice(BaseModel):
    code: Literal["curriculum_unknown", "grade_unknown", "exam_year_estimated"]
    message: str


class LearningPackReturnRequest(_In):
    transcript: str = Field(min_length=1, max_length=8000, pattern=r"\S")


class LearningPackPhotoOcrRequest(_In):
    photo_ids: list[UUID] = Field(min_length=1, max_length=10)


class LearningPackSubmission(LearningPackReturnRequest):
    completed_on: date | None = None
    independence: Literal["independent", "assisted", "unknown"] | None = None
    photo_ids: list[UUID] | None = Field(default=None, max_length=10)


class LearningPackCorrectionRequest(LearningPackReturnRequest):
    expected_revision: int = Field(strict=True, ge=0)


class LearningPackRequest(_In):
    school_minutes: int = Field(strict=True, ge=0, le=10080)


class LearningSettings(_In):
    mode: Literal["boarding", "weekend", "digital"]
    weekly_minutes: int = Field(strict=True, ge=0, le=10080)
    weekdays: list[Annotated[int, Field(strict=True, ge=1, le=7)]] = Field(max_length=7)
    school_progress: str = Field(default="", max_length=500)
    exam_scope: str = Field(default="", max_length=500)

    @field_validator("weekdays")
    @classmethod
    def _unique_weekdays(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("weekdays 不能重复")
        return value


class StudentProfileOut(BaseModel):
    learning_settings: LearningSettings | None = None
    user_id: str
    revision: int = Field(ge=0)
    display_name: str | None
    region_code: str | None
    grade: str | None
    subjects: list[str]
    exam_year: int | None
    exam_year_source: str | None
    exam_scheme_code: str | None
    curriculum_version: str | None
    onboarding_completed: bool
    notices: list[ProfileNotice]
    updated_at: datetime


class ProfileUpdateIn(_In):
    learning_settings: LearningSettings | None = None
    expected_revision: int = Field(strict=True, ge=0)
    region_code: RegionCode
    subjects: list[Subject] = Field(min_length=1, max_length=3)
    grade: Grade | None = None
    exam_year: int | None = None
    curriculum_version: str | None = Field(default=None, min_length=1, max_length=32)
    display_name: str | None = Field(default=None, min_length=1, max_length=40)

    @field_validator("subjects")
    @classmethod
    def _unique_subjects(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("subjects 不能重复")
        return value


# ---------------------------------------------------------------- 题目


class Applicability(BaseModel):
    scope: Literal["region", "general"]
    label: str
    recommended_regions: list[str]
    origin_region_code: str | None
    exam_year_from: int | None
    exam_year_to: int | None
    disclaimer: str


class QuestionSource(BaseModel):
    source_type: str
    source_category: str
    source_name: str | None
    source_year: int | None
    source_license: str
    source_url: str | None
    is_engineering_sample: bool
    label: str


class QuestionOriginLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    file_kind: Literal["pdf", "doc", "docx", "png", "jpeg", "json"]
    locator_kind: Literal["pdf_page", "word_fragment", "image_page", "json_fragment", "unknown"]
    index: int = Field(ge=1, strict=True)
    declared_block: int | None = Field(ge=1, strict=True)


class QuestionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_snapshot: QuestionSource
    origins: list[QuestionOriginLocation] = Field(max_length=2000)
    relation: Literal["declared", "derived_unverified"]
    parent_version: int | None = Field(ge=1, strict=True)
    access: Literal["metadata_only"]


class KnowledgeRef(BaseModel):
    id: str
    code: str
    title: str


class QuestionTopicOut(KnowledgeRef):
    subject: Subject
    question_count: int = Field(ge=1)


class QuestionTopicPage(BaseModel):
    items: list[QuestionTopicOut]


class QuestionOption(BaseModel):
    key: str
    text: str


class QuestionBlank(BaseModel):
    key: str
    label: str | None = None
    unit_hint: str | None = None
    placeholder: str | None = None


class QuestionAttachment(BaseModel):
    kind: Literal["image", "table"]
    media_id: str | None = None
    alt: str


ExperimentSafetyLevel = Literal["low", "medium", "high"]


class ExperimentSafety(BaseModel):
    level: ExperimentSafetyLevel
    notes: list[str]


class DataTableColumn(BaseModel):
    key: str
    label: str
    unit: str | None = None


class DataTableCell(BaseModel):
    col: str
    # None 表示留空，由学生填写；参考值不在这里，只在提交之后随自查给出。
    # 不叫 value：题目接口里不允许出现名为 value 的键（答案类的字段都叫它）
    text: str | None = None


class DataTableRow(BaseModel):
    key: str
    label: str | None = None
    cells: list[DataTableCell]


class DataTable(BaseModel):
    key: str
    title: str
    columns: list[DataTableColumn]
    rows: list[DataTableRow]


class Subquestion(BaseModel):
    key: str
    stem: str
    answer_mode: str
    options: list[QuestionOption] = Field(default_factory=list)
    blanks: list[QuestionBlank] = Field(default_factory=list)


class ProofStatement(BaseModel):
    """证明题的已知和求证。参考证明不在这里，只在提交之后随自查给出。"""

    givens: list[str] = Field(default_factory=list)
    claim: str


class QuestionContent(BaseModel):
    stem: str
    options: list[QuestionOption] = Field(default_factory=list)
    blanks: list[QuestionBlank] = Field(default_factory=list)
    subquestions: list[Subquestion] = Field(default_factory=list)
    attachments: list[QuestionAttachment] = Field(default_factory=list)
    data_tables: list[DataTable] = Field(default_factory=list)
    safety: ExperimentSafety | None = None
    proof: ProofStatement | None = None


class QuestionAssists(BaseModel):
    hint_levels: int
    has_standard_solution: bool
    has_fast_solution: bool
    visual_available: bool


class QuestionSummary(BaseModel):
    id: str
    subject: str
    type: str
    answer_mode: str
    difficulty: int
    title: str
    source: QuestionSource
    applicability: Applicability
    knowledge: list[KnowledgeRef]
    variant_of: str | None


class QuestionOut(QuestionSummary):
    provenance: QuestionProvenance | None = None
    version: int
    grade: str | None
    content: QuestionContent
    assists: QuestionAssists
    judging_note: str | None


class QuestionPage(BaseModel):
    items: list[QuestionSummary]
    next_cursor: str | None


# ---------------------------------------------------------------- 内容审核（reviewer / admin）


class ReviewDecisionIn(_In):
    expected_review_revision: int = Field(strict=True, ge=1)
    decision: ReviewDecisionType
    expected_version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=2000)
    solution_kinds: list[SolutionKind] | None = None


class MediaUploadIn(_In):
    purpose: Literal["scan", "draft_backup", "question_attachment"]
    mime: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MediaBlobIn(_In):
    content_base64: str = Field(max_length=22369624)


class MediaConfirmIn(_In):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MediaReviewConfirmationIn(_In):
    expected_version: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def strict_review_confirmation(cls, value):
        if not (isinstance(value, bool) and value):
            raise ValueError("须明确声明当前版本图片")
        return value


class MediaDeleteIn(_In):
    pass


class ReviewBatchItemIn(ReviewDecisionIn):
    question_id: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("必须逐题明确确认")
        return value


class ReviewBatchIn(_In):
    items: list[ReviewBatchItemIn] = Field(min_length=1, max_length=50)

    @field_validator("items")
    @classmethod
    def unique_questions(cls, items):
        if len({item.question_id.lower() for item in items}) != len(items):
            raise ValueError("题目ID不能重复")
        return items


class QuestionReviewStateOut(BaseModel):
    review_revision: int = Field(ge=1)
    question_id: str
    status: QuestionStatus
    version: int
    reviewed_by: str | None
    updated_at: datetime


class AdminQuestionSummary(BaseModel):
    review_revision: int = Field(ge=1)
    id: str
    subject: str
    type: str
    answer_mode: str
    difficulty: int
    title: str
    status: QuestionStatus
    version: int
    source: QuestionSource
    created_by: str | None
    reviewed_by: str | None
    published_at: datetime | None
    updated_at: datetime


class AdminStatusCounts(BaseModel):
    draft: int
    reviewed: int
    published: int
    withdrawn: int


class AdminQuestionPage(BaseModel):
    items: list[AdminQuestionSummary]
    next_cursor: str | None
    status_counts: AdminStatusCounts


class AdminAnswer(BaseModel):
    value: Any
    equivalence_rules: dict[str, Any]
    units: dict[str, Any]


class AdminVisual(BaseModel):
    template_id: str
    params: dict[str, float]
    caption: str


class ContentSpanRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str = Field(
        max_length=64,
        pattern="^(stem|subquestion:[1-9][0-9]{0,2}:stem|option:[1-9][0-9]{0,2}|subquestion:[1-9][0-9]{0,2}:option:[1-9][0-9]{0,2}|proof:given:[1-9][0-9]{0,2}|proof:claim|hint:[1-9][0-9]{0,2}|rephrase|solution:(standard|fast):(step:[1-9][0-9]{0,2}|final_answer|condition:[1-9][0-9]{0,2}|boundary|key_point:[1-9][0-9]{0,2})|visual:(caption|static_fallback)|rubric:point:[1-9][0-9]{0,2}|reference_cell:[1-9][0-9]{0,2}:[1-9][0-9]{0,2}:[1-9][0-9]{0,2}|reference_step:[1-9][0-9]{0,2}:(text|reason))$",
    )
    block_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    start: StrictInt = Field(ge=0, le=3999)
    end: StrictInt = Field(ge=1, le=4000)

    @field_validator("end")
    @classmethod
    def nonempty_range(cls, value, info):
        if value <= info.data.get("start", -1):
            raise ValueError("reference range must be nonempty")
        return value


class TeachingReferenceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_block_id: str = Field(
        max_length=64,
        pattern="^(hint:[1-9][0-9]{0,2}|rephrase|solution:(standard|fast):step:[1-9][0-9]{0,2}|visual:caption)$",
    )
    source_span: ContentSpanRef
    independent_safe: StrictBool


class AdminTeaching(BaseModel):
    reference_links: list[TeachingReferenceLink] = Field(default_factory=list, max_length=64)
    concept: str | None
    hints: list[str]
    concept_rephrase: str | None
    option_analysis: dict[str, str]
    visual: AdminVisual | None
    leak_markers: list[str]


class AdminSolution(BaseModel):
    kind: SolutionKind
    steps: list[str]
    final_answer: str
    key_points: list[str]
    conditions: list[str] | None
    boundary: str | None
    reviewed: bool
    reviewed_by: str | None


class AdminRegionTag(BaseModel):
    recommended_region_code: str
    origin_region_code: str | None
    exam_year_from: int | None
    exam_year_to: int | None
    review_status: str
    note: str | None


class AdminQuestionVersion(BaseModel):
    version: int
    created_by: str | None
    created_at: datetime


class AdminHistoryEntry(BaseModel):
    id: str
    action: HistoryAction
    actor_id: str | None
    from_status: QuestionStatus | None
    to_status: QuestionStatus | None
    version: int | None
    comment: str | None
    changes: list[str] | None
    created_at: datetime


class AdminVersionSnapshot(BaseModel):
    provenance: QuestionProvenance | None = None
    question_id: str
    version: int
    is_current: bool
    created_by: str | None
    created_at: datetime
    title: str
    difficulty: int
    grade: str | None
    content: QuestionContent
    answer: AdminAnswer
    teaching: AdminTeaching
    solutions: list[AdminSolution]
    knowledge: list[str]
    rubric: dict[str, Any]


class AdminQuestionDetail(BaseModel):
    provenance: QuestionProvenance | None = None
    review_revision: int = Field(ge=1)
    id: str
    subject: str
    type: str
    answer_mode: str
    difficulty: int
    grade: str | None
    title: str
    status: QuestionStatus
    version: int
    source: QuestionSource
    variant_of: str | None
    created_by: str | None
    reviewed_by: str | None
    published_at: datetime | None
    updated_at: datetime
    content: QuestionContent
    answer: AdminAnswer
    teaching: AdminTeaching
    solutions: list[AdminSolution]
    rubric: dict[str, Any]
    knowledge: list[KnowledgeRef]
    region_tags: list[AdminRegionTag]
    check_problems: list[str]
    versions: list[AdminQuestionVersion]
    history: list[AdminHistoryEntry]


# ---------------------------------------------------------------- 任务


class StudyTask(BaseModel):
    id: str
    kind: Literal["new_topic", "review_mistake", "retest", "weak_point", "variant"]
    title: str
    reason: str
    subject: str
    question_id: str
    review_item_id: str | None
    applicability: Applicability
    estimated_minutes: int


class TodayTasks(BaseModel):
    date: date
    items: list[StudyTask]
    cold_start: bool = False


# ---------------------------------------------------------------- 会话与作答


class DiagnosticRevisionIn(_In):
    expected_revision: int = Field(strict=True, ge=0)


class DiagnosticCreateIn(DiagnosticRevisionIn):
    subject: Subject
    expected_profile_revision: int = Field(strict=True, ge=0)


class SessionCreateIn(_In):
    question_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    origin: SessionOrigin
    review_item_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    parent_session_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    expected_question_version: int | None = Field(default=None, strict=True, ge=1)

    @model_serializer(mode="wrap")
    def preserve_legacy_fingerprint(self, handler):
        value = handler(self)
        if "expected_question_version" not in self.model_fields_set:
            value.pop("expected_question_version", None)
        return value

    @field_validator("expected_question_version", mode="before")
    @classmethod
    def nonnullable_expected_version(cls, value):
        if value is None:
            raise ValueError("提供期望题目版本时不能为null")
        return value


class StudySessionOut(BaseModel):
    id: str
    question_id: str
    question_version: int
    origin: str
    state: str
    review_item_id: str | None
    parent_session_id: str | None
    region_code_snapshot: str | None
    exam_year_snapshot: int | None
    curriculum_version_snapshot: str | None
    assisted: bool
    used_solution: bool
    independent_ended: bool
    hint_level_revealed: int
    hint_levels_total: int
    confused_streak: int
    needs_human_help: bool
    active_attempt_id: str | None
    first_submitted_attempt_id: str | None = None
    submitted_attempts: int
    last_event_seq: int
    created_at: datetime
    updated_at: datetime


class AttemptCreateIn(_In):
    session_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


class AnswerBlank(_In):
    key: str = Field(min_length=1, max_length=16)
    value: str = Field(max_length=200)


class AnswerPart(_In):
    """解答题、实验题某一小问的文字作答。"""

    key: str = Field(min_length=1, max_length=16)
    text: str = Field(max_length=4000)


class AnswerCell(_In):
    """实验题数据表里的一个格子：学生填的数（作答），或提交之后给出的参考值（自查）。"""

    table: str = Field(min_length=1, max_length=16)
    row: str = Field(min_length=1, max_length=16)
    col: str = Field(min_length=1, max_length=16)
    value: str = Field(max_length=40)


class AnswerStep(_In):
    """证明题作答里的一步。依据可以不写：写不写、写得对不对都不拦提交，也不判对错。"""

    text: str = Field(max_length=1000)
    reason: str = Field(max_length=400)


class AnswerPayload(_In):
    selected_options: list[str] | None = Field(default=None, max_length=10)
    blanks: list[AnswerBlank] | None = Field(default=None, max_length=10)
    parts: list[AnswerPart] | None = Field(default=None, max_length=20)
    cells: list[AnswerCell] | None = Field(default=None, max_length=200)
    steps: list[AnswerStep] | None = Field(default=None, max_length=30)
    text: str | None = Field(default=None, max_length=4000)

    @field_validator("selected_options")
    @classmethod
    def _valid_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if len(set(value)) != len(value):
            raise ValueError("selected_options 不能重复")
        if any(not 1 <= len(item) <= 8 for item in value):
            raise ValueError("选项键长度应为 1~8")
        return value


class Stroke(_In):
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    width: float = Field(ge=0.5, le=24)
    points: list[float] = Field(max_length=40000)


class StrokePage(_In):
    width: float = Field(gt=0, le=10000)
    height: float = Field(gt=0, le=10000)
    strokes: list[Stroke] = Field(max_length=3000)


class StrokeDoc(_In):
    version: Literal[1]
    pages: list[StrokePage] = Field(max_length=20)


class DraftSyncIn(_In):
    base_revision: int = Field(ge=0)
    answer: AnswerPayload | None = None
    strokes: StrokeDoc | None = None


class DraftCopyCreateIn(_In):
    source_revision: int = Field(ge=0, strict=True)
    answer: AnswerPayload | None
    strokes: StrokeDoc | None


class DraftOut(BaseModel):
    attempt_id: str
    revision: int
    answer: dict[str, Any] | None
    strokes: dict[str, Any] | None
    updated_at: datetime


class SubmitIn(_In):
    answer: AnswerPayload
    elapsed_ms: int | None = Field(default=None, ge=0)
    expected_draft_revision: int | None = Field(default=None, strict=True, ge=0)

    @field_validator("expected_draft_revision", mode="before")
    @classmethod
    def nonnullable_draft_revision(cls, value):
        if value is None:
            raise ValueError("提供期望草稿修订时不能为null")
        return value

    @model_serializer(mode="wrap")
    def preserve_legacy_fingerprint(self, handler):
        value = handler(self)
        if "expected_draft_revision" not in self.model_fields_set:
            value.pop("expected_draft_revision", None)
        return value


class FeedbackItem(BaseModel):
    target: str
    code: str
    message: str


class Evaluation(BaseModel):
    state: Literal["pending", "verified", "uncertain", "error"]
    outcome: Literal["correct", "partially_correct", "incorrect", "undetermined"]
    is_correct: bool | None
    independent: bool
    assisted: bool
    used_solution: bool
    review_required: bool
    feedback: list[FeedbackItem]
    message: str
    disclaimer: str


class AttemptOut(BaseModel):
    id: str
    session_id: str
    attempt_no: int
    submission_no: int | None = None
    copied_from_attempt_id: str | None = None
    copied_from_revision: int | None = None
    status: str
    answer: dict[str, Any] | None
    draft_revision: int
    assisted: bool
    used_solution: bool
    independent: bool | None
    evaluation: Evaluation | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DraftCopyOut(BaseModel):
    session: StudySessionOut
    attempt: AttemptOut
    draft: DraftOut


class QuestionDraftRefOut(BaseModel):
    session_id: str
    attempt_id: str
    question_version: int
    attempt_no: int
    draft_revision: int
    copied_from_attempt_id: str | None
    copied_from_revision: int | None
    origin: SessionOrigin
    review_item_id: str | None
    session_state: str
    updated_at: datetime


class QuestionDraftPageOut(BaseModel):
    items: list[QuestionDraftRefOut]
    next_cursor: str | None


class ReviewStateOut(BaseModel):
    id: str
    question_id: str
    status: str
    stage: int
    total_stages: int
    due_at: datetime
    last_result: str | None
    last_attempt_id: str | None
    updated_at: datetime


class ReviewItemOut(BaseModel):
    id: str
    question_id: str
    question_title: str
    subject: str
    status: str
    stage: int
    total_stages: int
    due_at: datetime
    is_due: bool
    last_result: str | None
    created_at: datetime
    updated_at: datetime


class SubmitResult(BaseModel):
    attempt: AttemptOut
    evaluation: Evaluation
    session: StudySessionOut
    events: list[dict[str, Any]]
    review_item: ReviewItemOut | None


# ---------------------------------------------------------------- 解答题、实验题自查

SelfCheckLevel = Literal["done", "partial", "missed"]


class SelfCheckPoint(BaseModel):
    key: str
    part: str | None
    text: str


class SelfCheckMark(BaseModel):
    point_key: str
    level: SelfCheckLevel


class SelfCheckMarkIn(_In):
    point_key: str = Field(min_length=1, max_length=16)
    level: SelfCheckLevel


class SelfCheckSaveIn(_In):
    marks: list[SelfCheckMarkIn] = Field(min_length=1, max_length=40)


class SelfCheckSummary(BaseModel):
    done: int
    partial: int
    missed: int
    total: int


ProofStage = Literal["premise", "construction", "reasoning", "conclusion"]


class ProofReferenceStep(BaseModel):
    """参考证明里的一步。只在提交之后给，只是对照用的参考，不参与任何判定。"""

    stage: ProofStage
    text: str
    reason: str


class SelfCheckOut(BaseModel):
    attempt_id: str
    points: list[SelfCheckPoint]
    # 实验题数据表里留空格子的参考值，只在提交之后给；解答题、证明题为空
    reference_cells: list[AnswerCell]
    # 证明题的参考证明，只在提交之后给；其他题型为空
    reference_steps: list[ProofReferenceStep]
    marks: list[SelfCheckMark]
    summary: SelfCheckSummary
    saved_at: datetime | None
    disclaimer: str


# ---------------------------------------------------------------- 教学


class TutorActionIn(_In):
    action: TutorActionType
    confirm_end_independent: bool = False


class TutorStep(BaseModel):
    session: StudySessionOut
    events: list[dict[str, Any]]


class TutorEventPage(BaseModel):
    items: list[dict[str, Any]]
    last_seq: int


# ---------------------------------------------------------------- 复测与学情


class ReviewPage(BaseModel):
    items: list[ReviewItemOut]
    next_cursor: str | None


class ReviewCompleteIn(_In):
    attempt_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


class ReviewCompletion(BaseModel):
    review_item: ReviewItemOut
    result: Literal["passed", "failed"]
    next_due_at: datetime | None


class RateStat(BaseModel):
    numerator: int
    denominator: int
    rate: float | None
    insufficient_data: bool


class ProgressBucket(BaseModel):
    key: str
    label: str
    independent: RateStat
    assisted: RateStat


class SubjectiveProgress(BaseModel):
    attempts: int
    self_checked: int
    points_done: int
    points_partial: int
    points_missed: int


class ProgressSummary(BaseModel):
    generated_at: datetime
    min_samples: int
    independent: RateStat
    assisted: RateStat
    hint_dependency: RateStat
    retest_success: RateStat
    variant_transfer: RateStat
    uncertain_attempts: int
    subjective: SubjectiveProgress
    by_subject: list[ProgressBucket]
    by_answer_mode: list[ProgressBucket]
    by_difficulty: list[ProgressBucket]
    disclaimer: str


# ---------------------------------------------------------------- 家长：授权绑定与周报


class ParentInviteOut(BaseModel):
    parent_invite_revision: int = Field(ge=0)
    id: str
    code: str
    created_at: datetime
    expires_at: datetime


class ParentInviteRedeemIn(_In):
    code: str = Field(min_length=1, max_length=40)


class ParentInviteCreateIn(_In):
    expected_parent_invite_revision: int = Field(strict=True, ge=0)


class ParentLinkRevokeIn(_In):
    expected_authorization_revision: int = Field(strict=True, ge=1)


class PendingParentInviteOut(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime


class ParentLinkOut(BaseModel):
    authorization_revision: int = Field(ge=1)
    id: str
    parent_id: str
    parent_label: str | None
    consent_at: datetime
    linked_at: datetime
    revoked_at: datetime | None


class ParentLinksOut(BaseModel):
    parent_invite_revision: int = Field(ge=0)
    links: list[ParentLinkOut]
    pending_invite: PendingParentInviteOut | None


class ParentStudentOut(BaseModel):
    student_id: str
    display_name: str | None
    linked_at: datetime


class ParentStudentsOut(BaseModel):
    items: list[ParentStudentOut]


WeeklyTrend = Literal["up", "down", "flat", "unknown"]


class PreviousWeekOut(BaseModel):
    week_start: date
    attempts_count: int
    independent: RateStat


class PaperWeeklySummary(BaseModel):
    confirmed: int
    awaiting_assessment: int
    late_returns: int
    unknown_completion_date: int
    independent: RateStat
    assisted: RateStat


class ParentWeeklyOut(BaseModel):
    paper: PaperWeeklySummary | None = None
    student_id: str
    student_display_name: str | None
    week_start: date
    week_end: date
    is_complete: bool
    generated_at: datetime
    min_samples: int
    sessions_count: int
    attempts_count: int
    active_days: int
    independent: RateStat
    assisted: RateStat
    hint_dependency: RateStat
    retest_success: RateStat
    written_attempts: int
    independent_trend: WeeklyTrend
    previous_week: PreviousWeekOut
    by_subject: list[ProgressBucket]
    disclaimer: str


# ---------------------------------------------------------------- 修改题目（产生新版本）
# 输入模型比输出模型严格：不认识的字段一律 422，文本长度有上限。输出模型保持宽松，库里的旧数据多出字段也不会让读取失败。

Text4000 = Annotated[str, Field(max_length=4000)]
Text200 = Annotated[str, Field(max_length=200)]


class QuestionOptionIn(_In, QuestionOption):
    key: str = Field(min_length=1, max_length=8)
    text: Text4000


class QuestionBlankIn(_In, QuestionBlank):
    key: str = Field(min_length=1, max_length=16)


class QuestionAttachmentIn(_In, QuestionAttachment):
    pass


class SubquestionIn(_In, Subquestion):
    stem: Text4000
    options: list[QuestionOptionIn] = Field(default_factory=list, max_length=12)
    blanks: list[QuestionBlankIn] = Field(default_factory=list, max_length=12)


TableKey = Annotated[str, Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9_]+$")]


class ExperimentSafetyIn(_In, ExperimentSafety):
    notes: list[Text200] = Field(min_length=1, max_length=8)


class DataTableColumnIn(_In, DataTableColumn):
    key: TableKey
    label: str = Field(min_length=1, max_length=40)
    unit: str | None = Field(default=None, max_length=16)


class DataTableCellIn(_In, DataTableCell):
    col: str = Field(min_length=1, max_length=16)
    text: str | None = Field(default=None, max_length=40)


class DataTableRowIn(_In, DataTableRow):
    key: TableKey
    label: str | None = Field(default=None, max_length=40)
    cells: list[DataTableCellIn] = Field(min_length=1, max_length=12)


class DataTableIn(_In, DataTable):
    key: TableKey
    title: str = Field(min_length=1, max_length=120)
    columns: list[DataTableColumnIn] = Field(min_length=1, max_length=12)
    rows: list[DataTableRowIn] = Field(min_length=1, max_length=30)


class ProofStatementIn(_In, ProofStatement):
    givens: list[Annotated[str, Field(min_length=1, max_length=400)]] = Field(
        default_factory=list, max_length=8
    )
    claim: str = Field(min_length=1, max_length=500)


class QuestionContentIn(_In, QuestionContent):
    stem: Text4000
    options: list[QuestionOptionIn] = Field(default_factory=list, max_length=12)
    blanks: list[QuestionBlankIn] = Field(default_factory=list, max_length=12)
    subquestions: list[SubquestionIn] = Field(default_factory=list, max_length=20)
    attachments: list[QuestionAttachmentIn] = Field(default_factory=list, max_length=20)
    data_tables: list[DataTableIn] = Field(default_factory=list, max_length=5)
    safety: ExperimentSafetyIn | None = None
    proof: ProofStatementIn | None = None


class AdminAnswerIn(_In, AdminAnswer):
    pass


class AdminVisualIn(_In, AdminVisual):
    template_id: str = Field(max_length=64)
    caption: Text4000


class AdminTeachingIn(_In, AdminTeaching):
    concept: str | None = Field(max_length=200)
    hints: list[Text4000] = Field(max_length=8)
    concept_rephrase: Text4000 | None
    option_analysis: dict[str, Text4000]
    visual: AdminVisualIn | None
    leak_markers: list[Text200] = Field(max_length=50)


class AdminSolutionInput(_In):
    kind: SolutionKind
    steps: list[Text4000] = Field(max_length=30)
    final_answer: Text4000
    key_points: list[Text200] = Field(max_length=20)
    conditions: list[Text4000] | None = Field(max_length=20)
    boundary: Text4000 | None


class AdminQuestionDraftIn(_In):
    title: str = Field(min_length=1, max_length=120)
    difficulty: int = Field(ge=1, le=5)
    grade: Grade | None
    content: QuestionContentIn
    answer: AdminAnswerIn
    teaching: AdminTeachingIn
    solutions: list[AdminSolutionInput] = Field(max_length=2)
    knowledge: list[Annotated[str, Field(max_length=64)]] = Field(max_length=20)
    rubric: dict[str, Any]
    comment: str | None = Field(default=None, max_length=2000)


class AdminQuestionEditIn(AdminQuestionDraftIn):
    expected_review_revision: int = Field(strict=True, ge=1)
    expected_version: int = Field(ge=1)


class AdminImportSourceIn(_In):
    source_type: Literal["self_authored", "textbook_licensed", "public_license", "gaokao_licensed"]
    source_category: SourceCategory
    source_name: str = Field(min_length=1, max_length=200)
    source_year: int | None = Field(ge=1900, le=2100)
    source_license: str = Field(min_length=1, max_length=120)
    source_url: str | None = Field(max_length=500)

    @field_validator("source_name", "source_license")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("来源和使用依据不能留空")
        return value


class AdminQuestionImportIn(_In):
    subject: Subject
    answer_mode: AnswerMode
    source: AdminImportSourceIn
    question: AdminQuestionDraftIn


class DocImportDefaultsIn(_In):
    subject: Subject
    answer_mode: AnswerMode
    source: AdminImportSourceIn


class DocImportJobCreateIn(_In):
    creation_deadline: datetime

    @field_validator("creation_deadline", mode="before")
    @classmethod
    def aware_creation_deadline(cls, value):
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
            value,
        ):
            raise ValueError("creation_deadline must be an aware RFC3339 timestamp")
        try:
            parsed = datetime.fromisoformat(value.upper()).astimezone(UTC)
        except OverflowError as error:
            raise ValueError("creation_deadline is outside the UTC datetime range") from error
        return parsed.replace(microsecond=parsed.microsecond // 1000 * 1000)

    title: str = Field(min_length=1, max_length=120)
    defaults: DocImportDefaultsIn


class DocImportRevisionIn(_In):
    expected_revision: int = Field(ge=1)


class DocImportUploadIn(DocImportRevisionIn):
    filename: str = Field(min_length=1, max_length=256)
    content_base64: str = Field(min_length=4, max_length=22_369_624)

    @field_validator("filename")
    @classmethod
    def safe_display_filename(cls, value: str) -> str:
        if not value.strip() or any(c in value for c in "/\\\x00") or value in {".", ".."}:
            raise ValueError("文件名不能包含路径或空字符")
        return value


class DocImportLocationIn(_In):
    file_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    page: int = Field(ge=1)
    block: int | None = Field(ge=1)


class DocImportCandidateIn(_In):
    id: str | None = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    title: str = Field(max_length=120)
    text: Text4000
    locations: list[DocImportLocationIn] = Field(max_length=200)
    payload: AdminQuestionImportIn | None
    confirmed: bool


class DocImportCandidatesEditIn(DocImportRevisionIn):
    items: list[DocImportCandidateIn] = Field(max_length=200)


class DocImportSubmitIn(DocImportRevisionIn):
    candidate_ids: list[Annotated[str, Field(pattern=r"^[0-9a-fA-F-]{36}$")]] = Field(
        min_length=1, max_length=50
    )

    @field_validator("candidate_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("候选题 ID 不能重复")
        return value


class ScanCreateIn(_In):
    media_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


class ScanExpressionIn(_In):
    span_id: str
    latex: str
    confidence: float | None = Field(ge=0, le=1)


class ScanConfirmIn(_In):
    stem_text: str = Field(min_length=1, max_length=4000)
    expressions: list[ScanExpressionIn] = Field(max_length=50)


class ExportSelfCheckOut(BaseModel):
    attempt_id: str
    marks: list[SelfCheckMark]
    saved_at: datetime


class ExportReviewHistoryOut(BaseModel):
    review_id: str
    first_attempt_id: str
    question_id: str
    state: str
    result: str | None
    completed_at: datetime | None


class ExportLearningSessionOut(BaseModel):
    session: StudySessionOut
    attempts: list[AttemptOut]
    drafts: list[DraftOut]
    self_checks: list[ExportSelfCheckOut]
    events: list[dict[str, Any]]


class ExportParentAccessLinkOut(BaseModel):
    id: str
    authorization_revision: int
    consent_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class ExportParentAccessInviteOut(BaseModel):
    id: str
    expires_at: datetime
    redeemed_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ExportParentAccessRecordsOut(BaseModel):
    history_complete: Literal[False] = False
    links: list[ExportParentAccessLinkOut]
    invites: list[ExportParentAccessInviteOut]


class ExportScanExpressionOut(BaseModel):
    span_id: str
    latex: str
    confidence: float | None = Field(strict=True, ge=0, le=1)


class ExportScanPayloadOut(BaseModel):
    id: UUID
    status: Literal["processing", "needs_confirmation", "confirmed", "failed"]
    confidence: float | None = Field(strict=True, ge=0, le=1)
    low_confidence: StrictBool
    stem_text: str | None
    expressions: list[ExportScanExpressionOut]
    matched_question_id: UUID | None
    error_code: str | None
    mock_notice: str | None = None


class ExportStoredScanOut(BaseModel):
    media_id: UUID
    expires_at: datetime
    scan: dict[str, Any]


class StudentMediaExportOut(BaseModel):
    format_version: Literal[1] = 1
    scope: Literal["server_current_student_media"] = "server_current_student_media"
    owner_id: UUID
    exported_at: datetime
    history_complete: Literal[False] = False
    consistent_snapshot: Literal[False] = False
    objects_count: int = Field(ge=0, le=1000)
    files_count: int = Field(ge=0, le=1000)
    size_bytes: int = Field(ge=1, le=16777216)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_base64: str = Field(max_length=22369624)


class ExportModelCallOut(BaseModel):
    created_at: datetime
    task_type: str
    status: str
    provider_calls: int = Field(ge=0)
    input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)
    image_units: int | None = Field(ge=0)
    estimated_cost_micros: int | None = Field(ge=0)


class ExportModelBudgetDayOut(BaseModel):
    usage_date: date
    request_count: int = Field(ge=0)
    estimated_cost_micros: int = Field(ge=0)
    updated_at: datetime


class ExportModelUsageOut(BaseModel):
    history_complete: Literal[False] = False
    identity_scope: Literal["current_server_pseudonym"] = "current_server_pseudonym"
    costs_are_billing: Literal[False] = False
    calls: list[ExportModelCallOut]
    budget_days: list[ExportModelBudgetDayOut]


class StudentLearningExportOut(BaseModel):
    format_version: Literal[1] = 1
    scope: Literal["server_learning_records"] = "server_learning_records"
    exported_at: datetime
    profile: StudentProfileOut
    sessions: list[ExportLearningSessionOut]
    reviews: list[ReviewItemOut]
    review_history: list[ExportReviewHistoryOut]
    diagnostic_runs: list[dict[str, Any]]
    diagnostic_workspace: dict[str, Any]
    parent_access_records: ExportParentAccessRecordsOut
    stored_scan_records: list[ExportStoredScanOut] | None
    model_usage: ExportModelUsageOut
    excluded: list[str] = [
        "auth_credentials",
        "operational_logs",
        "question_answer_keys",
        "unsynced_device_data",
        "media_files",
    ]
