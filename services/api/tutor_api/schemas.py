"""请求与响应模型。形状以 contracts/openapi.yaml 为准；测试会把每个真实响应按契约再校验一遍。

请求模型一律 extra="forbid"：多出来的字段（包括别人的 student_id）直接 422。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RegionCode = Literal["CN-51", "CN-50"]
Grade = Literal["G10", "G11", "G12"]
Subject = Literal["math", "physics", "chemistry"]
AnswerMode = Literal["single_choice", "multiple_choice", "fill", "written", "experiment"]
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
    role: Literal["student"] = "student"
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"


class ProfileNotice(BaseModel):
    code: Literal["curriculum_unknown", "grade_unknown", "exam_year_estimated"]
    message: str


class StudentProfileOut(BaseModel):
    user_id: str
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


class KnowledgeRef(BaseModel):
    id: str
    code: str
    title: str


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


class Subquestion(BaseModel):
    key: str
    stem: str
    answer_mode: str
    options: list[QuestionOption] = Field(default_factory=list)
    blanks: list[QuestionBlank] = Field(default_factory=list)


class QuestionContent(BaseModel):
    stem: str
    options: list[QuestionOption] = Field(default_factory=list)
    blanks: list[QuestionBlank] = Field(default_factory=list)
    subquestions: list[Subquestion] = Field(default_factory=list)
    attachments: list[QuestionAttachment] = Field(default_factory=list)


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
    version: int
    grade: str | None
    content: QuestionContent
    assists: QuestionAssists
    judging_note: str | None


class QuestionPage(BaseModel):
    items: list[QuestionSummary]
    next_cursor: str | None


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


# ---------------------------------------------------------------- 会话与作答


class SessionCreateIn(_In):
    question_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    origin: SessionOrigin
    review_item_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    parent_session_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")


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
    submitted_attempts: int
    last_event_seq: int
    created_at: datetime
    updated_at: datetime


class AttemptCreateIn(_In):
    session_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


class AnswerBlank(_In):
    key: str = Field(min_length=1, max_length=16)
    value: str = Field(max_length=200)


class AnswerPayload(_In):
    selected_options: list[str] | None = Field(default=None, max_length=10)
    blanks: list[AnswerBlank] | None = Field(default=None, max_length=10)
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


class DraftOut(BaseModel):
    attempt_id: str
    revision: int
    answer: dict[str, Any] | None
    strokes: dict[str, Any] | None
    updated_at: datetime


class SubmitIn(_In):
    answer: AnswerPayload
    elapsed_ms: int | None = Field(default=None, ge=0)


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


class ProgressSummary(BaseModel):
    generated_at: datetime
    min_samples: int
    independent: RateStat
    assisted: RateStat
    hint_dependency: RateStat
    retest_success: RateStat
    variant_transfer: RateStat
    uncertain_attempts: int
    by_subject: list[ProgressBucket]
    by_answer_mode: list[ProgressBucket]
    by_difficulty: list[ProgressBucket]
    disclaimer: str
