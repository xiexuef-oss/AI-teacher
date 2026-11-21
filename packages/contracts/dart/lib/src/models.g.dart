// GENERATED CODE - DO NOT MODIFY BY HAND
// 由 tools/gen_dart_contracts.py 根据 contracts/openapi.yaml 生成。要改动请改契约后重新生成。
// dart format off
// ignore_for_file: type=lint

class ErrorEnvelope {
  const ErrorEnvelope({
    required this.error,
  });

  final ErrorBody error;

  factory ErrorEnvelope.fromJson(Map<String, dynamic> json) => ErrorEnvelope(
        error: ErrorBody.fromJson(json['error'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'error': error.toJson(),
      };
}

class ErrorBody {
  const ErrorBody({
    required this.code,
    required this.message,
    required this.details,
    required this.requestId,
  });

  final String code;
  final String message;
  final Map<String, dynamic> details;
  final String requestId;

  factory ErrorBody.fromJson(Map<String, dynamic> json) => ErrorBody(
        code: json['code'] as String,
        message: json['message'] as String,
        details: Map<String, dynamic>.from(json['details'] as Map),
        requestId: json['request_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'code': code,
        'message': message,
        'details': details,
        'request_id': requestId,
      };
}

class DiagnosticRevision {
  const DiagnosticRevision({
    required this.expectedRevision,
  });

  final int expectedRevision;

  factory DiagnosticRevision.fromJson(Map<String, dynamic> json) => DiagnosticRevision(
        expectedRevision: (json['expected_revision'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'expected_revision': expectedRevision,
      };
}

class DiagnosticCreate {
  const DiagnosticCreate({
    required this.subject,
    required this.expectedRevision,
    required this.expectedProfileRevision,
  });

  final Subject subject;
  final int expectedRevision;
  final int expectedProfileRevision;

  factory DiagnosticCreate.fromJson(Map<String, dynamic> json) => DiagnosticCreate(
        subject: Subject.fromJson(json['subject'] as String),
        expectedRevision: (json['expected_revision'] as num).toInt(),
        expectedProfileRevision: (json['expected_profile_revision'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'subject': subject.toJson(),
        'expected_revision': expectedRevision,
        'expected_profile_revision': expectedProfileRevision,
      };
}

class DiagnosticScope {
  const DiagnosticScope({
    required this.profileRevision,
    required this.regionCode,
    this.grade,
    this.examYear,
    this.curriculumVersion,
  });

  final int profileRevision;
  final RegionCode regionCode;
  final Grade? grade;
  final int? examYear;
  final String? curriculumVersion;

  factory DiagnosticScope.fromJson(Map<String, dynamic> json) => DiagnosticScope(
        profileRevision: (json['profile_revision'] as num).toInt(),
        regionCode: RegionCode.fromJson(json['region_code'] as String),
        grade: json['grade'] == null ? null : Grade.fromJson(json['grade'] as String),
        examYear: json['exam_year'] == null ? null : (json['exam_year'] as num).toInt(),
        curriculumVersion: json['curriculum_version'] == null ? null : json['curriculum_version'] as String,
      );

  Map<String, dynamic> toJson() => {
        'profile_revision': profileRevision,
        'region_code': regionCode.toJson(),
        'grade': grade?.toJson(),
        'exam_year': examYear,
        'curriculum_version': curriculumVersion,
      };
}

class DiagnosticSubmission {
  const DiagnosticSubmission({
    required this.attemptId,
    required this.independent,
    required this.evaluationState,
    this.isCorrect,
  });

  final String attemptId;
  final bool independent;
  final EvaluationState evaluationState;
  final bool? isCorrect;

  factory DiagnosticSubmission.fromJson(Map<String, dynamic> json) => DiagnosticSubmission(
        attemptId: json['attempt_id'] as String,
        independent: json['independent'] as bool,
        evaluationState: EvaluationState.fromJson(json['evaluation_state'] as String),
        isCorrect: json['is_correct'] == null ? null : json['is_correct'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'attempt_id': attemptId,
        'independent': independent,
        'evaluation_state': evaluationState.toJson(),
        'is_correct': isCorrect,
      };
}

class DiagnosticItem {
  const DiagnosticItem({
    required this.position,
    required this.question,
    required this.questionVersion,
    this.sessionId,
    this.submission,
  });

  final int position;
  final QuestionSummary question;
  final int questionVersion;
  final String? sessionId;
  final DiagnosticSubmission? submission;

  factory DiagnosticItem.fromJson(Map<String, dynamic> json) => DiagnosticItem(
        position: (json['position'] as num).toInt(),
        question: QuestionSummary.fromJson(json['question'] as Map<String, dynamic>),
        questionVersion: (json['question_version'] as num).toInt(),
        sessionId: json['session_id'] == null ? null : json['session_id'] as String,
        submission: json['submission'] == null ? null : DiagnosticSubmission.fromJson(json['submission'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'position': position,
        'question': question.toJson(),
        'question_version': questionVersion,
        'session_id': sessionId,
        'submission': submission?.toJson(),
      };
}

/// 仅关联会话首份提交的本轮计数；uncertain/pending不算对错。独立正确、独立不正确、借助提示和未确认四类互斥，总和等于submitted。不推算掌握度、分数或正确率。
class DiagnosticSummary {
  const DiagnosticSummary({
    required this.submitted,
    required this.independentCorrect,
    required this.independentIncorrect,
    required this.assisted,
    required this.unconfirmed,
  });

  final int submitted;
  final int independentCorrect;
  final int independentIncorrect;
  final int assisted;
  final int unconfirmed;

  factory DiagnosticSummary.fromJson(Map<String, dynamic> json) => DiagnosticSummary(
        submitted: (json['submitted'] as num).toInt(),
        independentCorrect: (json['independent_correct'] as num).toInt(),
        independentIncorrect: (json['independent_incorrect'] as num).toInt(),
        assisted: (json['assisted'] as num).toInt(),
        unconfirmed: (json['unconfirmed'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'submitted': submitted,
        'independent_correct': independentCorrect,
        'independent_incorrect': independentIncorrect,
        'assisted': assisted,
        'unconfirmed': unconfirmed,
      };
}

class DiagnosticRun {
  const DiagnosticRun({
    required this.id,
    required this.subject,
    required this.scope,
    required this.status,
    required this.items,
    required this.summary,
    required this.createdAt,
    this.abandonedAt,
  });

  final String id;
  final Subject subject;
  final DiagnosticScope scope;
  final String status;
  final List<DiagnosticItem> items;
  final DiagnosticSummary summary;
  final DateTime createdAt;
  final DateTime? abandonedAt;

  factory DiagnosticRun.fromJson(Map<String, dynamic> json) => DiagnosticRun(
        id: json['id'] as String,
        subject: Subject.fromJson(json['subject'] as String),
        scope: DiagnosticScope.fromJson(json['scope'] as Map<String, dynamic>),
        status: json['status'] as String,
        items: (json['items'] as List<dynamic>).map((e) => DiagnosticItem.fromJson(e as Map<String, dynamic>)).toList(),
        summary: DiagnosticSummary.fromJson(json['summary'] as Map<String, dynamic>),
        createdAt: DateTime.parse(json['created_at'] as String),
        abandonedAt: json['abandoned_at'] == null ? null : DateTime.parse(json['abandoned_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'subject': subject.toJson(),
        'scope': scope.toJson(),
        'status': status,
        'items': items.map((e) => e.toJson()).toList(),
        'summary': summary.toJson(),
        'created_at': createdAt.toUtc().toIso8601String(),
        'abandoned_at': abandonedAt?.toUtc().toIso8601String(),
      };
}

class DiagnosticHistoryPage {
  const DiagnosticHistoryPage({
    required this.items,
    this.nextCursor,
  });

  final List<DiagnosticRun> items;
  final String? nextCursor;

  factory DiagnosticHistoryPage.fromJson(Map<String, dynamic> json) => DiagnosticHistoryPage(
        items: (json['items'] as List<dynamic>).map((e) => DiagnosticRun.fromJson(e as Map<String, dynamic>)).toList(),
        nextCursor: json['next_cursor'] == null ? null : json['next_cursor'] as String,
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
        'next_cursor': nextCursor,
      };
}

class DiagnosticWorkspace {
  const DiagnosticWorkspace({
    required this.revision,
    this.run,
  });

  final int revision;
  final DiagnosticRun? run;

  factory DiagnosticWorkspace.fromJson(Map<String, dynamic> json) => DiagnosticWorkspace(
        revision: (json['revision'] as num).toInt(),
        run: json['run'] == null ? null : DiagnosticRun.fromJson(json['run'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'revision': revision,
        'run': run?.toJson(),
      };
}

/// 首发地区：四川 CN-51、重庆 CN-50。
enum RegionCode {
  cn51('CN-51'),
  cn50('CN-50'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const RegionCode(this.value);
  final String value;

  static RegionCode fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => RegionCode.$unknown);

  String toJson() => value;
}

/// 高一 G10、高二 G11、高三 G12。
enum Grade {
  g10('G10'),
  g11('G11'),
  g12('G12'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const Grade(this.value);
  final String value;

  static Grade fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => Grade.$unknown);

  String toJson() => value;
}

enum Subject {
  math('math'),
  physics('physics'),
  chemistry('chemistry'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const Subject(this.value);
  final String value;

  static Subject fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => Subject.$unknown);

  String toJson() => value;
}

/// estimated 表示按年级推算，user 表示用户手动设置。
enum ExamYearSource {
  estimated('estimated'),
  user('user'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const ExamYearSource(this.value);
  final String value;

  static ExamYearSource fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => ExamYearSource.$unknown);

  String toJson() => value;
}

/// 题型（考试意义上的类别）。
enum QuestionType {
  singleChoice('single_choice'),
  multipleChoice('multiple_choice'),
  fillBlank('fill_blank'),
  solution('solution'),
  proof('proof'),
  experiment('experiment'),
  inference('inference'),
  processFlow('process_flow'),
  comprehensive('comprehensive'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const QuestionType(this.value);
  final String value;

  static QuestionType fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => QuestionType.$unknown);

  String toJson() => value;
}

/// 作答区的渲染方式。single_choice、multiple_choice、fill 由服务端确定性判定； written（解答题）只保存作答，提交后给对照要点的自查，不自动评分； experiment（实验题）是带数据表和安全提示的主观题：数据表里留空的格子填在 `answer.cells`， 文字作答填在 `answer.parts`，和解答题一样不自动评分、提交后对照要点和参考数据自查； proof（证明题）有"已知 / 求证"（`content.proof`），学生把证明写成一步一步（每一步带依据）填在 `answer.steps`， 同样不自动评分、提交后对照参考证明和要点自查。
enum AnswerMode {
  singleChoice('single_choice'),
  multipleChoice('multiple_choice'),
  fill('fill'),
  written('written'),
  experiment('experiment'),
  proof('proof'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const AnswerMode(this.value);
  final String value;

  static AnswerMode fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => AnswerMode.$unknown);

  String toJson() => value;
}

enum SourceType {
  selfAuthored('self_authored'),
  textbookLicensed('textbook_licensed'),
  publicLicense('public_license'),
  gaokaoLicensed('gaokao_licensed'),
  aiGenerated('ai_generated'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const SourceType(this.value);
  final String value;

  static SourceType fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => SourceType.$unknown);

  String toJson() => value;
}

/// 学生可见的筛选分类：高考真题、模拟题、基础母题、AI 生成变式。
enum SourceCategory {
  gaokaoReal('gaokao_real'),
  mockExam('mock_exam'),
  foundation('foundation'),
  aiVariant('ai_variant'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const SourceCategory(this.value);
  final String value;

  static SourceCategory fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => SourceCategory.$unknown);

  String toJson() => value;
}

enum QuestionScope {
  all('all'),
  region('region'),
  general('general'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const QuestionScope(this.value);
  final String value;

  static QuestionScope fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => QuestionScope.$unknown);

  String toJson() => value;
}

/// region 表示带有审核过的地区适用标记；general 表示全国通用基础题。
enum ApplicabilityScope {
  region('region'),
  general('general'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const ApplicabilityScope(this.value);
  final String value;

  static ApplicabilityScope fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => ApplicabilityScope.$unknown);

  String toJson() => value;
}

/// new_topic 新题（首次使用时为入门选题）；review_mistake 复习旧错题；retest 间隔复测；weak_point 薄弱点；variant 变式。
enum TaskKind {
  newTopic('new_topic'),
  reviewMistake('review_mistake'),
  retest('retest'),
  weakPoint('weak_point'),
  variant('variant'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const TaskKind(this.value);
  final String value;

  static TaskKind fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => TaskKind.$unknown);

  String toJson() => value;
}

enum SessionOrigin {
  task('task'),
  practice('practice'),
  review('review'),
  variant('variant'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const SessionOrigin(this.value);
  final String value;

  static SessionOrigin fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => SessionOrigin.$unknown);

  String toJson() => value;
}

/// docs/06 教学状态机，与 tutor_event.schema.json 的 SessionState 一致。
enum SessionState {
  ready('READY'),
  independentAttempt('INDEPENDENT_ATTEMPT'),
  submitted('SUBMITTED'),
  diagnosed('DIAGNOSED'),
  hinted('HINTED'),
  standard('STANDARD'),
  fast('FAST'),
  visual('VISUAL'),
  variant('VARIANT'),
  reviewScheduled('REVIEW_SCHEDULED'),
  done('DONE'),
  fallback('FALLBACK'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const SessionState(this.value);
  final String value;

  static SessionState fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => SessionState.$unknown);

  String toJson() => value;
}

enum AttemptStatus {
  draft('draft'),
  submitted('submitted'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const AttemptStatus(this.value);
  final String value;

  static AttemptStatus fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => AttemptStatus.$unknown);

  String toJson() => value;
}

/// verified 为确定判定；uncertain 为无法可靠判断（不给确定结论）；pending 为等待评分；error 为评分出错。
enum EvaluationState {
  pending('pending'),
  verified('verified'),
  uncertain('uncertain'),
  error('error'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const EvaluationState(this.value);
  final String value;

  static EvaluationState fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => EvaluationState.$unknown);

  String toJson() => value;
}

enum EvaluationOutcome {
  correct('correct'),
  partiallyCorrect('partially_correct'),
  incorrect('incorrect'),
  undetermined('undetermined'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const EvaluationOutcome(this.value);
  final String value;

  static EvaluationOutcome fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => EvaluationOutcome.$unknown);

  String toJson() => value;
}

enum FeedbackCode {
  correct('correct'),
  wrongOption('wrong_option'),
  missedOptions('missed_options'),
  valueIncorrect('value_incorrect'),
  unitMissing('unit_missing'),
  unitMismatch('unit_mismatch'),
  formatUnrecognized('format_unrecognized'),
  equivalenceUnconfirmed('equivalence_unconfirmed'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const FeedbackCode(this.value);
  final String value;

  static FeedbackCode fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => FeedbackCode.$unknown);

  String toJson() => value;
}

enum TutorActionType {
  requestHint('request_hint'),
  requestStandard('request_standard'),
  requestFast('request_fast'),
  requestVisual('request_visual'),
  markUnderstood('mark_understood'),
  markConfused('mark_confused'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const TutorActionType(this.value);
  final String value;

  static TutorActionType fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => TutorActionType.$unknown);

  String toJson() => value;
}

enum TutorEventType {
  diagnosis('diagnosis'),
  hint('hint'),
  standard('standard'),
  fast('fast'),
  visual('visual'),
  ask('ask'),
  notice('notice'),
  uncertainty('uncertainty'),
  fallback('fallback'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const TutorEventType(this.value);
  final String value;

  static TutorEventType fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => TutorEventType.$unknown);

  String toJson() => value;
}

enum TutorEventSource {
  reviewedContent('reviewed_content'),
  model('model'),
  ruleEngine('rule_engine'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const TutorEventSource(this.value);
  final String value;

  static TutorEventSource fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => TutorEventSource.$unknown);

  String toJson() => value;
}

enum ReviewStatus {
  scheduled('scheduled'),
  mastered('mastered'),
  paused('paused'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const ReviewStatus(this.value);
  final String value;

  static ReviewStatus fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => ReviewStatus.$unknown);

  String toJson() => value;
}

enum ReviewResult {
  passed('passed'),
  failed('failed'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const ReviewResult(this.value);
  final String value;

  static ReviewResult fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => ReviewResult.$unknown);

  String toJson() => value;
}

enum ReviewScope {
  due('due'),
  all('all'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const ReviewScope(this.value);
  final String value;

  static ReviewScope fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => ReviewScope.$unknown);

  String toJson() => value;
}

class Health {
  const Health({
    required this.status,
    required this.apiVersion,
    required this.contractVersion,
    required this.environment,
    required this.localIdentityMock,
    required this.externalModelCalls,
    required this.serverTime,
  });

  final String status;
  final String apiVersion;
  final String contractVersion;
  final String environment;
  final bool localIdentityMock;
  final bool externalModelCalls;
  final DateTime serverTime;

  factory Health.fromJson(Map<String, dynamic> json) => Health(
        status: json['status'] as String,
        apiVersion: json['api_version'] as String,
        contractVersion: json['contract_version'] as String,
        environment: json['environment'] as String,
        localIdentityMock: json['local_identity_mock'] as bool,
        externalModelCalls: json['external_model_calls'] as bool,
        serverTime: DateTime.parse(json['server_time'] as String),
      );

  Map<String, dynamic> toJson() => {
        'status': status,
        'api_version': apiVersion,
        'contract_version': contractVersion,
        'environment': environment,
        'local_identity_mock': localIdentityMock,
        'external_model_calls': externalModelCalls,
        'server_time': serverTime.toUtc().toIso8601String(),
      };
}

class LaunchConfig {
  const LaunchConfig({
    required this.regions,
    required this.grades,
    required this.subjects,
    required this.curriculumVersions,
    required this.schoolYearStartMonth,
    required this.examYearMin,
    required this.examYearMax,
  });

  final List<RegionOption> regions;
  final List<GradeOption> grades;
  final List<SubjectOption> subjects;
  final List<CurriculumOption> curriculumVersions;
  final int schoolYearStartMonth;
  final int examYearMin;
  final int examYearMax;

  factory LaunchConfig.fromJson(Map<String, dynamic> json) => LaunchConfig(
        regions: (json['regions'] as List<dynamic>).map((e) => RegionOption.fromJson(e as Map<String, dynamic>)).toList(),
        grades: (json['grades'] as List<dynamic>).map((e) => GradeOption.fromJson(e as Map<String, dynamic>)).toList(),
        subjects: (json['subjects'] as List<dynamic>).map((e) => SubjectOption.fromJson(e as Map<String, dynamic>)).toList(),
        curriculumVersions: (json['curriculum_versions'] as List<dynamic>).map((e) => CurriculumOption.fromJson(e as Map<String, dynamic>)).toList(),
        schoolYearStartMonth: (json['school_year_start_month'] as num).toInt(),
        examYearMin: (json['exam_year_min'] as num).toInt(),
        examYearMax: (json['exam_year_max'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'regions': regions.map((e) => e.toJson()).toList(),
        'grades': grades.map((e) => e.toJson()).toList(),
        'subjects': subjects.map((e) => e.toJson()).toList(),
        'curriculum_versions': curriculumVersions.map((e) => e.toJson()).toList(),
        'school_year_start_month': schoolYearStartMonth,
        'exam_year_min': examYearMin,
        'exam_year_max': examYearMax,
      };
}

class RegionOption {
  const RegionOption({
    required this.code,
    required this.name,
  });

  final RegionCode code;
  final String name;

  factory RegionOption.fromJson(Map<String, dynamic> json) => RegionOption(
        code: RegionCode.fromJson(json['code'] as String),
        name: json['name'] as String,
      );

  Map<String, dynamic> toJson() => {
        'code': code.toJson(),
        'name': name,
      };
}

class GradeOption {
  const GradeOption({
    required this.code,
    required this.name,
    required this.estimatedExamYear,
  });

  final Grade code;
  final String name;
  final int estimatedExamYear;

  factory GradeOption.fromJson(Map<String, dynamic> json) => GradeOption(
        code: Grade.fromJson(json['code'] as String),
        name: json['name'] as String,
        estimatedExamYear: (json['estimated_exam_year'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'code': code.toJson(),
        'name': name,
        'estimated_exam_year': estimatedExamYear,
      };
}

class SubjectOption {
  const SubjectOption({
    required this.code,
    required this.name,
  });

  final Subject code;
  final String name;

  factory SubjectOption.fromJson(Map<String, dynamic> json) => SubjectOption(
        code: Subject.fromJson(json['code'] as String),
        name: json['name'] as String,
      );

  Map<String, dynamic> toJson() => {
        'code': code.toJson(),
        'name': name,
      };
}

class CurriculumOption {
  const CurriculumOption({
    required this.code,
    required this.name,
  });

  final String code;
  final String name;

  factory CurriculumOption.fromJson(Map<String, dynamic> json) => CurriculumOption(
        code: json['code'] as String,
        name: json['name'] as String,
      );

  Map<String, dynamic> toJson() => {
        'code': code,
        'name': name,
      };
}

/// 本地身份 Mock 可以发放的角色；缺省为 student。parent 只是本地联调用的 Mock 角色：学生自己授权、可以撤销， 不代表任何监护人核验——真实登录与监护授权方案（Q-03）冻结之前，这是唯一的家长身份来源。
enum LocalRole {
  student('student'),
  parent('parent'),
  reviewer('reviewer'),
  admin('admin'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const LocalRole(this.value);
  final String value;

  static LocalRole fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => LocalRole.$unknown);

  String toJson() => value;
}

class LocalIdentity {
  const LocalIdentity({
    required this.userId,
    required this.role,
    required this.accessToken,
    required this.tokenType,
  });

  final String userId;
  final LocalRole role;
  final String accessToken;
  final String tokenType;

  factory LocalIdentity.fromJson(Map<String, dynamic> json) => LocalIdentity(
        userId: json['user_id'] as String,
        role: LocalRole.fromJson(json['role'] as String),
        accessToken: json['access_token'] as String,
        tokenType: json['token_type'] as String,
      );

  Map<String, dynamic> toJson() => {
        'user_id': userId,
        'role': role.toJson(),
        'access_token': accessToken,
        'token_type': tokenType,
      };
}

class LearningPackPdf {
  const LearningPackPdf({
    required this.revision,
    required this.sha256,
    required this.contentBase64,
  });

  final int revision;
  final String sha256;
  final String contentBase64;

  factory LearningPackPdf.fromJson(Map<String, dynamic> json) => LearningPackPdf(
        revision: (json['revision'] as num).toInt(),
        sha256: json['sha256'] as String,
        contentBase64: json['content_base64'] as String,
      );

  Map<String, dynamic> toJson() => {
        'revision': revision,
        'sha256': sha256,
        'content_base64': contentBase64,
      };
}

class PaperReviewSchedule {
  const PaperReviewSchedule({
    required this.items,
  });

  final List<PaperReviewScheduleItem> items;

  factory PaperReviewSchedule.fromJson(Map<String, dynamic> json) => PaperReviewSchedule(
        items: (json['items'] as List<dynamic>).map((e) => PaperReviewScheduleItem.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class PaperReviewScheduleItem {
  const PaperReviewScheduleItem({
    required this.knowledgeId,
    required this.title,
    required this.stage,
    required this.dueOn,
    required this.estimatedAnchor,
  });

  final String knowledgeId;
  final String title;
  final int stage;
  final String dueOn;
  final bool estimatedAnchor;

  factory PaperReviewScheduleItem.fromJson(Map<String, dynamic> json) => PaperReviewScheduleItem(
        knowledgeId: json['knowledge_id'] as String,
        title: json['title'] as String,
        stage: (json['stage'] as num).toInt(),
        dueOn: json['due_on'] as String,
        estimatedAnchor: json['estimated_anchor'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'knowledge_id': knowledgeId,
        'title': title,
        'stage': stage,
        'due_on': dueOn,
        'estimated_anchor': estimatedAnchor,
      };
}

class LearningPackHistory {
  const LearningPackHistory({
    required this.ids,
    this.nextCursor,
  });

  final List<String> ids;
  final String? nextCursor;

  factory LearningPackHistory.fromJson(Map<String, dynamic> json) => LearningPackHistory(
        ids: (json['ids'] as List<dynamic>).map((e) => e as String).toList(),
        nextCursor: json['next_cursor'] == null ? null : json['next_cursor'] as String,
      );

  Map<String, dynamic> toJson() => {
        'ids': ids,
        if (nextCursor != null) 'next_cursor': nextCursor,
      };
}

class LearningPackItems {
  const LearningPackItems({
    required this.items,
  });

  final List<LearningPackItem> items;

  factory LearningPackItems.fromJson(Map<String, dynamic> json) => LearningPackItems(
        items: (json['items'] as List<dynamic>).map((e) => LearningPackItem.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class LearningPackItem {
  const LearningPackItem({
    required this.revision,
    required this.code,
    required this.questionVersionId,
  });

  final int revision;
  final String code;
  final String questionVersionId;

  factory LearningPackItem.fromJson(Map<String, dynamic> json) => LearningPackItem(
        revision: (json['revision'] as num).toInt(),
        code: json['code'] as String,
        questionVersionId: json['question_version_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'revision': revision,
        'code': code,
        'question_version_id': questionVersionId,
      };
}

class LearningPackReturnRecord {
  const LearningPackReturnRecord({
    this.transcriptRevision,
    required this.item,
    required this.transcript,
    required this.confirmedAt,
  });

  final int? transcriptRevision;
  final LearningPackItem item;
  final String transcript;
  final DateTime confirmedAt;

  factory LearningPackReturnRecord.fromJson(Map<String, dynamic> json) => LearningPackReturnRecord(
        transcriptRevision: json['transcript_revision'] == null ? null : (json['transcript_revision'] as num).toInt(),
        item: LearningPackItem.fromJson(json['item'] as Map<String, dynamic>),
        transcript: json['transcript'] as String,
        confirmedAt: DateTime.parse(json['confirmed_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        if (transcriptRevision != null) 'transcript_revision': transcriptRevision,
        'item': item.toJson(),
        'transcript': transcript,
        'confirmed_at': confirmedAt.toUtc().toIso8601String(),
      };
}

class LearningPackCorrection {
  const LearningPackCorrection({
    required this.expectedRevision,
    required this.transcript,
  });

  final int expectedRevision;
  final String transcript;

  factory LearningPackCorrection.fromJson(Map<String, dynamic> json) => LearningPackCorrection(
        expectedRevision: (json['expected_revision'] as num).toInt(),
        transcript: json['transcript'] as String,
      );

  Map<String, dynamic> toJson() => {
        'expected_revision': expectedRevision,
        'transcript': transcript,
      };
}

class LearningPackPhotoOcrRequest {
  const LearningPackPhotoOcrRequest({
    required this.photoIds,
  });

  final List<String> photoIds;

  factory LearningPackPhotoOcrRequest.fromJson(Map<String, dynamic> json) => LearningPackPhotoOcrRequest(
        photoIds: (json['photo_ids'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        'photo_ids': photoIds,
      };
}

class LearningPackPhotoOcr {
  const LearningPackPhotoOcr({
    required this.id,
    required this.item,
    required this.status,
    required this.photoIds,
    this.candidate,
  });

  final String id;
  final LearningPackItem item;
  final String status;
  final List<String> photoIds;
  final String? candidate;

  factory LearningPackPhotoOcr.fromJson(Map<String, dynamic> json) => LearningPackPhotoOcr(
        id: json['id'] as String,
        item: LearningPackItem.fromJson(json['item'] as Map<String, dynamic>),
        status: json['status'] as String,
        photoIds: (json['photo_ids'] as List<dynamic>).map((e) => e as String).toList(),
        candidate: json['candidate'] == null ? null : json['candidate'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'item': item.toJson(),
        'status': status,
        'photo_ids': photoIds,
        if (candidate != null) 'candidate': candidate,
      };
}

class LearningPackReturnRequest {
  const LearningPackReturnRequest({
    required this.transcript,
    this.completedOn,
    this.independence,
    this.photoIds,
  });

  final String transcript;
  final String? completedOn;
  final String? independence;
  final List<String>? photoIds;

  factory LearningPackReturnRequest.fromJson(Map<String, dynamic> json) => LearningPackReturnRequest(
        transcript: json['transcript'] as String,
        completedOn: json['completed_on'] == null ? null : json['completed_on'] as String,
        independence: json['independence'] == null ? null : json['independence'] as String,
        photoIds: json['photo_ids'] == null ? null : (json['photo_ids'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        'transcript': transcript,
        if (completedOn != null) 'completed_on': completedOn,
        if (independence != null) 'independence': independence,
        if (photoIds != null) 'photo_ids': photoIds,
      };
}

class LearningPackRequest {
  const LearningPackRequest({
    required this.schoolMinutes,
  });

  final int schoolMinutes;

  factory LearningPackRequest.fromJson(Map<String, dynamic> json) => LearningPackRequest(
        schoolMinutes: (json['school_minutes'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'school_minutes': schoolMinutes,
      };
}

class LearningJobStatus {
  const LearningJobStatus({
    required this.id,
    required this.status,
    required this.attempts,
    this.packResult,
    this.reviews,
  });

  final String id;
  final String status;
  final int attempts;
  final String? packResult;
  final List<PaperReviewPlanItem>? reviews;

  factory LearningJobStatus.fromJson(Map<String, dynamic> json) => LearningJobStatus(
        id: json['id'] as String,
        status: json['status'] as String,
        attempts: (json['attempts'] as num).toInt(),
        packResult: json['pack_result'] == null ? null : json['pack_result'] as String,
        reviews: json['reviews'] == null ? null : (json['reviews'] as List<dynamic>).map((e) => PaperReviewPlanItem.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'status': status,
        'attempts': attempts,
        if (packResult != null) 'pack_result': packResult,
        if (reviews != null) 'reviews': reviews?.map((e) => e.toJson()).toList(),
      };
}

class PaperReviewPlanItem {
  const PaperReviewPlanItem({
    required this.knowledgeId,
    required this.title,
    required this.originalDueOn,
    this.suggestedOn,
    this.deferredReason,
  });

  final String knowledgeId;
  final String title;
  final String originalDueOn;
  final String? suggestedOn;
  final String? deferredReason;

  factory PaperReviewPlanItem.fromJson(Map<String, dynamic> json) => PaperReviewPlanItem(
        knowledgeId: json['knowledge_id'] as String,
        title: json['title'] as String,
        originalDueOn: json['original_due_on'] as String,
        suggestedOn: json['suggested_on'] == null ? null : json['suggested_on'] as String,
        deferredReason: json['deferred_reason'] == null ? null : json['deferred_reason'] as String,
      );

  Map<String, dynamic> toJson() => {
        'knowledge_id': knowledgeId,
        'title': title,
        'original_due_on': originalDueOn,
        if (suggestedOn != null) 'suggested_on': suggestedOn,
        if (deferredReason != null) 'deferred_reason': deferredReason,
      };
}

class LearningSettings {
  const LearningSettings({
    required this.mode,
    required this.weeklyMinutes,
    required this.weekdays,
    this.schoolProgress,
    this.examScope,
  });

  final String mode;
  final int weeklyMinutes;
  final List<int> weekdays;
  final String? schoolProgress;
  final String? examScope;

  factory LearningSettings.fromJson(Map<String, dynamic> json) => LearningSettings(
        mode: json['mode'] as String,
        weeklyMinutes: (json['weekly_minutes'] as num).toInt(),
        weekdays: (json['weekdays'] as List<dynamic>).map((e) => (e as num).toInt()).toList(),
        schoolProgress: json['school_progress'] == null ? null : json['school_progress'] as String,
        examScope: json['exam_scope'] == null ? null : json['exam_scope'] as String,
      );

  Map<String, dynamic> toJson() => {
        'mode': mode,
        'weekly_minutes': weeklyMinutes,
        'weekdays': weekdays,
        if (schoolProgress != null) 'school_progress': schoolProgress,
        if (examScope != null) 'exam_scope': examScope,
      };
}

class StudentProfile {
  const StudentProfile({
    this.revision,
    this.learningSettings,
    required this.userId,
    this.displayName,
    this.regionCode,
    this.grade,
    required this.subjects,
    this.examYear,
    this.examYearSource,
    this.examSchemeCode,
    this.curriculumVersion,
    required this.onboardingCompleted,
    required this.notices,
    required this.updatedAt,
  });

  final int? revision;
  final LearningSettings? learningSettings;
  final String userId;
  final String? displayName;
  final RegionCode? regionCode;
  final Grade? grade;
  final List<Subject> subjects;
  final int? examYear;
  final ExamYearSource? examYearSource;
  final String? examSchemeCode;
  final String? curriculumVersion;
  final bool onboardingCompleted;
  final List<ProfileNotice> notices;
  final DateTime updatedAt;

  factory StudentProfile.fromJson(Map<String, dynamic> json) => StudentProfile(
        revision: json['revision'] == null ? null : (json['revision'] as num).toInt(),
        learningSettings: json['learning_settings'] == null ? null : LearningSettings.fromJson(json['learning_settings'] as Map<String, dynamic>),
        userId: json['user_id'] as String,
        displayName: json['display_name'] == null ? null : json['display_name'] as String,
        regionCode: json['region_code'] == null ? null : RegionCode.fromJson(json['region_code'] as String),
        grade: json['grade'] == null ? null : Grade.fromJson(json['grade'] as String),
        subjects: (json['subjects'] as List<dynamic>).map((e) => Subject.fromJson(e as String)).toList(),
        examYear: json['exam_year'] == null ? null : (json['exam_year'] as num).toInt(),
        examYearSource: json['exam_year_source'] == null ? null : ExamYearSource.fromJson(json['exam_year_source'] as String),
        examSchemeCode: json['exam_scheme_code'] == null ? null : json['exam_scheme_code'] as String,
        curriculumVersion: json['curriculum_version'] == null ? null : json['curriculum_version'] as String,
        onboardingCompleted: json['onboarding_completed'] as bool,
        notices: (json['notices'] as List<dynamic>).map((e) => ProfileNotice.fromJson(e as Map<String, dynamic>)).toList(),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        if (revision != null) 'revision': revision,
        if (learningSettings != null) 'learning_settings': learningSettings?.toJson(),
        'user_id': userId,
        'display_name': displayName,
        'region_code': regionCode?.toJson(),
        'grade': grade?.toJson(),
        'subjects': subjects.map((e) => e.toJson()).toList(),
        'exam_year': examYear,
        'exam_year_source': examYearSource?.toJson(),
        'exam_scheme_code': examSchemeCode,
        'curriculum_version': curriculumVersion,
        'onboarding_completed': onboardingCompleted,
        'notices': notices.map((e) => e.toJson()).toList(),
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class ProfileNotice {
  const ProfileNotice({
    required this.code,
    required this.message,
  });

  final String code;
  final String message;

  factory ProfileNotice.fromJson(Map<String, dynamic> json) => ProfileNotice(
        code: json['code'] as String,
        message: json['message'] as String,
      );

  Map<String, dynamic> toJson() => {
        'code': code,
        'message': message,
      };
}

class ProfileUpdate {
  const ProfileUpdate({
    this.learningSettings,
    required this.expectedRevision,
    required this.regionCode,
    required this.subjects,
    this.grade,
    this.examYear,
    this.curriculumVersion,
    this.displayName,
  });

  final LearningSettings? learningSettings;
  final int expectedRevision;
  final RegionCode regionCode;
  final List<Subject> subjects;
  final Grade? grade;
  final int? examYear;
  final String? curriculumVersion;
  final String? displayName;

  factory ProfileUpdate.fromJson(Map<String, dynamic> json) => ProfileUpdate(
        learningSettings: json['learning_settings'] == null ? null : LearningSettings.fromJson(json['learning_settings'] as Map<String, dynamic>),
        expectedRevision: (json['expected_revision'] as num).toInt(),
        regionCode: RegionCode.fromJson(json['region_code'] as String),
        subjects: (json['subjects'] as List<dynamic>).map((e) => Subject.fromJson(e as String)).toList(),
        grade: json['grade'] == null ? null : Grade.fromJson(json['grade'] as String),
        examYear: json['exam_year'] == null ? null : (json['exam_year'] as num).toInt(),
        curriculumVersion: json['curriculum_version'] == null ? null : json['curriculum_version'] as String,
        displayName: json['display_name'] == null ? null : json['display_name'] as String,
      );

  Map<String, dynamic> toJson() => {
        if (learningSettings != null) 'learning_settings': learningSettings?.toJson(),
        'expected_revision': expectedRevision,
        'region_code': regionCode.toJson(),
        'subjects': subjects.map((e) => e.toJson()).toList(),
        if (grade != null) 'grade': grade?.toJson(),
        if (examYear != null) 'exam_year': examYear,
        if (curriculumVersion != null) 'curriculum_version': curriculumVersion,
        if (displayName != null) 'display_name': displayName,
      };
}

class TodayTasks {
  const TodayTasks({
    required this.date,
    this.coldStart,
    required this.items,
  });

  final String date;
  final bool? coldStart;
  final List<StudyTask> items;

  factory TodayTasks.fromJson(Map<String, dynamic> json) => TodayTasks(
        date: json['date'] as String,
        coldStart: json['cold_start'] == null ? null : json['cold_start'] as bool,
        items: (json['items'] as List<dynamic>).map((e) => StudyTask.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'date': date,
        if (coldStart != null) 'cold_start': coldStart,
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class QuestionTopic {
  const QuestionTopic({
    required this.id,
    required this.code,
    required this.title,
    required this.subject,
    required this.questionCount,
  });

  final String id;
  final String code;
  final String title;
  final Subject subject;
  final int questionCount;

  factory QuestionTopic.fromJson(Map<String, dynamic> json) => QuestionTopic(
        id: json['id'] as String,
        code: json['code'] as String,
        title: json['title'] as String,
        subject: Subject.fromJson(json['subject'] as String),
        questionCount: (json['question_count'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'code': code,
        'title': title,
        'subject': subject.toJson(),
        'question_count': questionCount,
      };
}

class QuestionTopicPage {
  const QuestionTopicPage({
    required this.items,
  });

  final List<QuestionTopic> items;

  factory QuestionTopicPage.fromJson(Map<String, dynamic> json) => QuestionTopicPage(
        items: (json['items'] as List<dynamic>).map((e) => QuestionTopic.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class StudyTask {
  const StudyTask({
    required this.id,
    required this.kind,
    required this.title,
    required this.reason,
    required this.subject,
    required this.questionId,
    this.reviewItemId,
    required this.applicability,
    required this.estimatedMinutes,
  });

  final String id;
  final TaskKind kind;
  final String title;
  final String reason;
  final Subject subject;
  final String questionId;
  final String? reviewItemId;
  final Applicability applicability;
  final int estimatedMinutes;

  factory StudyTask.fromJson(Map<String, dynamic> json) => StudyTask(
        id: json['id'] as String,
        kind: TaskKind.fromJson(json['kind'] as String),
        title: json['title'] as String,
        reason: json['reason'] as String,
        subject: Subject.fromJson(json['subject'] as String),
        questionId: json['question_id'] as String,
        reviewItemId: json['review_item_id'] == null ? null : json['review_item_id'] as String,
        applicability: Applicability.fromJson(json['applicability'] as Map<String, dynamic>),
        estimatedMinutes: (json['estimated_minutes'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'kind': kind.toJson(),
        'title': title,
        'reason': reason,
        'subject': subject.toJson(),
        'question_id': questionId,
        'review_item_id': reviewItemId,
        'applicability': applicability.toJson(),
        'estimated_minutes': estimatedMinutes,
      };
}

class Applicability {
  const Applicability({
    required this.scope,
    required this.label,
    required this.recommendedRegions,
    this.originRegionCode,
    this.examYearFrom,
    this.examYearTo,
    required this.disclaimer,
  });

  final ApplicabilityScope scope;
  final String label;
  final List<RegionCode> recommendedRegions;
  final String? originRegionCode;
  final int? examYearFrom;
  final int? examYearTo;
  final String disclaimer;

  factory Applicability.fromJson(Map<String, dynamic> json) => Applicability(
        scope: ApplicabilityScope.fromJson(json['scope'] as String),
        label: json['label'] as String,
        recommendedRegions: (json['recommended_regions'] as List<dynamic>).map((e) => RegionCode.fromJson(e as String)).toList(),
        originRegionCode: json['origin_region_code'] == null ? null : json['origin_region_code'] as String,
        examYearFrom: json['exam_year_from'] == null ? null : (json['exam_year_from'] as num).toInt(),
        examYearTo: json['exam_year_to'] == null ? null : (json['exam_year_to'] as num).toInt(),
        disclaimer: json['disclaimer'] as String,
      );

  Map<String, dynamic> toJson() => {
        'scope': scope.toJson(),
        'label': label,
        'recommended_regions': recommendedRegions.map((e) => e.toJson()).toList(),
        'origin_region_code': originRegionCode,
        'exam_year_from': examYearFrom,
        'exam_year_to': examYearTo,
        'disclaimer': disclaimer,
      };
}

/// 导入时校验归属及页序后的来源位置声明；不含原文、预览或文件访问凭据，不承诺精确文本对应。
class QuestionOriginLocation {
  const QuestionOriginLocation({
    required this.fileSha256,
    required this.fileKind,
    required this.locatorKind,
    required this.index,
    this.declaredBlock,
  });

  final String fileSha256;
  final DocImportFileKind fileKind;
  final String locatorKind;
  final int index;
  final int? declaredBlock;

  factory QuestionOriginLocation.fromJson(Map<String, dynamic> json) => QuestionOriginLocation(
        fileSha256: json['file_sha256'] as String,
        fileKind: DocImportFileKind.fromJson(json['file_kind'] as String),
        locatorKind: json['locator_kind'] as String,
        index: (json['index'] as num).toInt(),
        declaredBlock: json['declared_block'] == null ? null : (json['declared_block'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'file_sha256': fileSha256,
        'file_kind': fileKind.toJson(),
        'locator_kind': locatorKind,
        'index': index,
        'declared_block': declaredBlock,
      };
}

/// 此题目版本的导入来源快照。原文件仍按临时任务期限管理，本记录仅有元数据；来源声明不等于版权审校或精确引文。
class QuestionProvenance {
  const QuestionProvenance({
    required this.sourceSnapshot,
    required this.origins,
    required this.relation,
    this.parentVersion,
    required this.access,
  });

  final QuestionSource sourceSnapshot;
  final List<QuestionOriginLocation> origins;
  final String relation;
  final int? parentVersion;
  final String access;

  factory QuestionProvenance.fromJson(Map<String, dynamic> json) => QuestionProvenance(
        sourceSnapshot: QuestionSource.fromJson(json['source_snapshot'] as Map<String, dynamic>),
        origins: (json['origins'] as List<dynamic>).map((e) => QuestionOriginLocation.fromJson(e as Map<String, dynamic>)).toList(),
        relation: json['relation'] as String,
        parentVersion: json['parent_version'] == null ? null : (json['parent_version'] as num).toInt(),
        access: json['access'] as String,
      );

  Map<String, dynamic> toJson() => {
        'source_snapshot': sourceSnapshot.toJson(),
        'origins': origins.map((e) => e.toJson()).toList(),
        'relation': relation,
        'parent_version': parentVersion,
        'access': access,
      };
}

class QuestionSource {
  const QuestionSource({
    required this.sourceType,
    required this.sourceCategory,
    this.sourceName,
    this.sourceYear,
    required this.sourceLicense,
    this.sourceUrl,
    required this.isEngineeringSample,
    required this.label,
  });

  final SourceType sourceType;
  final SourceCategory sourceCategory;
  final String? sourceName;
  final int? sourceYear;
  final String sourceLicense;
  final String? sourceUrl;
  final bool isEngineeringSample;
  final String label;

  factory QuestionSource.fromJson(Map<String, dynamic> json) => QuestionSource(
        sourceType: SourceType.fromJson(json['source_type'] as String),
        sourceCategory: SourceCategory.fromJson(json['source_category'] as String),
        sourceName: json['source_name'] == null ? null : json['source_name'] as String,
        sourceYear: json['source_year'] == null ? null : (json['source_year'] as num).toInt(),
        sourceLicense: json['source_license'] as String,
        sourceUrl: json['source_url'] == null ? null : json['source_url'] as String,
        isEngineeringSample: json['is_engineering_sample'] as bool,
        label: json['label'] as String,
      );

  Map<String, dynamic> toJson() => {
        'source_type': sourceType.toJson(),
        'source_category': sourceCategory.toJson(),
        'source_name': sourceName,
        'source_year': sourceYear,
        'source_license': sourceLicense,
        'source_url': sourceUrl,
        'is_engineering_sample': isEngineeringSample,
        'label': label,
      };
}

class KnowledgeRef {
  const KnowledgeRef({
    required this.id,
    required this.code,
    required this.title,
  });

  final String id;
  final String code;
  final String title;

  factory KnowledgeRef.fromJson(Map<String, dynamic> json) => KnowledgeRef(
        id: json['id'] as String,
        code: json['code'] as String,
        title: json['title'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'code': code,
        'title': title,
      };
}

class QuestionOption {
  const QuestionOption({
    required this.key,
    required this.text,
  });

  final String key;
  final String text;

  factory QuestionOption.fromJson(Map<String, dynamic> json) => QuestionOption(
        key: json['key'] as String,
        text: json['text'] as String,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'text': text,
      };
}

class QuestionBlank {
  const QuestionBlank({
    required this.key,
    this.label,
    this.unitHint,
    this.placeholder,
  });

  final String key;
  final String? label;
  final String? unitHint;
  final String? placeholder;

  factory QuestionBlank.fromJson(Map<String, dynamic> json) => QuestionBlank(
        key: json['key'] as String,
        label: json['label'] == null ? null : json['label'] as String,
        unitHint: json['unit_hint'] == null ? null : json['unit_hint'] as String,
        placeholder: json['placeholder'] == null ? null : json['placeholder'] as String,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'label': label,
        'unit_hint': unitHint,
        'placeholder': placeholder,
      };
}

class QuestionAttachment {
  const QuestionAttachment({
    required this.kind,
    this.mediaId,
    required this.alt,
  });

  final String kind;
  final String? mediaId;
  final String alt;

  factory QuestionAttachment.fromJson(Map<String, dynamic> json) => QuestionAttachment(
        kind: json['kind'] as String,
        mediaId: json['media_id'] == null ? null : json['media_id'] as String,
        alt: json['alt'] as String,
      );

  Map<String, dynamic> toJson() => {
        'kind': kind,
        'media_id': mediaId,
        'alt': alt,
      };
}

class Subquestion {
  const Subquestion({
    required this.key,
    required this.stem,
    required this.answerMode,
    required this.options,
    required this.blanks,
  });

  final String key;
  final String stem;
  final AnswerMode answerMode;
  final List<QuestionOption> options;
  final List<QuestionBlank> blanks;

  factory Subquestion.fromJson(Map<String, dynamic> json) => Subquestion(
        key: json['key'] as String,
        stem: json['stem'] as String,
        answerMode: AnswerMode.fromJson(json['answer_mode'] as String),
        options: (json['options'] as List<dynamic>).map((e) => QuestionOption.fromJson(e as Map<String, dynamic>)).toList(),
        blanks: (json['blanks'] as List<dynamic>).map((e) => QuestionBlank.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'stem': stem,
        'answer_mode': answerMode.toJson(),
        'options': options.map((e) => e.toJson()).toList(),
        'blanks': blanks.map((e) => e.toJson()).toList(),
      };
}

/// 实验的风险分级。low 只涉及常规的低风险操作；medium 需要提醒防护措施； high（高风险）现在不收录：还没有专项审核流程，程序校验会拦住它，不会发给学生。
enum ExperimentSafetyLevel {
  low('low'),
  medium('medium'),
  high('high'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const ExperimentSafetyLevel(this.value);
  final String value;

  static ExperimentSafetyLevel fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => ExperimentSafetyLevel.$unknown);

  String toJson() => value;
}

/// 实验安全提示。每道实验题都必须有，上线前由审核员逐条确认。 这是纸面练习，不是操作指导：题目、提示和解法都不给现实操作的步骤诱导。
class ExperimentSafety {
  const ExperimentSafety({
    required this.level,
    required this.notes,
  });

  final ExperimentSafetyLevel level;
  final List<String> notes;

  factory ExperimentSafety.fromJson(Map<String, dynamic> json) => ExperimentSafety(
        level: ExperimentSafetyLevel.fromJson(json['level'] as String),
        notes: (json['notes'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        'level': level.toJson(),
        'notes': notes,
      };
}

class DataTableColumn {
  const DataTableColumn({
    required this.key,
    required this.label,
    this.unit,
  });

  final String key;
  final String label;
  final String? unit;

  factory DataTableColumn.fromJson(Map<String, dynamic> json) => DataTableColumn(
        key: json['key'] as String,
        label: json['label'] as String,
        unit: json['unit'] == null ? null : json['unit'] as String,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'label': label,
        'unit': unit,
      };
}

class DataTableCell {
  const DataTableCell({
    required this.col,
    this.text,
  });

  final String col;
  final String? text;

  factory DataTableCell.fromJson(Map<String, dynamic> json) => DataTableCell(
        col: json['col'] as String,
        text: json['text'] == null ? null : json['text'] as String,
      );

  Map<String, dynamic> toJson() => {
        'col': col,
        'text': text,
      };
}

class DataTableRow {
  const DataTableRow({
    required this.key,
    this.label,
    required this.cells,
  });

  final String key;
  final String? label;
  final List<DataTableCell> cells;

  factory DataTableRow.fromJson(Map<String, dynamic> json) => DataTableRow(
        key: json['key'] as String,
        label: json['label'] == null ? null : json['label'] as String,
        cells: (json['cells'] as List<dynamic>).map((e) => DataTableCell.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'label': label,
        'cells': cells.map((e) => e.toJson()).toList(),
      };
}

/// 实验题的数据表。格子由 (表键, 行键, 列键) 唯一确定；text 为 null 的格子由学生填写。
class DataTable {
  const DataTable({
    required this.key,
    required this.title,
    required this.columns,
    required this.rows,
  });

  final String key;
  final String title;
  final List<DataTableColumn> columns;
  final List<DataTableRow> rows;

  factory DataTable.fromJson(Map<String, dynamic> json) => DataTable(
        key: json['key'] as String,
        title: json['title'] as String,
        columns: (json['columns'] as List<dynamic>).map((e) => DataTableColumn.fromJson(e as Map<String, dynamic>)).toList(),
        rows: (json['rows'] as List<dynamic>).map((e) => DataTableRow.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'title': title,
        'columns': columns.map((e) => e.toJson()).toList(),
        'rows': rows.map((e) => e.toJson()).toList(),
      };
}

/// 证明题的"已知"和"求证"。参考证明不在这里，只在提交之后随自查（`SelfCheck.reference_steps`）给出。
class ProofStatement {
  const ProofStatement({
    required this.givens,
    required this.claim,
  });

  final List<String> givens;
  final String claim;

  factory ProofStatement.fromJson(Map<String, dynamic> json) => ProofStatement(
        givens: (json['givens'] as List<dynamic>).map((e) => e as String).toList(),
        claim: json['claim'] as String,
      );

  Map<String, dynamic> toJson() => {
        'givens': givens,
        'claim': claim,
      };
}

class QuestionContent {
  const QuestionContent({
    required this.stem,
    required this.options,
    required this.blanks,
    required this.subquestions,
    required this.attachments,
    required this.dataTables,
    this.safety,
    this.proof,
  });

  final String stem;
  final List<QuestionOption> options;
  final List<QuestionBlank> blanks;
  final List<Subquestion> subquestions;
  final List<QuestionAttachment> attachments;
  final List<DataTable> dataTables;
  final ExperimentSafety? safety;
  final ProofStatement? proof;

  factory QuestionContent.fromJson(Map<String, dynamic> json) => QuestionContent(
        stem: json['stem'] as String,
        options: (json['options'] as List<dynamic>).map((e) => QuestionOption.fromJson(e as Map<String, dynamic>)).toList(),
        blanks: (json['blanks'] as List<dynamic>).map((e) => QuestionBlank.fromJson(e as Map<String, dynamic>)).toList(),
        subquestions: (json['subquestions'] as List<dynamic>).map((e) => Subquestion.fromJson(e as Map<String, dynamic>)).toList(),
        attachments: (json['attachments'] as List<dynamic>).map((e) => QuestionAttachment.fromJson(e as Map<String, dynamic>)).toList(),
        dataTables: (json['data_tables'] as List<dynamic>).map((e) => DataTable.fromJson(e as Map<String, dynamic>)).toList(),
        safety: json['safety'] == null ? null : ExperimentSafety.fromJson(json['safety'] as Map<String, dynamic>),
        proof: json['proof'] == null ? null : ProofStatement.fromJson(json['proof'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'stem': stem,
        'options': options.map((e) => e.toJson()).toList(),
        'blanks': blanks.map((e) => e.toJson()).toList(),
        'subquestions': subquestions.map((e) => e.toJson()).toList(),
        'attachments': attachments.map((e) => e.toJson()).toList(),
        'data_tables': dataTables.map((e) => e.toJson()).toList(),
        'safety': safety?.toJson(),
        'proof': proof?.toJson(),
      };
}

class QuestionAssists {
  const QuestionAssists({
    required this.hintLevels,
    required this.hasStandardSolution,
    required this.hasFastSolution,
    required this.visualAvailable,
  });

  final int hintLevels;
  final bool hasStandardSolution;
  final bool hasFastSolution;
  final bool visualAvailable;

  factory QuestionAssists.fromJson(Map<String, dynamic> json) => QuestionAssists(
        hintLevels: (json['hint_levels'] as num).toInt(),
        hasStandardSolution: json['has_standard_solution'] as bool,
        hasFastSolution: json['has_fast_solution'] as bool,
        visualAvailable: json['visual_available'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'hint_levels': hintLevels,
        'has_standard_solution': hasStandardSolution,
        'has_fast_solution': hasFastSolution,
        'visual_available': visualAvailable,
      };
}

class QuestionSummary {
  const QuestionSummary({
    required this.id,
    required this.subject,
    required this.type,
    required this.answerMode,
    required this.difficulty,
    required this.title,
    required this.source,
    required this.applicability,
    required this.knowledge,
    this.variantOf,
  });

  final String id;
  final Subject subject;
  final QuestionType type;
  final AnswerMode answerMode;
  final int difficulty;
  final String title;
  final QuestionSource source;
  final Applicability applicability;
  final List<KnowledgeRef> knowledge;
  final String? variantOf;

  factory QuestionSummary.fromJson(Map<String, dynamic> json) => QuestionSummary(
        id: json['id'] as String,
        subject: Subject.fromJson(json['subject'] as String),
        type: QuestionType.fromJson(json['type'] as String),
        answerMode: AnswerMode.fromJson(json['answer_mode'] as String),
        difficulty: (json['difficulty'] as num).toInt(),
        title: json['title'] as String,
        source: QuestionSource.fromJson(json['source'] as Map<String, dynamic>),
        applicability: Applicability.fromJson(json['applicability'] as Map<String, dynamic>),
        knowledge: (json['knowledge'] as List<dynamic>).map((e) => KnowledgeRef.fromJson(e as Map<String, dynamic>)).toList(),
        variantOf: json['variant_of'] == null ? null : json['variant_of'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'subject': subject.toJson(),
        'type': type.toJson(),
        'answer_mode': answerMode.toJson(),
        'difficulty': difficulty,
        'title': title,
        'source': source.toJson(),
        'applicability': applicability.toJson(),
        'knowledge': knowledge.map((e) => e.toJson()).toList(),
        'variant_of': variantOf,
      };
}

class Question {
  const Question({
    this.provenance,
    required this.id,
    required this.subject,
    required this.type,
    required this.answerMode,
    required this.difficulty,
    required this.title,
    required this.source,
    required this.applicability,
    required this.knowledge,
    this.variantOf,
    required this.version,
    this.grade,
    required this.content,
    required this.assists,
    this.judgingNote,
  });

  final QuestionProvenance? provenance;
  final String id;
  final Subject subject;
  final QuestionType type;
  final AnswerMode answerMode;
  final int difficulty;
  final String title;
  final QuestionSource source;
  final Applicability applicability;
  final List<KnowledgeRef> knowledge;
  final String? variantOf;
  final int version;
  final Grade? grade;
  final QuestionContent content;
  final QuestionAssists assists;
  final String? judgingNote;

  factory Question.fromJson(Map<String, dynamic> json) => Question(
        provenance: json['provenance'] == null ? null : QuestionProvenance.fromJson(json['provenance'] as Map<String, dynamic>),
        id: json['id'] as String,
        subject: Subject.fromJson(json['subject'] as String),
        type: QuestionType.fromJson(json['type'] as String),
        answerMode: AnswerMode.fromJson(json['answer_mode'] as String),
        difficulty: (json['difficulty'] as num).toInt(),
        title: json['title'] as String,
        source: QuestionSource.fromJson(json['source'] as Map<String, dynamic>),
        applicability: Applicability.fromJson(json['applicability'] as Map<String, dynamic>),
        knowledge: (json['knowledge'] as List<dynamic>).map((e) => KnowledgeRef.fromJson(e as Map<String, dynamic>)).toList(),
        variantOf: json['variant_of'] == null ? null : json['variant_of'] as String,
        version: (json['version'] as num).toInt(),
        grade: json['grade'] == null ? null : Grade.fromJson(json['grade'] as String),
        content: QuestionContent.fromJson(json['content'] as Map<String, dynamic>),
        assists: QuestionAssists.fromJson(json['assists'] as Map<String, dynamic>),
        judgingNote: json['judging_note'] == null ? null : json['judging_note'] as String,
      );

  Map<String, dynamic> toJson() => {
        if (provenance != null) 'provenance': provenance?.toJson(),
        'id': id,
        'subject': subject.toJson(),
        'type': type.toJson(),
        'answer_mode': answerMode.toJson(),
        'difficulty': difficulty,
        'title': title,
        'source': source.toJson(),
        'applicability': applicability.toJson(),
        'knowledge': knowledge.map((e) => e.toJson()).toList(),
        'variant_of': variantOf,
        'version': version,
        'grade': grade?.toJson(),
        'content': content.toJson(),
        'assists': assists.toJson(),
        'judging_note': judgingNote,
      };
}

class QuestionPage {
  const QuestionPage({
    required this.items,
    this.nextCursor,
  });

  final List<QuestionSummary> items;
  final String? nextCursor;

  factory QuestionPage.fromJson(Map<String, dynamic> json) => QuestionPage(
        items: (json['items'] as List<dynamic>).map((e) => QuestionSummary.fromJson(e as Map<String, dynamic>)).toList(),
        nextCursor: json['next_cursor'] == null ? null : json['next_cursor'] as String,
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
        'next_cursor': nextCursor,
      };
}

class SessionCreate {
  const SessionCreate({
    required this.questionId,
    this.expectedQuestionVersion,
    required this.origin,
    this.reviewItemId,
    this.parentSessionId,
  });

  final String questionId;
  final int? expectedQuestionVersion;
  final SessionOrigin origin;
  final String? reviewItemId;
  final String? parentSessionId;

  factory SessionCreate.fromJson(Map<String, dynamic> json) => SessionCreate(
        questionId: json['question_id'] as String,
        expectedQuestionVersion: json['expected_question_version'] == null ? null : (json['expected_question_version'] as num).toInt(),
        origin: SessionOrigin.fromJson(json['origin'] as String),
        reviewItemId: json['review_item_id'] == null ? null : json['review_item_id'] as String,
        parentSessionId: json['parent_session_id'] == null ? null : json['parent_session_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'question_id': questionId,
        if (expectedQuestionVersion != null) 'expected_question_version': expectedQuestionVersion,
        'origin': origin.toJson(),
        if (reviewItemId != null) 'review_item_id': reviewItemId,
        if (parentSessionId != null) 'parent_session_id': parentSessionId,
      };
}

class StudySession {
  const StudySession({
    required this.id,
    required this.questionId,
    required this.questionVersion,
    required this.origin,
    required this.state,
    this.reviewItemId,
    this.parentSessionId,
    this.regionCodeSnapshot,
    this.examYearSnapshot,
    this.curriculumVersionSnapshot,
    required this.assisted,
    required this.usedSolution,
    required this.independentEnded,
    required this.hintLevelRevealed,
    required this.hintLevelsTotal,
    required this.confusedStreak,
    required this.needsHumanHelp,
    this.activeAttemptId,
    this.firstSubmittedAttemptId,
    required this.submittedAttempts,
    required this.lastEventSeq,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String questionId;
  final int questionVersion;
  final SessionOrigin origin;
  final SessionState state;
  final String? reviewItemId;
  final String? parentSessionId;
  final String? regionCodeSnapshot;
  final int? examYearSnapshot;
  final String? curriculumVersionSnapshot;
  final bool assisted;
  final bool usedSolution;
  final bool independentEnded;
  final int hintLevelRevealed;
  final int hintLevelsTotal;
  final int confusedStreak;
  final bool needsHumanHelp;
  final String? activeAttemptId;
  final String? firstSubmittedAttemptId;
  final int submittedAttempts;
  final int lastEventSeq;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory StudySession.fromJson(Map<String, dynamic> json) => StudySession(
        id: json['id'] as String,
        questionId: json['question_id'] as String,
        questionVersion: (json['question_version'] as num).toInt(),
        origin: SessionOrigin.fromJson(json['origin'] as String),
        state: SessionState.fromJson(json['state'] as String),
        reviewItemId: json['review_item_id'] == null ? null : json['review_item_id'] as String,
        parentSessionId: json['parent_session_id'] == null ? null : json['parent_session_id'] as String,
        regionCodeSnapshot: json['region_code_snapshot'] == null ? null : json['region_code_snapshot'] as String,
        examYearSnapshot: json['exam_year_snapshot'] == null ? null : (json['exam_year_snapshot'] as num).toInt(),
        curriculumVersionSnapshot: json['curriculum_version_snapshot'] == null ? null : json['curriculum_version_snapshot'] as String,
        assisted: json['assisted'] as bool,
        usedSolution: json['used_solution'] as bool,
        independentEnded: json['independent_ended'] as bool,
        hintLevelRevealed: (json['hint_level_revealed'] as num).toInt(),
        hintLevelsTotal: (json['hint_levels_total'] as num).toInt(),
        confusedStreak: (json['confused_streak'] as num).toInt(),
        needsHumanHelp: json['needs_human_help'] as bool,
        activeAttemptId: json['active_attempt_id'] == null ? null : json['active_attempt_id'] as String,
        firstSubmittedAttemptId: json['first_submitted_attempt_id'] == null ? null : json['first_submitted_attempt_id'] as String,
        submittedAttempts: (json['submitted_attempts'] as num).toInt(),
        lastEventSeq: (json['last_event_seq'] as num).toInt(),
        createdAt: DateTime.parse(json['created_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'question_id': questionId,
        'question_version': questionVersion,
        'origin': origin.toJson(),
        'state': state.toJson(),
        'review_item_id': reviewItemId,
        'parent_session_id': parentSessionId,
        'region_code_snapshot': regionCodeSnapshot,
        'exam_year_snapshot': examYearSnapshot,
        'curriculum_version_snapshot': curriculumVersionSnapshot,
        'assisted': assisted,
        'used_solution': usedSolution,
        'independent_ended': independentEnded,
        'hint_level_revealed': hintLevelRevealed,
        'hint_levels_total': hintLevelsTotal,
        'confused_streak': confusedStreak,
        'needs_human_help': needsHumanHelp,
        'active_attempt_id': activeAttemptId,
        if (firstSubmittedAttemptId != null) 'first_submitted_attempt_id': firstSubmittedAttemptId,
        'submitted_attempts': submittedAttempts,
        'last_event_seq': lastEventSeq,
        'created_at': createdAt.toUtc().toIso8601String(),
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class AttemptCreate {
  const AttemptCreate({
    required this.sessionId,
  });

  final String sessionId;

  factory AttemptCreate.fromJson(Map<String, dynamic> json) => AttemptCreate(
        sessionId: json['session_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'session_id': sessionId,
      };
}

class AnswerBlank {
  const AnswerBlank({
    required this.key,
    required this.value,
  });

  final String key;
  final String value;

  factory AnswerBlank.fromJson(Map<String, dynamic> json) => AnswerBlank(
        key: json['key'] as String,
        value: json['value'] as String,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'value': value,
      };
}

/// 实验题数据表里的一个格子：学生填写的数（作答），或提交之后给出的参考值（自查）。
class AnswerCell {
  const AnswerCell({
    required this.table,
    required this.row,
    required this.col,
    required this.value,
  });

  final String table;
  final String row;
  final String col;
  final String value;

  factory AnswerCell.fromJson(Map<String, dynamic> json) => AnswerCell(
        table: json['table'] as String,
        row: json['row'] as String,
        col: json['col'] as String,
        value: json['value'] as String,
      );

  Map<String, dynamic> toJson() => {
        'table': table,
        'row': row,
        'col': col,
        'value': value,
      };
}

/// 解答题、实验题某一小问的文字作答。
class AnswerPart {
  const AnswerPart({
    required this.key,
    required this.text,
  });

  final String key;
  final String text;

  factory AnswerPart.fromJson(Map<String, dynamic> json) => AnswerPart(
        key: json['key'] as String,
        text: json['text'] as String,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'text': text,
      };
}

/// 证明题作答里的一步。依据可以不写：写不写、写得对不对都不拦提交，也不判对错，只是自查清单里会问。
class AnswerStep {
  const AnswerStep({
    required this.text,
    required this.reason,
  });

  final String text;
  final String reason;

  factory AnswerStep.fromJson(Map<String, dynamic> json) => AnswerStep(
        text: json['text'] as String,
        reason: json['reason'] as String,
      );

  Map<String, dynamic> toJson() => {
        'text': text,
        'reason': reason,
      };
}

/// 按题目的 answer_mode 填写对应字段：选择题用 selected_options，填空题用 blanks，解答题用 parts， 实验题用 cells（数据表里留空的格子）和 parts（文字小问），证明题用 steps（一步一步的证明）。 解答题、实验题、证明题可以只写一部分，也可以只有笔迹（笔迹随草稿同步，不在这里）； 文字、格子、步骤和笔迹都没有时提交返回 422。
class AnswerPayload {
  const AnswerPayload({
    this.selectedOptions,
    this.blanks,
    this.parts,
    this.cells,
    this.steps,
    this.text,
  });

  final List<String>? selectedOptions;
  final List<AnswerBlank>? blanks;
  final List<AnswerPart>? parts;
  final List<AnswerCell>? cells;
  final List<AnswerStep>? steps;
  final String? text;

  factory AnswerPayload.fromJson(Map<String, dynamic> json) => AnswerPayload(
        selectedOptions: json['selected_options'] == null ? null : (json['selected_options'] as List<dynamic>).map((e) => e as String).toList(),
        blanks: json['blanks'] == null ? null : (json['blanks'] as List<dynamic>).map((e) => AnswerBlank.fromJson(e as Map<String, dynamic>)).toList(),
        parts: json['parts'] == null ? null : (json['parts'] as List<dynamic>).map((e) => AnswerPart.fromJson(e as Map<String, dynamic>)).toList(),
        cells: json['cells'] == null ? null : (json['cells'] as List<dynamic>).map((e) => AnswerCell.fromJson(e as Map<String, dynamic>)).toList(),
        steps: json['steps'] == null ? null : (json['steps'] as List<dynamic>).map((e) => AnswerStep.fromJson(e as Map<String, dynamic>)).toList(),
        text: json['text'] == null ? null : json['text'] as String,
      );

  Map<String, dynamic> toJson() => {
        if (selectedOptions != null) 'selected_options': selectedOptions,
        if (blanks != null) 'blanks': blanks?.map((e) => e.toJson()).toList(),
        if (parts != null) 'parts': parts?.map((e) => e.toJson()).toList(),
        if (cells != null) 'cells': cells?.map((e) => e.toJson()).toList(),
        if (steps != null) 'steps': steps?.map((e) => e.toJson()).toList(),
        if (text != null) 'text': text,
      };
}

class Stroke {
  const Stroke({
    required this.color,
    required this.width,
    required this.points,
  });

  final String color;
  final double width;
  final List<double> points;

  factory Stroke.fromJson(Map<String, dynamic> json) => Stroke(
        color: json['color'] as String,
        width: (json['width'] as num).toDouble(),
        points: (json['points'] as List<dynamic>).map((e) => (e as num).toDouble()).toList(),
      );

  Map<String, dynamic> toJson() => {
        'color': color,
        'width': width,
        'points': points,
      };
}

class StrokePage {
  const StrokePage({
    required this.width,
    required this.height,
    required this.strokes,
  });

  final double width;
  final double height;
  final List<Stroke> strokes;

  factory StrokePage.fromJson(Map<String, dynamic> json) => StrokePage(
        width: (json['width'] as num).toDouble(),
        height: (json['height'] as num).toDouble(),
        strokes: (json['strokes'] as List<dynamic>).map((e) => Stroke.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'width': width,
        'height': height,
        'strokes': strokes.map((e) => e.toJson()).toList(),
      };
}

class StrokeDoc {
  const StrokeDoc({
    required this.version,
    required this.pages,
  });

  final int version;
  final List<StrokePage> pages;

  factory StrokeDoc.fromJson(Map<String, dynamic> json) => StrokeDoc(
        version: (json['version'] as num).toInt(),
        pages: (json['pages'] as List<dynamic>).map((e) => StrokePage.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'version': version,
        'pages': pages.map((e) => e.toJson()).toList(),
      };
}

class Draft {
  const Draft({
    required this.attemptId,
    required this.revision,
    this.answer,
    this.strokes,
    required this.updatedAt,
  });

  final String attemptId;
  final int revision;
  final AnswerPayload? answer;
  final StrokeDoc? strokes;
  final DateTime updatedAt;

  factory Draft.fromJson(Map<String, dynamic> json) => Draft(
        attemptId: json['attempt_id'] as String,
        revision: (json['revision'] as num).toInt(),
        answer: json['answer'] == null ? null : AnswerPayload.fromJson(json['answer'] as Map<String, dynamic>),
        strokes: json['strokes'] == null ? null : StrokeDoc.fromJson(json['strokes'] as Map<String, dynamic>),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'attempt_id': attemptId,
        'revision': revision,
        'answer': answer?.toJson(),
        'strokes': strokes?.toJson(),
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class DraftSync {
  const DraftSync({
    required this.baseRevision,
    this.answer,
    this.strokes,
  });

  final int baseRevision;
  final AnswerPayload? answer;
  final StrokeDoc? strokes;

  factory DraftSync.fromJson(Map<String, dynamic> json) => DraftSync(
        baseRevision: (json['base_revision'] as num).toInt(),
        answer: json['answer'] == null ? null : AnswerPayload.fromJson(json['answer'] as Map<String, dynamic>),
        strokes: json['strokes'] == null ? null : StrokeDoc.fromJson(json['strokes'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'base_revision': baseRevision,
        if (answer != null) 'answer': answer?.toJson(),
        if (strokes != null) 'strokes': strokes?.toJson(),
      };
}

class SubmitRequest {
  const SubmitRequest({
    required this.answer,
    this.elapsedMs,
    this.expectedDraftRevision,
  });

  final AnswerPayload answer;
  final int? elapsedMs;
  final int? expectedDraftRevision;

  factory SubmitRequest.fromJson(Map<String, dynamic> json) => SubmitRequest(
        answer: AnswerPayload.fromJson(json['answer'] as Map<String, dynamic>),
        elapsedMs: json['elapsed_ms'] == null ? null : (json['elapsed_ms'] as num).toInt(),
        expectedDraftRevision: json['expected_draft_revision'] == null ? null : (json['expected_draft_revision'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'answer': answer.toJson(),
        if (elapsedMs != null) 'elapsed_ms': elapsedMs,
        if (expectedDraftRevision != null) 'expected_draft_revision': expectedDraftRevision,
      };
}

class FeedbackItem {
  const FeedbackItem({
    required this.target,
    required this.code,
    required this.message,
  });

  final String target;
  final FeedbackCode code;
  final String message;

  factory FeedbackItem.fromJson(Map<String, dynamic> json) => FeedbackItem(
        target: json['target'] as String,
        code: FeedbackCode.fromJson(json['code'] as String),
        message: json['message'] as String,
      );

  Map<String, dynamic> toJson() => {
        'target': target,
        'code': code.toJson(),
        'message': message,
      };
}

class Evaluation {
  const Evaluation({
    required this.state,
    required this.outcome,
    this.isCorrect,
    required this.independent,
    required this.assisted,
    required this.usedSolution,
    required this.reviewRequired,
    required this.feedback,
    required this.message,
    required this.disclaimer,
  });

  final EvaluationState state;
  final EvaluationOutcome outcome;
  final bool? isCorrect;
  final bool independent;
  final bool assisted;
  final bool usedSolution;
  final bool reviewRequired;
  final List<FeedbackItem> feedback;
  final String message;
  final String disclaimer;

  factory Evaluation.fromJson(Map<String, dynamic> json) => Evaluation(
        state: EvaluationState.fromJson(json['state'] as String),
        outcome: EvaluationOutcome.fromJson(json['outcome'] as String),
        isCorrect: json['is_correct'] == null ? null : json['is_correct'] as bool,
        independent: json['independent'] as bool,
        assisted: json['assisted'] as bool,
        usedSolution: json['used_solution'] as bool,
        reviewRequired: json['review_required'] as bool,
        feedback: (json['feedback'] as List<dynamic>).map((e) => FeedbackItem.fromJson(e as Map<String, dynamic>)).toList(),
        message: json['message'] as String,
        disclaimer: json['disclaimer'] as String,
      );

  Map<String, dynamic> toJson() => {
        'state': state.toJson(),
        'outcome': outcome.toJson(),
        'is_correct': isCorrect,
        'independent': independent,
        'assisted': assisted,
        'used_solution': usedSolution,
        'review_required': reviewRequired,
        'feedback': feedback.map((e) => e.toJson()).toList(),
        'message': message,
        'disclaimer': disclaimer,
      };
}

class Attempt {
  const Attempt({
    required this.id,
    required this.sessionId,
    required this.attemptNo,
    this.submissionNo,
    this.copiedFromAttemptId,
    this.copiedFromRevision,
    required this.status,
    this.answer,
    required this.draftRevision,
    required this.assisted,
    required this.usedSolution,
    this.independent,
    this.evaluation,
    this.submittedAt,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String sessionId;
  final int attemptNo;
  final int? submissionNo;
  final String? copiedFromAttemptId;
  final int? copiedFromRevision;
  final AttemptStatus status;
  final AnswerPayload? answer;
  final int draftRevision;
  final bool assisted;
  final bool usedSolution;
  final bool? independent;
  final Evaluation? evaluation;
  final DateTime? submittedAt;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory Attempt.fromJson(Map<String, dynamic> json) => Attempt(
        id: json['id'] as String,
        sessionId: json['session_id'] as String,
        attemptNo: (json['attempt_no'] as num).toInt(),
        submissionNo: json['submission_no'] == null ? null : (json['submission_no'] as num).toInt(),
        copiedFromAttemptId: json['copied_from_attempt_id'] == null ? null : json['copied_from_attempt_id'] as String,
        copiedFromRevision: json['copied_from_revision'] == null ? null : (json['copied_from_revision'] as num).toInt(),
        status: AttemptStatus.fromJson(json['status'] as String),
        answer: json['answer'] == null ? null : AnswerPayload.fromJson(json['answer'] as Map<String, dynamic>),
        draftRevision: (json['draft_revision'] as num).toInt(),
        assisted: json['assisted'] as bool,
        usedSolution: json['used_solution'] as bool,
        independent: json['independent'] == null ? null : json['independent'] as bool,
        evaluation: json['evaluation'] == null ? null : Evaluation.fromJson(json['evaluation'] as Map<String, dynamic>),
        submittedAt: json['submitted_at'] == null ? null : DateTime.parse(json['submitted_at'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'session_id': sessionId,
        'attempt_no': attemptNo,
        if (submissionNo != null) 'submission_no': submissionNo,
        if (copiedFromAttemptId != null) 'copied_from_attempt_id': copiedFromAttemptId,
        if (copiedFromRevision != null) 'copied_from_revision': copiedFromRevision,
        'status': status.toJson(),
        'answer': answer?.toJson(),
        'draft_revision': draftRevision,
        'assisted': assisted,
        'used_solution': usedSolution,
        'independent': independent,
        'evaluation': evaluation?.toJson(),
        'submitted_at': submittedAt?.toUtc().toIso8601String(),
        'created_at': createdAt.toUtc().toIso8601String(),
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class DraftCopyCreate {
  const DraftCopyCreate({
    required this.sourceRevision,
    this.answer,
    this.strokes,
  });

  final int sourceRevision;
  final AnswerPayload? answer;
  final StrokeDoc? strokes;

  factory DraftCopyCreate.fromJson(Map<String, dynamic> json) => DraftCopyCreate(
        sourceRevision: (json['source_revision'] as num).toInt(),
        answer: json['answer'] == null ? null : AnswerPayload.fromJson(json['answer'] as Map<String, dynamic>),
        strokes: json['strokes'] == null ? null : StrokeDoc.fromJson(json['strokes'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'source_revision': sourceRevision,
        'answer': answer?.toJson(),
        'strokes': strokes?.toJson(),
      };
}

class DraftCopy {
  const DraftCopy({
    required this.session,
    required this.attempt,
    required this.draft,
  });

  final StudySession session;
  final Attempt attempt;
  final Draft draft;

  factory DraftCopy.fromJson(Map<String, dynamic> json) => DraftCopy(
        session: StudySession.fromJson(json['session'] as Map<String, dynamic>),
        attempt: Attempt.fromJson(json['attempt'] as Map<String, dynamic>),
        draft: Draft.fromJson(json['draft'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'session': session.toJson(),
        'attempt': attempt.toJson(),
        'draft': draft.toJson(),
      };
}

class QuestionDraftRef {
  const QuestionDraftRef({
    required this.sessionId,
    required this.attemptId,
    required this.questionVersion,
    required this.attemptNo,
    required this.draftRevision,
    this.copiedFromAttemptId,
    this.copiedFromRevision,
    required this.origin,
    this.reviewItemId,
    required this.sessionState,
    required this.updatedAt,
  });

  final String sessionId;
  final String attemptId;
  final int questionVersion;
  final int attemptNo;
  final int draftRevision;
  final String? copiedFromAttemptId;
  final int? copiedFromRevision;
  final SessionOrigin origin;
  final String? reviewItemId;
  final SessionState sessionState;
  final DateTime updatedAt;

  factory QuestionDraftRef.fromJson(Map<String, dynamic> json) => QuestionDraftRef(
        sessionId: json['session_id'] as String,
        attemptId: json['attempt_id'] as String,
        questionVersion: (json['question_version'] as num).toInt(),
        attemptNo: (json['attempt_no'] as num).toInt(),
        draftRevision: (json['draft_revision'] as num).toInt(),
        copiedFromAttemptId: json['copied_from_attempt_id'] == null ? null : json['copied_from_attempt_id'] as String,
        copiedFromRevision: json['copied_from_revision'] == null ? null : (json['copied_from_revision'] as num).toInt(),
        origin: SessionOrigin.fromJson(json['origin'] as String),
        reviewItemId: json['review_item_id'] == null ? null : json['review_item_id'] as String,
        sessionState: SessionState.fromJson(json['session_state'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'session_id': sessionId,
        'attempt_id': attemptId,
        'question_version': questionVersion,
        'attempt_no': attemptNo,
        'draft_revision': draftRevision,
        'copied_from_attempt_id': copiedFromAttemptId,
        'copied_from_revision': copiedFromRevision,
        'origin': origin.toJson(),
        'review_item_id': reviewItemId,
        'session_state': sessionState.toJson(),
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class QuestionDraftPage {
  const QuestionDraftPage({
    required this.items,
    this.nextCursor,
  });

  final List<QuestionDraftRef> items;
  final String? nextCursor;

  factory QuestionDraftPage.fromJson(Map<String, dynamic> json) => QuestionDraftPage(
        items: (json['items'] as List<dynamic>).map((e) => QuestionDraftRef.fromJson(e as Map<String, dynamic>)).toList(),
        nextCursor: json['next_cursor'] == null ? null : json['next_cursor'] as String,
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
        'next_cursor': nextCursor,
      };
}

class SubmitResult {
  const SubmitResult({
    required this.attempt,
    required this.evaluation,
    required this.session,
    required this.events,
    this.reviewItem,
  });

  final Attempt attempt;
  final Evaluation evaluation;
  final StudySession session;
  final List<TutorEvent> events;
  final ReviewItem? reviewItem;

  factory SubmitResult.fromJson(Map<String, dynamic> json) => SubmitResult(
        attempt: Attempt.fromJson(json['attempt'] as Map<String, dynamic>),
        evaluation: Evaluation.fromJson(json['evaluation'] as Map<String, dynamic>),
        session: StudySession.fromJson(json['session'] as Map<String, dynamic>),
        events: (json['events'] as List<dynamic>).map((e) => TutorEvent.fromJson(e as Map<String, dynamic>)).toList(),
        reviewItem: json['review_item'] == null ? null : ReviewItem.fromJson(json['review_item'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'attempt': attempt.toJson(),
        'evaluation': evaluation.toJson(),
        'session': session.toJson(),
        'events': events.map((e) => e.toJson()).toList(),
        'review_item': reviewItem?.toJson(),
      };
}

/// 学生对照一个要点的自评：done 做到了，partial 做到一部分，missed 没做到。
enum SelfCheckLevel {
  done('done'),
  partial('partial'),
  missed('missed'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const SelfCheckLevel(this.value);
  final String value;

  static SelfCheckLevel fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => SelfCheckLevel.$unknown);

  String toJson() => value;
}

/// 参考证明里一步的角色，对应 docs/06 的"拆解前提、构造、关键变形、结论"。 premise 前提（用了哪些已知条件）；construction 构造（引入辅助量、辅助线，或把式子改写成便于证明的形式）； reasoning 推理（一步一步推下去的关键步骤）；conclusion 结论（回到求证）。
enum ProofStage {
  premise('premise'),
  construction('construction'),
  reasoning('reasoning'),
  conclusion('conclusion'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const ProofStage(this.value);
  final String value;

  static ProofStage fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => ProofStage.$unknown);

  String toJson() => value;
}

/// 对照检查的一个要点。不带分值：这不是评分，只是一张自查清单。
class SelfCheckPoint {
  const SelfCheckPoint({
    required this.key,
    this.part$,
    required this.text,
  });

  final String key;
  final String? part$;
  final String text;

  factory SelfCheckPoint.fromJson(Map<String, dynamic> json) => SelfCheckPoint(
        key: json['key'] as String,
        part$: json['part'] == null ? null : json['part'] as String,
        text: json['text'] as String,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'part': part$,
        'text': text,
      };
}

/// 参考证明里的一步。只在提交之后随自查给出，只是对照用的参考：证明的写法不止一种，它不参与任何判定。
class ProofReferenceStep {
  const ProofReferenceStep({
    required this.stage,
    required this.text,
    required this.reason,
  });

  final ProofStage stage;
  final String text;
  final String reason;

  factory ProofReferenceStep.fromJson(Map<String, dynamic> json) => ProofReferenceStep(
        stage: ProofStage.fromJson(json['stage'] as String),
        text: json['text'] as String,
        reason: json['reason'] as String,
      );

  Map<String, dynamic> toJson() => {
        'stage': stage.toJson(),
        'text': text,
        'reason': reason,
      };
}

class SelfCheckMark {
  const SelfCheckMark({
    required this.pointKey,
    required this.level,
  });

  final String pointKey;
  final SelfCheckLevel level;

  factory SelfCheckMark.fromJson(Map<String, dynamic> json) => SelfCheckMark(
        pointKey: json['point_key'] as String,
        level: SelfCheckLevel.fromJson(json['level'] as String),
      );

  Map<String, dynamic> toJson() => {
        'point_key': pointKey,
        'level': level.toJson(),
      };
}

class SelfCheckSave {
  const SelfCheckSave({
    required this.marks,
  });

  final List<SelfCheckMark> marks;

  factory SelfCheckSave.fromJson(Map<String, dynamic> json) => SelfCheckSave(
        marks: (json['marks'] as List<dynamic>).map((e) => SelfCheckMark.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'marks': marks.map((e) => e.toJson()).toList(),
      };
}

/// 各档要点的个数。只是计数，不折算成分数。
class SelfCheckSummary {
  const SelfCheckSummary({
    required this.done,
    required this.partial,
    required this.missed,
    required this.total,
  });

  final int done;
  final int partial;
  final int missed;
  final int total;

  factory SelfCheckSummary.fromJson(Map<String, dynamic> json) => SelfCheckSummary(
        done: (json['done'] as num).toInt(),
        partial: (json['partial'] as num).toInt(),
        missed: (json['missed'] as num).toInt(),
        total: (json['total'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'done': done,
        'partial': partial,
        'missed': missed,
        'total': total,
      };
}

class SelfCheck {
  const SelfCheck({
    required this.attemptId,
    required this.points,
    required this.referenceCells,
    required this.referenceSteps,
    required this.marks,
    required this.summary,
    this.savedAt,
    required this.disclaimer,
  });

  final String attemptId;
  final List<SelfCheckPoint> points;
  final List<AnswerCell> referenceCells;
  final List<ProofReferenceStep> referenceSteps;
  final List<SelfCheckMark> marks;
  final SelfCheckSummary summary;
  final DateTime? savedAt;
  final String disclaimer;

  factory SelfCheck.fromJson(Map<String, dynamic> json) => SelfCheck(
        attemptId: json['attempt_id'] as String,
        points: (json['points'] as List<dynamic>).map((e) => SelfCheckPoint.fromJson(e as Map<String, dynamic>)).toList(),
        referenceCells: (json['reference_cells'] as List<dynamic>).map((e) => AnswerCell.fromJson(e as Map<String, dynamic>)).toList(),
        referenceSteps: (json['reference_steps'] as List<dynamic>).map((e) => ProofReferenceStep.fromJson(e as Map<String, dynamic>)).toList(),
        marks: (json['marks'] as List<dynamic>).map((e) => SelfCheckMark.fromJson(e as Map<String, dynamic>)).toList(),
        summary: SelfCheckSummary.fromJson(json['summary'] as Map<String, dynamic>),
        savedAt: json['saved_at'] == null ? null : DateTime.parse(json['saved_at'] as String),
        disclaimer: json['disclaimer'] as String,
      );

  Map<String, dynamic> toJson() => {
        'attempt_id': attemptId,
        'points': points.map((e) => e.toJson()).toList(),
        'reference_cells': referenceCells.map((e) => e.toJson()).toList(),
        'reference_steps': referenceSteps.map((e) => e.toJson()).toList(),
        'marks': marks.map((e) => e.toJson()).toList(),
        'summary': summary.toJson(),
        'saved_at': savedAt?.toUtc().toIso8601String(),
        'disclaimer': disclaimer,
      };
}

class TutorAction {
  const TutorAction({
    required this.action,
    this.confirmEndIndependent,
  });

  final TutorActionType action;
  final bool? confirmEndIndependent;

  factory TutorAction.fromJson(Map<String, dynamic> json) => TutorAction(
        action: TutorActionType.fromJson(json['action'] as String),
        confirmEndIndependent: json['confirm_end_independent'] == null ? null : json['confirm_end_independent'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'action': action.toJson(),
        if (confirmEndIndependent != null) 'confirm_end_independent': confirmEndIndependent,
      };
}

class TutorStep {
  const TutorStep({
    required this.session,
    required this.events,
  });

  final StudySession session;
  final List<TutorEvent> events;

  factory TutorStep.fromJson(Map<String, dynamic> json) => TutorStep(
        session: StudySession.fromJson(json['session'] as Map<String, dynamic>),
        events: (json['events'] as List<dynamic>).map((e) => TutorEvent.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'session': session.toJson(),
        'events': events.map((e) => e.toJson()).toList(),
      };
}

/// 固定题版本白名单文本块的范围；Unicode codepoint左闭右开。摘要为完整原文UTF-8 SHA-256，不做归一化。服务端必须另验start < end及实际长度、权限和审核范围。
class ContentSpanRef {
  const ContentSpanRef({
    required this.blockId,
    required this.blockSha256,
    required this.start,
    required this.end,
  });

  final String blockId;
  final String blockSha256;
  final int start;
  final int end;

  factory ContentSpanRef.fromJson(Map<String, dynamic> json) => ContentSpanRef(
        blockId: json['block_id'] as String,
        blockSha256: json['block_sha256'] as String,
        start: json['start'] as int,
        end: json['end'] as int,
      );

  Map<String, dynamic> toJson() => {
        'block_id': blockId,
        'block_sha256': blockSha256,
        'start': start,
        'end': end,
      };
}

/// 服务端在事件meta固定question_id/question_version下授权解析的快照。索引均为版本内原序1-based ordinal；不包含任意URL或原始文件定位。
class ResolvedContentSpan {
  const ResolvedContentSpan({
    required this.blockId,
    required this.blockSha256,
    required this.start,
    required this.end,
    required this.blockText,
    required this.label,
  });

  final String blockId;
  final String blockSha256;
  final int start;
  final int end;
  final String blockText;
  final String label;

  factory ResolvedContentSpan.fromJson(Map<String, dynamic> json) => ResolvedContentSpan(
        blockId: json['block_id'] as String,
        blockSha256: json['block_sha256'] as String,
        start: json['start'] as int,
        end: json['end'] as int,
        blockText: json['block_text'] as String,
        label: json['label'] as String,
      );

  Map<String, dynamic> toJson() => {
        'block_id': blockId,
        'block_sha256': blockSha256,
        'start': start,
        'end': end,
        'block_text': blockText,
        'label': label,
      };
}

/// 随题版本独立审校的教学引用注记。independent_safe仅为声明，不能绕过内容可见性、整块防泄题和完整解析门控；编辑使摘要失效时必须清除或重审。
class TeachingReferenceLink {
  const TeachingReferenceLink({
    required this.targetBlockId,
    required this.sourceSpan,
    required this.independentSafe,
  });

  final String targetBlockId;
  final ContentSpanRef sourceSpan;
  final bool independentSafe;

  factory TeachingReferenceLink.fromJson(Map<String, dynamic> json) => TeachingReferenceLink(
        targetBlockId: json['target_block_id'] as String,
        sourceSpan: ContentSpanRef.fromJson(json['source_span'] as Map<String, dynamic>),
        independentSafe: json['independent_safe'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'target_block_id': targetBlockId,
        'source_span': sourceSpan.toJson(),
        'independent_safe': independentSafe,
      };
}

/// 教学事件信封。payload 的结构按 type 由 contracts/tutor_event.schema.json 约束。
class TutorEvent {
  const TutorEvent({
    required this.id,
    required this.sessionId,
    required this.seqNo,
    required this.type,
    required this.createdAt,
    required this.stateAfter,
    required this.payload,
    required this.meta,
    this.references,
  });

  final String id;
  final String sessionId;
  final int seqNo;
  final TutorEventType type;
  final DateTime createdAt;
  final SessionState stateAfter;
  final Map<String, dynamic> payload;
  final TutorEventMeta meta;
  final List<ResolvedContentSpan>? references;

  factory TutorEvent.fromJson(Map<String, dynamic> json) => TutorEvent(
        id: json['id'] as String,
        sessionId: json['session_id'] as String,
        seqNo: (json['seq_no'] as num).toInt(),
        type: TutorEventType.fromJson(json['type'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
        stateAfter: SessionState.fromJson(json['state_after'] as String),
        payload: Map<String, dynamic>.from(json['payload'] as Map),
        meta: TutorEventMeta.fromJson(json['meta'] as Map<String, dynamic>),
        references: json.containsKey('references') ? _decodeReferences(json) : null,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'session_id': sessionId,
        'seq_no': seqNo,
        'type': type.toJson(),
        'created_at': createdAt.toUtc().toIso8601String(),
        'state_after': stateAfter.toJson(),
        'payload': payload,
        'meta': meta.toJson(),
        if (references != null) 'references': references?.map((e) => e.toJson()).toList(),
      };

  // 损坏的引用局部降级，保留事件正文；无效占位由客户端显示为引用不可用。
  static List<ResolvedContentSpan> _decodeReferences(Map<String, dynamic> json) {
    const unavailable = ResolvedContentSpan(blockId: '', blockSha256: '',
      start: -1, end: 0, blockText: '', label: '');
    try {
      final raw = json['references'];
      final version = (json['meta'] as Map)['question_version'];
      if (version is! int || version < 1 || json['seq_no'] is! int ||
          raw is! List || raw.length > 8) return const [unavailable];
      const keys = {'block_id', 'block_sha256', 'start', 'end', 'block_text', 'label'};
      final result = <ResolvedContentSpan>[];
      for (final item in raw) {
        if (item is! Map<String, dynamic> || item.length != keys.length ||
            !keys.every(item.containsKey)) return const [unavailable];
        result.add(ResolvedContentSpan.fromJson(item));
      }
      return result;
    } catch (_) {
      return const [unavailable];
    }
  }
}

class TutorEventMeta {
  const TutorEventMeta({
    required this.schemaVersion,
    required this.source,
    required this.degraded,
    this.provider,
    this.modelId,
    this.promptVersion,
    required this.questionId,
    required this.questionVersion,
    this.traceId,
    required this.requestId,
  });

  final String schemaVersion;
  final TutorEventSource source;
  final bool degraded;
  final String? provider;
  final String? modelId;
  final String? promptVersion;
  final String questionId;
  final int questionVersion;
  final String? traceId;
  final String requestId;

  factory TutorEventMeta.fromJson(Map<String, dynamic> json) => TutorEventMeta(
        schemaVersion: json['schema_version'] as String,
        source: TutorEventSource.fromJson(json['source'] as String),
        degraded: json['degraded'] as bool,
        provider: json['provider'] == null ? null : json['provider'] as String,
        modelId: json['model_id'] == null ? null : json['model_id'] as String,
        promptVersion: json['prompt_version'] == null ? null : json['prompt_version'] as String,
        questionId: json['question_id'] as String,
        questionVersion: (json['question_version'] as num).toInt(),
        traceId: json['trace_id'] == null ? null : json['trace_id'] as String,
        requestId: json['request_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'schema_version': schemaVersion,
        'source': source.toJson(),
        'degraded': degraded,
        'provider': provider,
        'model_id': modelId,
        'prompt_version': promptVersion,
        'question_id': questionId,
        'question_version': questionVersion,
        'trace_id': traceId,
        'request_id': requestId,
      };
}

class TutorEventPage {
  const TutorEventPage({
    required this.items,
    required this.lastSeq,
  });

  final List<TutorEvent> items;
  final int lastSeq;

  factory TutorEventPage.fromJson(Map<String, dynamic> json) => TutorEventPage(
        items: (json['items'] as List<dynamic>).map((e) => TutorEvent.fromJson(e as Map<String, dynamic>)).toList(),
        lastSeq: (json['last_seq'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
        'last_seq': lastSeq,
      };
}

class ReviewItem {
  const ReviewItem({
    required this.id,
    required this.questionId,
    required this.questionTitle,
    required this.subject,
    required this.status,
    required this.stage,
    required this.totalStages,
    required this.dueAt,
    required this.isDue,
    this.lastResult,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String questionId;
  final String questionTitle;
  final Subject subject;
  final ReviewStatus status;
  final int stage;
  final int totalStages;
  final DateTime dueAt;
  final bool isDue;
  final ReviewResult? lastResult;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory ReviewItem.fromJson(Map<String, dynamic> json) => ReviewItem(
        id: json['id'] as String,
        questionId: json['question_id'] as String,
        questionTitle: json['question_title'] as String,
        subject: Subject.fromJson(json['subject'] as String),
        status: ReviewStatus.fromJson(json['status'] as String),
        stage: (json['stage'] as num).toInt(),
        totalStages: (json['total_stages'] as num).toInt(),
        dueAt: DateTime.parse(json['due_at'] as String),
        isDue: json['is_due'] as bool,
        lastResult: json['last_result'] == null ? null : ReviewResult.fromJson(json['last_result'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'question_id': questionId,
        'question_title': questionTitle,
        'subject': subject.toJson(),
        'status': status.toJson(),
        'stage': stage,
        'total_stages': totalStages,
        'due_at': dueAt.toUtc().toIso8601String(),
        'is_due': isDue,
        'last_result': lastResult?.toJson(),
        'created_at': createdAt.toUtc().toIso8601String(),
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class ExportSelfCheck {
  const ExportSelfCheck({
    required this.attemptId,
    required this.marks,
    required this.savedAt,
  });

  final String attemptId;
  final List<SelfCheckMark> marks;
  final DateTime savedAt;

  factory ExportSelfCheck.fromJson(Map<String, dynamic> json) => ExportSelfCheck(
        attemptId: json['attempt_id'] as String,
        marks: (json['marks'] as List<dynamic>).map((e) => SelfCheckMark.fromJson(e as Map<String, dynamic>)).toList(),
        savedAt: DateTime.parse(json['saved_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'attempt_id': attemptId,
        'marks': marks.map((e) => e.toJson()).toList(),
        'saved_at': savedAt.toUtc().toIso8601String(),
      };
}

class ExportReviewHistory {
  const ExportReviewHistory({
    required this.reviewId,
    required this.firstAttemptId,
    required this.questionId,
    required this.state,
    this.result,
    this.completedAt,
  });

  final String reviewId;
  final String firstAttemptId;
  final String questionId;
  final String state;
  final String? result;
  final DateTime? completedAt;

  factory ExportReviewHistory.fromJson(Map<String, dynamic> json) => ExportReviewHistory(
        reviewId: json['review_id'] as String,
        firstAttemptId: json['first_attempt_id'] as String,
        questionId: json['question_id'] as String,
        state: json['state'] as String,
        result: json['result'] == null ? null : json['result'] as String,
        completedAt: json['completed_at'] == null ? null : DateTime.parse(json['completed_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'review_id': reviewId,
        'first_attempt_id': firstAttemptId,
        'question_id': questionId,
        'state': state,
        'result': result,
        'completed_at': completedAt?.toUtc().toIso8601String(),
      };
}

class ExportLearningSession {
  const ExportLearningSession({
    required this.session,
    required this.attempts,
    required this.drafts,
    required this.selfChecks,
    required this.events,
  });

  final StudySession session;
  final List<Attempt> attempts;
  final List<Draft> drafts;
  final List<ExportSelfCheck> selfChecks;
  final List<TutorEvent> events;

  factory ExportLearningSession.fromJson(Map<String, dynamic> json) => ExportLearningSession(
        session: StudySession.fromJson(json['session'] as Map<String, dynamic>),
        attempts: (json['attempts'] as List<dynamic>).map((e) => Attempt.fromJson(e as Map<String, dynamic>)).toList(),
        drafts: (json['drafts'] as List<dynamic>).map((e) => Draft.fromJson(e as Map<String, dynamic>)).toList(),
        selfChecks: (json['self_checks'] as List<dynamic>).map((e) => ExportSelfCheck.fromJson(e as Map<String, dynamic>)).toList(),
        events: (json['events'] as List<dynamic>).map((e) => TutorEvent.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'session': session.toJson(),
        'attempts': attempts.map((e) => e.toJson()).toList(),
        'drafts': drafts.map((e) => e.toJson()).toList(),
        'self_checks': selfChecks.map((e) => e.toJson()).toList(),
        'events': events.map((e) => e.toJson()).toList(),
      };
}

class ExportParentAccessLink {
  const ExportParentAccessLink({
    required this.id,
    required this.authorizationRevision,
    required this.consentAt,
    this.revokedAt,
    required this.createdAt,
  });

  final String id;
  final int authorizationRevision;
  final DateTime consentAt;
  final DateTime? revokedAt;
  final DateTime createdAt;

  factory ExportParentAccessLink.fromJson(Map<String, dynamic> json) => ExportParentAccessLink(
        id: json['id'] as String,
        authorizationRevision: (json['authorization_revision'] as num).toInt(),
        consentAt: DateTime.parse(json['consent_at'] as String),
        revokedAt: json['revoked_at'] == null ? null : DateTime.parse(json['revoked_at'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'authorization_revision': authorizationRevision,
        'consent_at': consentAt.toUtc().toIso8601String(),
        'revoked_at': revokedAt?.toUtc().toIso8601String(),
        'created_at': createdAt.toUtc().toIso8601String(),
      };
}

class ExportParentAccessInvite {
  const ExportParentAccessInvite({
    required this.id,
    required this.expiresAt,
    this.redeemedAt,
    this.revokedAt,
    required this.createdAt,
  });

  final String id;
  final DateTime expiresAt;
  final DateTime? redeemedAt;
  final DateTime? revokedAt;
  final DateTime createdAt;

  factory ExportParentAccessInvite.fromJson(Map<String, dynamic> json) => ExportParentAccessInvite(
        id: json['id'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String),
        redeemedAt: json['redeemed_at'] == null ? null : DateTime.parse(json['redeemed_at'] as String),
        revokedAt: json['revoked_at'] == null ? null : DateTime.parse(json['revoked_at'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'expires_at': expiresAt.toUtc().toIso8601String(),
        'redeemed_at': redeemedAt?.toUtc().toIso8601String(),
        'revoked_at': revokedAt?.toUtc().toIso8601String(),
        'created_at': createdAt.toUtc().toIso8601String(),
      };
}

/// 本人现存的家长访问授权和邀请元数据；不含家长身份、邀请码或哈希。绑定重新授权覆盖旧时间，不能推定完整历史或法定监护关系；导出不恢复、不撤销授权。
class ExportParentAccessRecords {
  const ExportParentAccessRecords({
    required this.historyComplete,
    required this.links,
    required this.invites,
  });

  final bool historyComplete;
  final List<ExportParentAccessLink> links;
  final List<ExportParentAccessInvite> invites;

  factory ExportParentAccessRecords.fromJson(Map<String, dynamic> json) => ExportParentAccessRecords(
        historyComplete: json['history_complete'] as bool,
        links: (json['links'] as List<dynamic>).map((e) => ExportParentAccessLink.fromJson(e as Map<String, dynamic>)).toList(),
        invites: (json['invites'] as List<dynamic>).map((e) => ExportParentAccessInvite.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'history_complete': historyComplete,
        'links': links.map((e) => e.toJson()).toList(),
        'invites': invites.map((e) => e.toJson()).toList(),
      };
}

/// 本人现存拍题文字快照；状态保留保存值，expires_at是原有效期。media_id只是原图引用，不保证图片存在或可读，不包含原图字节、存储路径或内部payload字段。
class ExportStoredScan {
  const ExportStoredScan({
    required this.mediaId,
    required this.expiresAt,
    required this.scan,
  });

  final String mediaId;
  final DateTime expiresAt;
  final Scan scan;

  factory ExportStoredScan.fromJson(Map<String, dynamic> json) => ExportStoredScan(
        mediaId: json['media_id'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String),
        scan: Scan.fromJson(json['scan'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
        'expires_at': expiresAt.toUtc().toIso8601String(),
        'scan': scan.toJson(),
      };
}

/// 当前可访问学生用途媒体档案；内含状态清单，明确排除过期/删除、审核用途及已清理历史。false标记不能改为完整历史或全局快照承诺。
class StudentMediaExport {
  const StudentMediaExport({
    required this.formatVersion,
    required this.scope,
    required this.ownerId,
    required this.exportedAt,
    required this.historyComplete,
    required this.consistentSnapshot,
    required this.objectsCount,
    required this.filesCount,
    required this.sizeBytes,
    required this.sha256,
    required this.archiveBase64,
  });

  final int formatVersion;
  final String scope;
  final String ownerId;
  final DateTime exportedAt;
  final bool historyComplete;
  final bool consistentSnapshot;
  final int objectsCount;
  final int filesCount;
  final int sizeBytes;
  final String sha256;
  final String archiveBase64;

  factory StudentMediaExport.fromJson(Map<String, dynamic> json) => StudentMediaExport(
        formatVersion: (json['format_version'] as num).toInt(),
        scope: json['scope'] as String,
        ownerId: json['owner_id'] as String,
        exportedAt: DateTime.parse(json['exported_at'] as String),
        historyComplete: json['history_complete'] as bool,
        consistentSnapshot: json['consistent_snapshot'] as bool,
        objectsCount: (json['objects_count'] as num).toInt(),
        filesCount: (json['files_count'] as num).toInt(),
        sizeBytes: (json['size_bytes'] as num).toInt(),
        sha256: json['sha256'] as String,
        archiveBase64: json['archive_base64'] as String,
      );

  Map<String, dynamic> toJson() => {
        'format_version': formatVersion,
        'scope': scope,
        'owner_id': ownerId,
        'exported_at': exportedAt.toUtc().toIso8601String(),
        'history_complete': historyComplete,
        'consistent_snapshot': consistentSnapshot,
        'objects_count': objectsCount,
        'files_count': filesCount,
        'size_bytes': sizeBytes,
        'sha256': sha256,
        'archive_base64': archiveBase64,
      };
}

class StudentMediaArchiveObject {
  const StudentMediaArchiveObject({
    required this.mediaId,
    required this.purpose,
    this.mime,
    required this.sizeBytes,
    required this.sha256,
    required this.expiresAt,
    required this.state,
    this.fileName,
    required this.availability,
  });

  final String mediaId;
  final String purpose;
  final String? mime;
  final int sizeBytes;
  final String sha256;
  final DateTime expiresAt;
  final String state;
  final String? fileName;
  final String availability;

  factory StudentMediaArchiveObject.fromJson(Map<String, dynamic> json) => StudentMediaArchiveObject(
        mediaId: json['media_id'] as String,
        purpose: json['purpose'] as String,
        mime: json['mime'] == null ? null : json['mime'] as String,
        sizeBytes: (json['size_bytes'] as num).toInt(),
        sha256: json['sha256'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String),
        state: json['state'] as String,
        fileName: json['file_name'] == null ? null : json['file_name'] as String,
        availability: json['availability'] as String,
      );

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
        'purpose': purpose,
        'mime': mime,
        'size_bytes': sizeBytes,
        'sha256': sha256,
        'expires_at': expiresAt.toUtc().toIso8601String(),
        'state': state,
        'file_name': fileName,
        'availability': availability,
      };
}

/// ZIP内自包含范围清单，不是完整历史或跨对象快照；未上传/待确认只列状态。
class StudentMediaArchiveManifest {
  const StudentMediaArchiveManifest({
    required this.formatVersion,
    required this.scope,
    required this.ownerId,
    required this.exportedAt,
    required this.historyComplete,
    required this.consistentSnapshot,
    required this.objectsCount,
    required this.filesCount,
    required this.objects,
    required this.excluded,
  });

  final int formatVersion;
  final String scope;
  final String ownerId;
  final DateTime exportedAt;
  final bool historyComplete;
  final bool consistentSnapshot;
  final int objectsCount;
  final int filesCount;
  final List<StudentMediaArchiveObject> objects;
  final List<String> excluded;

  factory StudentMediaArchiveManifest.fromJson(Map<String, dynamic> json) => StudentMediaArchiveManifest(
        formatVersion: (json['format_version'] as num).toInt(),
        scope: json['scope'] as String,
        ownerId: json['owner_id'] as String,
        exportedAt: DateTime.parse(json['exported_at'] as String),
        historyComplete: json['history_complete'] as bool,
        consistentSnapshot: json['consistent_snapshot'] as bool,
        objectsCount: (json['objects_count'] as num).toInt(),
        filesCount: (json['files_count'] as num).toInt(),
        objects: (json['objects'] as List<dynamic>).map((e) => StudentMediaArchiveObject.fromJson(e as Map<String, dynamic>)).toList(),
        excluded: (json['excluded'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        'format_version': formatVersion,
        'scope': scope,
        'owner_id': ownerId,
        'exported_at': exportedAt.toUtc().toIso8601String(),
        'history_complete': historyComplete,
        'consistent_snapshot': consistentSnapshot,
        'objects_count': objectsCount,
        'files_count': filesCount,
        'objects': objects.map((e) => e.toJson()).toList(),
        'excluded': excluded,
      };
}

class ExportModelCall {
  const ExportModelCall({
    required this.createdAt,
    required this.taskType,
    required this.status,
    required this.providerCalls,
    this.inputTokens,
    this.outputTokens,
    this.imageUnits,
    this.estimatedCostMicros,
  });

  final DateTime createdAt;
  final String taskType;
  final String status;
  final int providerCalls;
  final int? inputTokens;
  final int? outputTokens;
  final int? imageUnits;
  final int? estimatedCostMicros;

  factory ExportModelCall.fromJson(Map<String, dynamic> json) => ExportModelCall(
        createdAt: DateTime.parse(json['created_at'] as String),
        taskType: json['task_type'] as String,
        status: json['status'] as String,
        providerCalls: (json['provider_calls'] as num).toInt(),
        inputTokens: json['input_tokens'] == null ? null : (json['input_tokens'] as num).toInt(),
        outputTokens: json['output_tokens'] == null ? null : (json['output_tokens'] as num).toInt(),
        imageUnits: json['image_units'] == null ? null : (json['image_units'] as num).toInt(),
        estimatedCostMicros: json['estimated_cost_micros'] == null ? null : (json['estimated_cost_micros'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'created_at': createdAt.toUtc().toIso8601String(),
        'task_type': taskType,
        'status': status,
        'provider_calls': providerCalls,
        'input_tokens': inputTokens,
        'output_tokens': outputTokens,
        'image_units': imageUnits,
        'estimated_cost_micros': estimatedCostMicros,
      };
}

class ExportModelBudgetDay {
  const ExportModelBudgetDay({
    required this.usageDate,
    required this.requestCount,
    required this.estimatedCostMicros,
    required this.updatedAt,
  });

  final String usageDate;
  final int requestCount;
  final int estimatedCostMicros;
  final DateTime updatedAt;

  factory ExportModelBudgetDay.fromJson(Map<String, dynamic> json) => ExportModelBudgetDay(
        usageDate: json['usage_date'] as String,
        requestCount: (json['request_count'] as num).toInt(),
        estimatedCostMicros: (json['estimated_cost_micros'] as num).toInt(),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'usage_date': usageDate,
        'request_count': requestCount,
        'estimated_cost_micros': estimatedCostMicros,
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

/// 当前服务端伪名对应的现存调用元数据和student预算桶；不含平台预算、内部调用恢复记录或提示词。无法追溯旧密钥伪名，不代表完整历史。预算估算及保守预占不是实际账单，不得与调用估算相加。
class ExportModelUsage {
  const ExportModelUsage({
    required this.historyComplete,
    required this.identityScope,
    required this.costsAreBilling,
    required this.calls,
    required this.budgetDays,
  });

  final bool historyComplete;
  final String identityScope;
  final bool costsAreBilling;
  final List<ExportModelCall> calls;
  final List<ExportModelBudgetDay> budgetDays;

  factory ExportModelUsage.fromJson(Map<String, dynamic> json) => ExportModelUsage(
        historyComplete: json['history_complete'] as bool,
        identityScope: json['identity_scope'] as String,
        costsAreBilling: json['costs_are_billing'] as bool,
        calls: (json['calls'] as List<dynamic>).map((e) => ExportModelCall.fromJson(e as Map<String, dynamic>)).toList(),
        budgetDays: (json['budget_days'] as List<dynamic>).map((e) => ExportModelBudgetDay.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'history_complete': historyComplete,
        'identity_scope': identityScope,
        'costs_are_billing': costsAreBilling,
        'calls': calls.map((e) => e.toJson()).toList(),
        'budget_days': budgetDays.map((e) => e.toJson()).toList(),
      };
}

class StudentLearningExport {
  const StudentLearningExport({
    this.modelUsage,
    this.parentAccessRecords,
    this.storedScanRecords,
    this.diagnosticRuns,
    this.diagnosticWorkspace,
    required this.formatVersion,
    required this.scope,
    required this.exportedAt,
    required this.profile,
    required this.sessions,
    required this.reviews,
    required this.reviewHistory,
    required this.excluded,
  });

  final ExportModelUsage? modelUsage;
  final ExportParentAccessRecords? parentAccessRecords;
  final List<ExportStoredScan>? storedScanRecords;
  final List<DiagnosticRun>? diagnosticRuns;
  final DiagnosticWorkspace? diagnosticWorkspace;
  final int formatVersion;
  final String scope;
  final DateTime exportedAt;
  final StudentProfile profile;
  final List<ExportLearningSession> sessions;
  final List<ReviewItem> reviews;
  final List<ExportReviewHistory> reviewHistory;
  final List<String> excluded;

  factory StudentLearningExport.fromJson(Map<String, dynamic> json) => StudentLearningExport(
        modelUsage: json['model_usage'] == null ? null : ExportModelUsage.fromJson(json['model_usage'] as Map<String, dynamic>),
        parentAccessRecords: json['parent_access_records'] == null ? null : ExportParentAccessRecords.fromJson(json['parent_access_records'] as Map<String, dynamic>),
        storedScanRecords: json['stored_scan_records'] == null ? null : (json['stored_scan_records'] as List<dynamic>).map((e) => ExportStoredScan.fromJson(e as Map<String, dynamic>)).toList(),
        diagnosticRuns: json['diagnostic_runs'] == null ? null : (json['diagnostic_runs'] as List<dynamic>).map((e) => DiagnosticRun.fromJson(e as Map<String, dynamic>)).toList(),
        diagnosticWorkspace: json['diagnostic_workspace'] == null ? null : DiagnosticWorkspace.fromJson(json['diagnostic_workspace'] as Map<String, dynamic>),
        formatVersion: (json['format_version'] as num).toInt(),
        scope: json['scope'] as String,
        exportedAt: DateTime.parse(json['exported_at'] as String),
        profile: StudentProfile.fromJson(json['profile'] as Map<String, dynamic>),
        sessions: (json['sessions'] as List<dynamic>).map((e) => ExportLearningSession.fromJson(e as Map<String, dynamic>)).toList(),
        reviews: (json['reviews'] as List<dynamic>).map((e) => ReviewItem.fromJson(e as Map<String, dynamic>)).toList(),
        reviewHistory: (json['review_history'] as List<dynamic>).map((e) => ExportReviewHistory.fromJson(e as Map<String, dynamic>)).toList(),
        excluded: (json['excluded'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        if (modelUsage != null) 'model_usage': modelUsage?.toJson(),
        if (parentAccessRecords != null) 'parent_access_records': parentAccessRecords?.toJson(),
        if (storedScanRecords != null) 'stored_scan_records': storedScanRecords?.map((e) => e.toJson()).toList(),
        if (diagnosticRuns != null) 'diagnostic_runs': diagnosticRuns?.map((e) => e.toJson()).toList(),
        if (diagnosticWorkspace != null) 'diagnostic_workspace': diagnosticWorkspace?.toJson(),
        'format_version': formatVersion,
        'scope': scope,
        'exported_at': exportedAt.toUtc().toIso8601String(),
        'profile': profile.toJson(),
        'sessions': sessions.map((e) => e.toJson()).toList(),
        'reviews': reviews.map((e) => e.toJson()).toList(),
        'review_history': reviewHistory.map((e) => e.toJson()).toList(),
        'excluded': excluded,
      };
}

class ReviewState {
  const ReviewState({
    required this.id,
    required this.questionId,
    required this.status,
    required this.stage,
    required this.totalStages,
    required this.dueAt,
    this.lastResult,
    this.lastAttemptId,
    required this.updatedAt,
  });

  final String id;
  final String questionId;
  final ReviewStatus status;
  final int stage;
  final int totalStages;
  final DateTime dueAt;
  final ReviewResult? lastResult;
  final String? lastAttemptId;
  final DateTime updatedAt;

  factory ReviewState.fromJson(Map<String, dynamic> json) => ReviewState(
        id: json['id'] as String,
        questionId: json['question_id'] as String,
        status: ReviewStatus.fromJson(json['status'] as String),
        stage: (json['stage'] as num).toInt(),
        totalStages: (json['total_stages'] as num).toInt(),
        dueAt: DateTime.parse(json['due_at'] as String),
        lastResult: json['last_result'] == null ? null : ReviewResult.fromJson(json['last_result'] as String),
        lastAttemptId: json['last_attempt_id'] == null ? null : json['last_attempt_id'] as String,
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'question_id': questionId,
        'status': status.toJson(),
        'stage': stage,
        'total_stages': totalStages,
        'due_at': dueAt.toUtc().toIso8601String(),
        'last_result': lastResult?.toJson(),
        'last_attempt_id': lastAttemptId,
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class ReviewPage {
  const ReviewPage({
    required this.items,
    this.nextCursor,
  });

  final List<ReviewItem> items;
  final String? nextCursor;

  factory ReviewPage.fromJson(Map<String, dynamic> json) => ReviewPage(
        items: (json['items'] as List<dynamic>).map((e) => ReviewItem.fromJson(e as Map<String, dynamic>)).toList(),
        nextCursor: json['next_cursor'] == null ? null : json['next_cursor'] as String,
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
        'next_cursor': nextCursor,
      };
}

class ReviewComplete {
  const ReviewComplete({
    required this.attemptId,
  });

  final String attemptId;

  factory ReviewComplete.fromJson(Map<String, dynamic> json) => ReviewComplete(
        attemptId: json['attempt_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'attempt_id': attemptId,
      };
}

class ReviewCompletion {
  const ReviewCompletion({
    required this.reviewItem,
    required this.result,
    this.nextDueAt,
  });

  final ReviewItem reviewItem;
  final ReviewResult result;
  final DateTime? nextDueAt;

  factory ReviewCompletion.fromJson(Map<String, dynamic> json) => ReviewCompletion(
        reviewItem: ReviewItem.fromJson(json['review_item'] as Map<String, dynamic>),
        result: ReviewResult.fromJson(json['result'] as String),
        nextDueAt: json['next_due_at'] == null ? null : DateTime.parse(json['next_due_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'review_item': reviewItem.toJson(),
        'result': result.toJson(),
        'next_due_at': nextDueAt?.toUtc().toIso8601String(),
      };
}

class RateStat {
  const RateStat({
    required this.numerator,
    required this.denominator,
    this.rate,
    required this.insufficientData,
  });

  final int numerator;
  final int denominator;
  final double? rate;
  final bool insufficientData;

  factory RateStat.fromJson(Map<String, dynamic> json) => RateStat(
        numerator: (json['numerator'] as num).toInt(),
        denominator: (json['denominator'] as num).toInt(),
        rate: json['rate'] == null ? null : (json['rate'] as num).toDouble(),
        insufficientData: json['insufficient_data'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'numerator': numerator,
        'denominator': denominator,
        'rate': rate,
        'insufficient_data': insufficientData,
      };
}

class ProgressBucket {
  const ProgressBucket({
    required this.key,
    required this.label,
    required this.independent,
    required this.assisted,
  });

  final String key;
  final String label;
  final RateStat independent;
  final RateStat assisted;

  factory ProgressBucket.fromJson(Map<String, dynamic> json) => ProgressBucket(
        key: json['key'] as String,
        label: json['label'] as String,
        independent: RateStat.fromJson(json['independent'] as Map<String, dynamic>),
        assisted: RateStat.fromJson(json['assisted'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'label': label,
        'independent': independent.toJson(),
        'assisted': assisted.toJson(),
      };
}

/// 解答题、实验题和证明题不自动评分，所以不进任何正确率。这里只数：提交了几份、其中自查了几份， 以及自查里各档要点的个数（只统计已保存自查的作答）。这些都是学生自己的记录。
class SubjectiveProgress {
  const SubjectiveProgress({
    required this.attempts,
    required this.selfChecked,
    required this.pointsDone,
    required this.pointsPartial,
    required this.pointsMissed,
  });

  final int attempts;
  final int selfChecked;
  final int pointsDone;
  final int pointsPartial;
  final int pointsMissed;

  factory SubjectiveProgress.fromJson(Map<String, dynamic> json) => SubjectiveProgress(
        attempts: (json['attempts'] as num).toInt(),
        selfChecked: (json['self_checked'] as num).toInt(),
        pointsDone: (json['points_done'] as num).toInt(),
        pointsPartial: (json['points_partial'] as num).toInt(),
        pointsMissed: (json['points_missed'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'attempts': attempts,
        'self_checked': selfChecked,
        'points_done': pointsDone,
        'points_partial': pointsPartial,
        'points_missed': pointsMissed,
      };
}

class ProgressSummary {
  const ProgressSummary({
    required this.generatedAt,
    required this.minSamples,
    required this.independent,
    required this.assisted,
    required this.hintDependency,
    required this.retestSuccess,
    required this.variantTransfer,
    required this.uncertainAttempts,
    required this.subjective,
    required this.bySubject,
    required this.byAnswerMode,
    required this.byDifficulty,
    required this.disclaimer,
  });

  final DateTime generatedAt;
  final int minSamples;
  final RateStat independent;
  final RateStat assisted;
  final RateStat hintDependency;
  final RateStat retestSuccess;
  final RateStat variantTransfer;
  final int uncertainAttempts;
  final SubjectiveProgress subjective;
  final List<ProgressBucket> bySubject;
  final List<ProgressBucket> byAnswerMode;
  final List<ProgressBucket> byDifficulty;
  final String disclaimer;

  factory ProgressSummary.fromJson(Map<String, dynamic> json) => ProgressSummary(
        generatedAt: DateTime.parse(json['generated_at'] as String),
        minSamples: (json['min_samples'] as num).toInt(),
        independent: RateStat.fromJson(json['independent'] as Map<String, dynamic>),
        assisted: RateStat.fromJson(json['assisted'] as Map<String, dynamic>),
        hintDependency: RateStat.fromJson(json['hint_dependency'] as Map<String, dynamic>),
        retestSuccess: RateStat.fromJson(json['retest_success'] as Map<String, dynamic>),
        variantTransfer: RateStat.fromJson(json['variant_transfer'] as Map<String, dynamic>),
        uncertainAttempts: (json['uncertain_attempts'] as num).toInt(),
        subjective: SubjectiveProgress.fromJson(json['subjective'] as Map<String, dynamic>),
        bySubject: (json['by_subject'] as List<dynamic>).map((e) => ProgressBucket.fromJson(e as Map<String, dynamic>)).toList(),
        byAnswerMode: (json['by_answer_mode'] as List<dynamic>).map((e) => ProgressBucket.fromJson(e as Map<String, dynamic>)).toList(),
        byDifficulty: (json['by_difficulty'] as List<dynamic>).map((e) => ProgressBucket.fromJson(e as Map<String, dynamic>)).toList(),
        disclaimer: json['disclaimer'] as String,
      );

  Map<String, dynamic> toJson() => {
        'generated_at': generatedAt.toUtc().toIso8601String(),
        'min_samples': minSamples,
        'independent': independent.toJson(),
        'assisted': assisted.toJson(),
        'hint_dependency': hintDependency.toJson(),
        'retest_success': retestSuccess.toJson(),
        'variant_transfer': variantTransfer.toJson(),
        'uncertain_attempts': uncertainAttempts,
        'subjective': subjective.toJson(),
        'by_subject': bySubject.map((e) => e.toJson()).toList(),
        'by_answer_mode': byAnswerMode.map((e) => e.toJson()).toList(),
        'by_difficulty': byDifficulty.map((e) => e.toJson()).toList(),
        'disclaimer': disclaimer,
      };
}

class MediaReviewConfirmation {
  const MediaReviewConfirmation({
    required this.expectedVersion,
    required this.sha256,
    required this.confirmed,
  });

  final int expectedVersion;
  final String sha256;
  final bool confirmed;

  factory MediaReviewConfirmation.fromJson(Map<String, dynamic> json) => MediaReviewConfirmation(
        expectedVersion: (json['expected_version'] as num).toInt(),
        sha256: json['sha256'] as String,
        confirmed: json['confirmed'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'expected_version': expectedVersion,
        'sha256': sha256,
        'confirmed': confirmed,
      };
}

class MediaReviewDeclaration {
  const MediaReviewDeclaration({
    required this.questionId,
    required this.version,
    required this.mediaId,
    required this.sha256,
    required this.actorId,
    required this.expiresAt,
  });

  final String questionId;
  final int version;
  final String mediaId;
  final String sha256;
  final String actorId;
  final DateTime expiresAt;

  factory MediaReviewDeclaration.fromJson(Map<String, dynamic> json) => MediaReviewDeclaration(
        questionId: json['question_id'] as String,
        version: (json['version'] as num).toInt(),
        mediaId: json['media_id'] as String,
        sha256: json['sha256'] as String,
        actorId: json['actor_id'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'question_id': questionId,
        'version': version,
        'media_id': mediaId,
        'sha256': sha256,
        'actor_id': actorId,
        'expires_at': expiresAt.toUtc().toIso8601String(),
      };
}

class SchoolMaterialConfirmationRequest {
  const SchoolMaterialConfirmationRequest({
    required this.sourceRevision,
    required this.items,
  });

  final String sourceRevision;
  final List<SchoolMaterialConfirmedItem> items;

  factory SchoolMaterialConfirmationRequest.fromJson(Map<String, dynamic> json) => SchoolMaterialConfirmationRequest(
        sourceRevision: json['source_revision'] as String,
        items: (json['items'] as List<dynamic>).map((e) => SchoolMaterialConfirmedItem.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'source_revision': sourceRevision,
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class SchoolMaterialConfirmedItem {
  const SchoolMaterialConfirmedItem({
    required this.text,
    required this.pages,
  });

  final String text;
  final List<int> pages;

  factory SchoolMaterialConfirmedItem.fromJson(Map<String, dynamic> json) => SchoolMaterialConfirmedItem(
        text: json['text'] as String,
        pages: (json['pages'] as List<dynamic>).map((e) => (e as num).toInt()).toList(),
      );

  Map<String, dynamic> toJson() => {
        'text': text,
        'pages': pages,
      };
}

class SchoolMaterialConfirmationReceipt {
  const SchoolMaterialConfirmationReceipt({
    required this.sourceRevision,
    required this.itemCount,
  });

  final String sourceRevision;
  final int itemCount;

  factory SchoolMaterialConfirmationReceipt.fromJson(Map<String, dynamic> json) => SchoolMaterialConfirmationReceipt(
        sourceRevision: json['source_revision'] as String,
        itemCount: (json['item_count'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'source_revision': sourceRevision,
        'item_count': itemCount,
      };
}

class SchoolMaterialCandidates {
  const SchoolMaterialCandidates({
    this.sourceRevision,
    this.confirmedItems,
    required this.items,
  });

  final String? sourceRevision;
  final List<SchoolMaterialConfirmedItem>? confirmedItems;
  final List<SchoolMaterialCandidate> items;

  factory SchoolMaterialCandidates.fromJson(Map<String, dynamic> json) => SchoolMaterialCandidates(
        sourceRevision: json['source_revision'] == null ? null : json['source_revision'] as String,
        confirmedItems: json['confirmed_items'] == null ? null : (json['confirmed_items'] as List<dynamic>).map((e) => SchoolMaterialConfirmedItem.fromJson(e as Map<String, dynamic>)).toList(),
        items: (json['items'] as List<dynamic>).map((e) => SchoolMaterialCandidate.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        if (sourceRevision != null) 'source_revision': sourceRevision,
        if (confirmedItems != null) 'confirmed_items': confirmedItems?.map((e) => e.toJson()).toList(),
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class SchoolMaterialCandidate {
  const SchoolMaterialCandidate({
    required this.text,
    required this.locations,
    required this.warnings,
  });

  final String text;
  final List<SchoolMaterialCandidateLocation> locations;
  final List<String> warnings;

  factory SchoolMaterialCandidate.fromJson(Map<String, dynamic> json) => SchoolMaterialCandidate(
        text: json['text'] as String,
        locations: (json['locations'] as List<dynamic>).map((e) => SchoolMaterialCandidateLocation.fromJson(e as Map<String, dynamic>)).toList(),
        warnings: (json['warnings'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        'text': text,
        'locations': locations.map((e) => e.toJson()).toList(),
        'warnings': warnings,
      };
}

class SchoolMaterialCandidateLocation {
  const SchoolMaterialCandidateLocation({
    required this.page,
    this.block,
  });

  final int page;
  final int? block;

  factory SchoolMaterialCandidateLocation.fromJson(Map<String, dynamic> json) => SchoolMaterialCandidateLocation(
        page: (json['page'] as num).toInt(),
        block: json['block'] == null ? null : (json['block'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'page': page,
        'block': block,
      };
}

class SchoolMaterialPages {
  const SchoolMaterialPages({
    required this.pages,
  });

  final List<SchoolMaterialPage> pages;

  factory SchoolMaterialPages.fromJson(Map<String, dynamic> json) => SchoolMaterialPages(
        pages: (json['pages'] as List<dynamic>).map((e) => SchoolMaterialPage.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'pages': pages.map((e) => e.toJson()).toList(),
      };
}

class SchoolMaterialPage {
  const SchoolMaterialPage({
    required this.pageNumber,
    required this.text,
    required this.needsOcr,
    this.revision,
  });

  final int pageNumber;
  final String text;
  final bool needsOcr;
  final int? revision;

  factory SchoolMaterialPage.fromJson(Map<String, dynamic> json) => SchoolMaterialPage(
        pageNumber: (json['page_number'] as num).toInt(),
        text: json['text'] as String,
        needsOcr: json['needs_ocr'] as bool,
        revision: json['revision'] == null ? null : (json['revision'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'page_number': pageNumber,
        'text': text,
        'needs_ocr': needsOcr,
        if (revision != null) 'revision': revision,
      };
}

class SchoolMaterialCorrectionReceipt {
  const SchoolMaterialCorrectionReceipt({
    required this.pageNumber,
    required this.revision,
  });

  final int pageNumber;
  final int revision;

  factory SchoolMaterialCorrectionReceipt.fromJson(Map<String, dynamic> json) => SchoolMaterialCorrectionReceipt(
        pageNumber: (json['page_number'] as num).toInt(),
        revision: (json['revision'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'page_number': pageNumber,
        'revision': revision,
      };
}

class SchoolMaterialPageCorrection {
  const SchoolMaterialPageCorrection({
    required this.expectedRevision,
    required this.text,
  });

  final int expectedRevision;
  final String text;

  factory SchoolMaterialPageCorrection.fromJson(Map<String, dynamic> json) => SchoolMaterialPageCorrection(
        expectedRevision: (json['expected_revision'] as num).toInt(),
        text: json['text'] as String,
      );

  Map<String, dynamic> toJson() => {
        'expected_revision': expectedRevision,
        'text': text,
      };
}

class SchoolMaterialSubmitRequest {
  const SchoolMaterialSubmitRequest({
    required this.mediaId,
  });

  final String mediaId;

  factory SchoolMaterialSubmitRequest.fromJson(Map<String, dynamic> json) => SchoolMaterialSubmitRequest(
        mediaId: json['media_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
      };
}

class SchoolMaterialUploadRequest {
  const SchoolMaterialUploadRequest({
    required this.mime,
    required this.sizeBytes,
    required this.sha256,
  });

  final String mime;
  final int sizeBytes;
  final String sha256;

  factory SchoolMaterialUploadRequest.fromJson(Map<String, dynamic> json) => SchoolMaterialUploadRequest(
        mime: json['mime'] as String,
        sizeBytes: (json['size_bytes'] as num).toInt(),
        sha256: json['sha256'] as String,
      );

  Map<String, dynamic> toJson() => {
        'mime': mime,
        'size_bytes': sizeBytes,
        'sha256': sha256,
      };
}

class SchoolMaterialSource {
  const SchoolMaterialSource({
    required this.mediaId,
    required this.mime,
    required this.sizeBytes,
    required this.sha256,
    required this.expiresAt,
    required this.pageCount,
  });

  final String mediaId;
  final String mime;
  final int sizeBytes;
  final String sha256;
  final DateTime expiresAt;
  final int pageCount;

  factory SchoolMaterialSource.fromJson(Map<String, dynamic> json) => SchoolMaterialSource(
        mediaId: json['media_id'] as String,
        mime: json['mime'] as String,
        sizeBytes: (json['size_bytes'] as num).toInt(),
        sha256: json['sha256'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String),
        pageCount: (json['page_count'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
        'mime': mime,
        'size_bytes': sizeBytes,
        'sha256': sha256,
        'expires_at': expiresAt.toUtc().toIso8601String(),
        'page_count': pageCount,
      };
}

class MediaBlobUpload {
  const MediaBlobUpload({
    required this.contentBase64,
  });

  final String contentBase64;

  factory MediaBlobUpload.fromJson(Map<String, dynamic> json) => MediaBlobUpload(
        contentBase64: json['content_base64'] as String,
      );

  Map<String, dynamic> toJson() => {
        'content_base64': contentBase64,
      };
}

class MediaConfirm {
  const MediaConfirm({
    required this.sha256,
  });

  final String sha256;

  factory MediaConfirm.fromJson(Map<String, dynamic> json) => MediaConfirm(
        sha256: json['sha256'] as String,
      );

  Map<String, dynamic> toJson() => {
        'sha256': sha256,
      };
}

class MediaDelete {
  const MediaDelete();


  factory MediaDelete.fromJson(Map<String, dynamic> json) => MediaDelete(
      );

  Map<String, dynamic> toJson() => {
      };
}

class MediaAssetInfo {
  const MediaAssetInfo({
    required this.mediaId,
    required this.mime,
    required this.sizeBytes,
    required this.sha256,
    required this.expiresAt,
  });

  final String mediaId;
  final String mime;
  final int sizeBytes;
  final String sha256;
  final DateTime expiresAt;

  factory MediaAssetInfo.fromJson(Map<String, dynamic> json) => MediaAssetInfo(
        mediaId: json['media_id'] as String,
        mime: json['mime'] as String,
        sizeBytes: (json['size_bytes'] as num).toInt(),
        sha256: json['sha256'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
        'mime': mime,
        'size_bytes': sizeBytes,
        'sha256': sha256,
        'expires_at': expiresAt.toUtc().toIso8601String(),
      };
}

class MediaContent {
  const MediaContent({
    required this.mediaId,
    required this.mime,
    required this.contentBase64,
  });

  final String mediaId;
  final String mime;
  final String contentBase64;

  factory MediaContent.fromJson(Map<String, dynamic> json) => MediaContent(
        mediaId: json['media_id'] as String,
        mime: json['mime'] as String,
        contentBase64: json['content_base64'] as String,
      );

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
        'mime': mime,
        'content_base64': contentBase64,
      };
}

class MediaDeleted {
  const MediaDeleted({
    required this.mediaId,
    required this.deleted,
  });

  final String mediaId;
  final bool deleted;

  factory MediaDeleted.fromJson(Map<String, dynamic> json) => MediaDeleted(
        mediaId: json['media_id'] as String,
        deleted: json['deleted'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
        'deleted': deleted,
      };
}

class MediaUploadRequest {
  const MediaUploadRequest({
    required this.purpose,
    required this.mime,
    required this.sizeBytes,
    required this.sha256,
  });

  final String purpose;
  final String mime;
  final int sizeBytes;
  final String sha256;

  factory MediaUploadRequest.fromJson(Map<String, dynamic> json) => MediaUploadRequest(
        purpose: json['purpose'] as String,
        mime: json['mime'] as String,
        sizeBytes: (json['size_bytes'] as num).toInt(),
        sha256: json['sha256'] as String,
      );

  Map<String, dynamic> toJson() => {
        'purpose': purpose,
        'mime': mime,
        'size_bytes': sizeBytes,
        'sha256': sha256,
      };
}

class MediaUpload {
  const MediaUpload({
    required this.mediaId,
    required this.uploadUrl,
    required this.uploadMethod,
    required this.expiresAt,
    required this.maxBytes,
  });

  final String mediaId;
  final String uploadUrl;
  final String uploadMethod;
  final DateTime expiresAt;
  final int maxBytes;

  factory MediaUpload.fromJson(Map<String, dynamic> json) => MediaUpload(
        mediaId: json['media_id'] as String,
        uploadUrl: json['upload_url'] as String,
        uploadMethod: json['upload_method'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String),
        maxBytes: (json['max_bytes'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
        'upload_url': uploadUrl,
        'upload_method': uploadMethod,
        'expires_at': expiresAt.toUtc().toIso8601String(),
        'max_bytes': maxBytes,
      };
}

class ScanCreate {
  const ScanCreate({
    required this.mediaId,
  });

  final String mediaId;

  factory ScanCreate.fromJson(Map<String, dynamic> json) => ScanCreate(
        mediaId: json['media_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
      };
}

class ScanExpression {
  const ScanExpression({
    required this.spanId,
    required this.latex,
    this.confidence,
  });

  final String spanId;
  final String latex;
  final double? confidence;

  factory ScanExpression.fromJson(Map<String, dynamic> json) => ScanExpression(
        spanId: json['span_id'] as String,
        latex: json['latex'] as String,
        confidence: json['confidence'] == null ? null : (json['confidence'] as num).toDouble(),
      );

  Map<String, dynamic> toJson() => {
        'span_id': spanId,
        'latex': latex,
        'confidence': confidence,
      };
}

class Scan {
  const Scan({
    required this.id,
    required this.status,
    this.confidence,
    required this.lowConfidence,
    this.stemText,
    required this.expressions,
    this.matchedQuestionId,
    this.errorCode,
    this.mockNotice,
  });

  final String id;
  final String status;
  final double? confidence;
  final bool lowConfidence;
  final String? stemText;
  final List<ScanExpression> expressions;
  final String? matchedQuestionId;
  final String? errorCode;
  final String? mockNotice;

  factory Scan.fromJson(Map<String, dynamic> json) => Scan(
        id: json['id'] as String,
        status: json['status'] as String,
        confidence: json['confidence'] == null ? null : (json['confidence'] as num).toDouble(),
        lowConfidence: json['low_confidence'] as bool,
        stemText: json['stem_text'] == null ? null : json['stem_text'] as String,
        expressions: (json['expressions'] as List<dynamic>).map((e) => ScanExpression.fromJson(e as Map<String, dynamic>)).toList(),
        matchedQuestionId: json['matched_question_id'] == null ? null : json['matched_question_id'] as String,
        errorCode: json['error_code'] == null ? null : json['error_code'] as String,
        mockNotice: json['mock_notice'] == null ? null : json['mock_notice'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'status': status,
        'confidence': confidence,
        'low_confidence': lowConfidence,
        'stem_text': stemText,
        'expressions': expressions.map((e) => e.toJson()).toList(),
        'matched_question_id': matchedQuestionId,
        'error_code': errorCode,
        if (mockNotice != null) 'mock_notice': mockNotice,
      };
}

class ScanConfirm {
  const ScanConfirm({
    required this.stemText,
    required this.expressions,
  });

  final String stemText;
  final List<ScanExpression> expressions;

  factory ScanConfirm.fromJson(Map<String, dynamic> json) => ScanConfirm(
        stemText: json['stem_text'] as String,
        expressions: (json['expressions'] as List<dynamic>).map((e) => ScanExpression.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'stem_text': stemText,
        'expressions': expressions.map((e) => e.toJson()).toList(),
      };
}

class ScanConfirmation {
  const ScanConfirmation({
    required this.scan,
    this.questionId,
    this.draftQuestionId,
  });

  final Scan scan;
  final String? questionId;
  final String? draftQuestionId;

  factory ScanConfirmation.fromJson(Map<String, dynamic> json) => ScanConfirmation(
        scan: Scan.fromJson(json['scan'] as Map<String, dynamic>),
        questionId: json['question_id'] == null ? null : json['question_id'] as String,
        draftQuestionId: json['draft_question_id'] == null ? null : json['draft_question_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'scan': scan.toJson(),
        'question_id': questionId,
        'draft_question_id': draftQuestionId,
      };
}

/// 学生生成的一次性邀请码。`code` 只在创建时出现这一次，之后任何接口都不会再返回它。
class ParentInvite {
  const ParentInvite({
    this.parentInviteRevision,
    required this.id,
    required this.code,
    required this.createdAt,
    required this.expiresAt,
  });

  final int? parentInviteRevision;
  final String id;
  final String code;
  final DateTime createdAt;
  final DateTime expiresAt;

  factory ParentInvite.fromJson(Map<String, dynamic> json) => ParentInvite(
        parentInviteRevision: json['parent_invite_revision'] == null ? null : (json['parent_invite_revision'] as num).toInt(),
        id: json['id'] as String,
        code: json['code'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        expiresAt: DateTime.parse(json['expires_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        if (parentInviteRevision != null) 'parent_invite_revision': parentInviteRevision,
        'id': id,
        'code': code,
        'created_at': createdAt.toUtc().toIso8601String(),
        'expires_at': expiresAt.toUtc().toIso8601String(),
      };
}

class ParentInviteCreate {
  const ParentInviteCreate({
    required this.expectedParentInviteRevision,
  });

  final int expectedParentInviteRevision;

  factory ParentInviteCreate.fromJson(Map<String, dynamic> json) => ParentInviteCreate(
        expectedParentInviteRevision: (json['expected_parent_invite_revision'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'expected_parent_invite_revision': expectedParentInviteRevision,
      };
}

class ParentLinkRevoke {
  const ParentLinkRevoke({
    required this.expectedAuthorizationRevision,
  });

  final int expectedAuthorizationRevision;

  factory ParentLinkRevoke.fromJson(Map<String, dynamic> json) => ParentLinkRevoke(
        expectedAuthorizationRevision: (json['expected_authorization_revision'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'expected_authorization_revision': expectedAuthorizationRevision,
      };
}

class ParentInviteRedeem {
  const ParentInviteRedeem({
    required this.code,
  });

  final String code;

  factory ParentInviteRedeem.fromJson(Map<String, dynamic> json) => ParentInviteRedeem(
        code: json['code'] as String,
      );

  Map<String, dynamic> toJson() => {
        'code': code,
      };
}

/// 一个还没被使用、也没过期的邀请码。这里看不到码本身。
class PendingParentInvite {
  const PendingParentInvite({
    required this.id,
    required this.createdAt,
    required this.expiresAt,
  });

  final String id;
  final DateTime createdAt;
  final DateTime expiresAt;

  factory PendingParentInvite.fromJson(Map<String, dynamic> json) => PendingParentInvite(
        id: json['id'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        expiresAt: DateTime.parse(json['expires_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'created_at': createdAt.toUtc().toIso8601String(),
        'expires_at': expiresAt.toUtc().toIso8601String(),
      };
}

/// 学生对一位家长的授权。
class ParentLink {
  const ParentLink({
    this.authorizationRevision,
    required this.id,
    required this.parentId,
    this.parentLabel,
    required this.consentAt,
    required this.linkedAt,
    this.revokedAt,
  });

  final int? authorizationRevision;
  final String id;
  final String parentId;
  final String? parentLabel;
  final DateTime consentAt;
  final DateTime linkedAt;
  final DateTime? revokedAt;

  factory ParentLink.fromJson(Map<String, dynamic> json) => ParentLink(
        authorizationRevision: json['authorization_revision'] == null ? null : (json['authorization_revision'] as num).toInt(),
        id: json['id'] as String,
        parentId: json['parent_id'] as String,
        parentLabel: json['parent_label'] == null ? null : json['parent_label'] as String,
        consentAt: DateTime.parse(json['consent_at'] as String),
        linkedAt: DateTime.parse(json['linked_at'] as String),
        revokedAt: json['revoked_at'] == null ? null : DateTime.parse(json['revoked_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        if (authorizationRevision != null) 'authorization_revision': authorizationRevision,
        'id': id,
        'parent_id': parentId,
        'parent_label': parentLabel,
        'consent_at': consentAt.toUtc().toIso8601String(),
        'linked_at': linkedAt.toUtc().toIso8601String(),
        'revoked_at': revokedAt?.toUtc().toIso8601String(),
      };
}

class ParentLinks {
  const ParentLinks({
    this.parentInviteRevision,
    required this.links,
    this.pendingInvite,
  });

  final int? parentInviteRevision;
  final List<ParentLink> links;
  final PendingParentInvite? pendingInvite;

  factory ParentLinks.fromJson(Map<String, dynamic> json) => ParentLinks(
        parentInviteRevision: json['parent_invite_revision'] == null ? null : (json['parent_invite_revision'] as num).toInt(),
        links: (json['links'] as List<dynamic>).map((e) => ParentLink.fromJson(e as Map<String, dynamic>)).toList(),
        pendingInvite: json['pending_invite'] == null ? null : PendingParentInvite.fromJson(json['pending_invite'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        if (parentInviteRevision != null) 'parent_invite_revision': parentInviteRevision,
        'links': links.map((e) => e.toJson()).toList(),
        'pending_invite': pendingInvite?.toJson(),
      };
}

/// 家长能看的一位学生。
class ParentStudent {
  const ParentStudent({
    required this.studentId,
    this.displayName,
    required this.linkedAt,
  });

  final String studentId;
  final String? displayName;
  final DateTime linkedAt;

  factory ParentStudent.fromJson(Map<String, dynamic> json) => ParentStudent(
        studentId: json['student_id'] as String,
        displayName: json['display_name'] == null ? null : json['display_name'] as String,
        linkedAt: DateTime.parse(json['linked_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'student_id': studentId,
        'display_name': displayName,
        'linked_at': linkedAt.toUtc().toIso8601String(),
      };
}

class ParentStudents {
  const ParentStudents({
    required this.items,
  });

  final List<ParentStudent> items;

  factory ParentStudents.fromJson(Map<String, dynamic> json) => ParentStudents(
        items: (json['items'] as List<dynamic>).map((e) => ParentStudent.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
      };
}

/// 独立正确率和上一周比：up 高了，down 低了，flat 差不多（差距不到 5 个百分点），unknown 两周里有一周样本不足。
enum WeeklyTrend {
  up('up'),
  down('down'),
  flat('flat'),
  unknown('unknown'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const WeeklyTrend(this.value);
  final String value;

  static WeeklyTrend fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => WeeklyTrend.$unknown);

  String toJson() => value;
}

/// 上一周的几个数，用来看趋势。
class PreviousWeek {
  const PreviousWeek({
    required this.weekStart,
    required this.attemptsCount,
    required this.independent,
  });

  final String weekStart;
  final int attemptsCount;
  final RateStat independent;

  factory PreviousWeek.fromJson(Map<String, dynamic> json) => PreviousWeek(
        weekStart: json['week_start'] as String,
        attemptsCount: (json['attempts_count'] as num).toInt(),
        independent: RateStat.fromJson(json['independent'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'week_start': weekStart,
        'attempts_count': attemptsCount,
        'independent': independent.toJson(),
      };
}

class PaperWeeklySummary {
  const PaperWeeklySummary({
    required this.confirmed,
    required this.awaitingAssessment,
    required this.lateReturns,
    required this.unknownCompletionDate,
    required this.independent,
    required this.assisted,
  });

  final int confirmed;
  final int awaitingAssessment;
  final int lateReturns;
  final int unknownCompletionDate;
  final RateStat independent;
  final RateStat assisted;

  factory PaperWeeklySummary.fromJson(Map<String, dynamic> json) => PaperWeeklySummary(
        confirmed: (json['confirmed'] as num).toInt(),
        awaitingAssessment: (json['awaiting_assessment'] as num).toInt(),
        lateReturns: (json['late_returns'] as num).toInt(),
        unknownCompletionDate: (json['unknown_completion_date'] as num).toInt(),
        independent: RateStat.fromJson(json['independent'] as Map<String, dynamic>),
        assisted: RateStat.fromJson(json['assisted'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'confirmed': confirmed,
        'awaiting_assessment': awaitingAssessment,
        'late_returns': lateReturns,
        'unknown_completion_date': unknownCompletionDate,
        'independent': independent.toJson(),
        'assisted': assisted.toJson(),
      };
}

class ParentWeeklySnapshot {
  const ParentWeeklySnapshot({
    required this.revision,
    required this.report,
  });

  final int revision;
  final ParentWeekly report;

  factory ParentWeeklySnapshot.fromJson(Map<String, dynamic> json) => ParentWeeklySnapshot(
        revision: (json['revision'] as num).toInt(),
        report: ParentWeekly.fromJson(json['report'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'revision': revision,
        'report': report.toJson(),
      };
}

/// 一位已授权学生某一周的汇总。只有计数和比例：没有具体题目、作答内容、提示原文、草稿和笔迹， 也没有每次练习的时间。周从周一到周日，按服务端配置的时区划分。样本少于 `min_samples` 的比例是 null，只给计数。 不是官方成绩，没有排名，也没有连续天数。
class ParentWeekly {
  const ParentWeekly({
    this.paper,
    required this.studentId,
    this.studentDisplayName,
    required this.weekStart,
    required this.weekEnd,
    required this.isComplete,
    required this.generatedAt,
    required this.minSamples,
    required this.sessionsCount,
    required this.attemptsCount,
    required this.activeDays,
    required this.independent,
    required this.assisted,
    required this.hintDependency,
    required this.retestSuccess,
    required this.writtenAttempts,
    required this.independentTrend,
    required this.previousWeek,
    required this.bySubject,
    required this.disclaimer,
  });

  final PaperWeeklySummary? paper;
  final String studentId;
  final String? studentDisplayName;
  final String weekStart;
  final String weekEnd;
  final bool isComplete;
  final DateTime generatedAt;
  final int minSamples;
  final int sessionsCount;
  final int attemptsCount;
  final int activeDays;
  final RateStat independent;
  final RateStat assisted;
  final RateStat hintDependency;
  final RateStat retestSuccess;
  final int writtenAttempts;
  final WeeklyTrend independentTrend;
  final PreviousWeek previousWeek;
  final List<ProgressBucket> bySubject;
  final String disclaimer;

  factory ParentWeekly.fromJson(Map<String, dynamic> json) => ParentWeekly(
        paper: json['paper'] == null ? null : PaperWeeklySummary.fromJson(json['paper'] as Map<String, dynamic>),
        studentId: json['student_id'] as String,
        studentDisplayName: json['student_display_name'] == null ? null : json['student_display_name'] as String,
        weekStart: json['week_start'] as String,
        weekEnd: json['week_end'] as String,
        isComplete: json['is_complete'] as bool,
        generatedAt: DateTime.parse(json['generated_at'] as String),
        minSamples: (json['min_samples'] as num).toInt(),
        sessionsCount: (json['sessions_count'] as num).toInt(),
        attemptsCount: (json['attempts_count'] as num).toInt(),
        activeDays: (json['active_days'] as num).toInt(),
        independent: RateStat.fromJson(json['independent'] as Map<String, dynamic>),
        assisted: RateStat.fromJson(json['assisted'] as Map<String, dynamic>),
        hintDependency: RateStat.fromJson(json['hint_dependency'] as Map<String, dynamic>),
        retestSuccess: RateStat.fromJson(json['retest_success'] as Map<String, dynamic>),
        writtenAttempts: (json['written_attempts'] as num).toInt(),
        independentTrend: WeeklyTrend.fromJson(json['independent_trend'] as String),
        previousWeek: PreviousWeek.fromJson(json['previous_week'] as Map<String, dynamic>),
        bySubject: (json['by_subject'] as List<dynamic>).map((e) => ProgressBucket.fromJson(e as Map<String, dynamic>)).toList(),
        disclaimer: json['disclaimer'] as String,
      );

  Map<String, dynamic> toJson() => {
        if (paper != null) 'paper': paper?.toJson(),
        'student_id': studentId,
        'student_display_name': studentDisplayName,
        'week_start': weekStart,
        'week_end': weekEnd,
        'is_complete': isComplete,
        'generated_at': generatedAt.toUtc().toIso8601String(),
        'min_samples': minSamples,
        'sessions_count': sessionsCount,
        'attempts_count': attemptsCount,
        'active_days': activeDays,
        'independent': independent.toJson(),
        'assisted': assisted.toJson(),
        'hint_dependency': hintDependency.toJson(),
        'retest_success': retestSuccess.toJson(),
        'written_attempts': writtenAttempts,
        'independent_trend': independentTrend.toJson(),
        'previous_week': previousWeek.toJson(),
        'by_subject': bySubject.map((e) => e.toJson()).toList(),
        'disclaimer': disclaimer,
      };
}

/// docs/07 的审校状态。draft 编辑中；reviewed 已独立二审；published 已上线；withdrawn 因问题下线（终态）。
enum QuestionStatus {
  draft('draft'),
  reviewed('reviewed'),
  published('published'),
  withdrawn('withdrawn'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const QuestionStatus(this.value);
  final String value;

  static QuestionStatus fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => QuestionStatus.$unknown);

  String toJson() => value;
}

/// approve 二审通过；reject 退回修改（须写原因）；publish 上线；withdraw 下线（须写原因）。
enum ReviewDecisionType {
  approve('approve'),
  reject('reject'),
  publish('publish'),
  withdraw('withdraw'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const ReviewDecisionType(this.value);
  final String value;

  static ReviewDecisionType fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => ReviewDecisionType.$unknown);

  String toJson() => value;
}

enum SolutionKind {
  standard('standard'),
  fast('fast'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const SolutionKind(this.value);
  final String value;

  static SolutionKind fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => SolutionKind.$unknown);

  String toJson() => value;
}

class ReviewBatchItem {
  const ReviewBatchItem({
    required this.expectedReviewRevision,
    required this.questionId,
    required this.expectedVersion,
    required this.decision,
    required this.confirmed,
    this.comment,
    this.solutionKinds,
  });

  final int expectedReviewRevision;
  final String questionId;
  final int expectedVersion;
  final ReviewDecisionType decision;
  final bool confirmed;
  final String? comment;
  final List<SolutionKind>? solutionKinds;

  factory ReviewBatchItem.fromJson(Map<String, dynamic> json) => ReviewBatchItem(
        expectedReviewRevision: (json['expected_review_revision'] as num).toInt(),
        questionId: json['question_id'] as String,
        expectedVersion: (json['expected_version'] as num).toInt(),
        decision: ReviewDecisionType.fromJson(json['decision'] as String),
        confirmed: json['confirmed'] as bool,
        comment: json['comment'] == null ? null : json['comment'] as String,
        solutionKinds: json['solution_kinds'] == null ? null : (json['solution_kinds'] as List<dynamic>).map((e) => SolutionKind.fromJson(e as String)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'expected_review_revision': expectedReviewRevision,
        'question_id': questionId,
        'expected_version': expectedVersion,
        'decision': decision.toJson(),
        'confirmed': confirmed,
        if (comment != null) 'comment': comment,
        if (solutionKinds != null) 'solution_kinds': solutionKinds?.map((e) => e.toJson()).toList(),
      };
}

class ReviewBatch {
  const ReviewBatch({
    required this.items,
  });

  final List<ReviewBatchItem> items;

  factory ReviewBatch.fromJson(Map<String, dynamic> json) => ReviewBatch(
        items: (json['items'] as List<dynamic>).map((e) => ReviewBatchItem.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class ReviewBatchError {
  const ReviewBatchError({
    required this.status,
    required this.code,
    required this.message,
  });

  final int status;
  final String code;
  final String message;

  factory ReviewBatchError.fromJson(Map<String, dynamic> json) => ReviewBatchError(
        status: (json['status'] as num).toInt(),
        code: json['code'] as String,
        message: json['message'] as String,
      );

  Map<String, dynamic> toJson() => {
        'status': status,
        'code': code,
        'message': message,
      };
}

class ReviewBatchResultItem {
  const ReviewBatchResultItem({
    required this.questionId,
    required this.status,
    this.state,
    this.error,
  });

  final String questionId;
  final String status;
  final QuestionReviewState? state;
  final ReviewBatchError? error;

  factory ReviewBatchResultItem.fromJson(Map<String, dynamic> json) => ReviewBatchResultItem(
        questionId: json['question_id'] as String,
        status: json['status'] as String,
        state: json['state'] == null ? null : QuestionReviewState.fromJson(json['state'] as Map<String, dynamic>),
        error: json['error'] == null ? null : ReviewBatchError.fromJson(json['error'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'question_id': questionId,
        'status': status,
        'state': state?.toJson(),
        'error': error?.toJson(),
      };
}

class ReviewBatchResult {
  const ReviewBatchResult({
    required this.items,
  });

  final List<ReviewBatchResultItem> items;

  factory ReviewBatchResult.fromJson(Map<String, dynamic> json) => ReviewBatchResult(
        items: (json['items'] as List<dynamic>).map((e) => ReviewBatchResultItem.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class ReviewDecision {
  const ReviewDecision({
    required this.expectedReviewRevision,
    required this.decision,
    required this.expectedVersion,
    this.comment,
    this.solutionKinds,
  });

  final int expectedReviewRevision;
  final ReviewDecisionType decision;
  final int expectedVersion;
  final String? comment;
  final List<SolutionKind>? solutionKinds;

  factory ReviewDecision.fromJson(Map<String, dynamic> json) => ReviewDecision(
        expectedReviewRevision: (json['expected_review_revision'] as num).toInt(),
        decision: ReviewDecisionType.fromJson(json['decision'] as String),
        expectedVersion: (json['expected_version'] as num).toInt(),
        comment: json['comment'] == null ? null : json['comment'] as String,
        solutionKinds: json['solution_kinds'] == null ? null : (json['solution_kinds'] as List<dynamic>).map((e) => SolutionKind.fromJson(e as String)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'expected_review_revision': expectedReviewRevision,
        'decision': decision.toJson(),
        'expected_version': expectedVersion,
        if (comment != null) 'comment': comment,
        if (solutionKinds != null) 'solution_kinds': solutionKinds?.map((e) => e.toJson()).toList(),
      };
}

class QuestionReviewState {
  const QuestionReviewState({
    this.reviewRevision,
    required this.questionId,
    required this.status,
    required this.version,
    this.reviewedBy,
    required this.updatedAt,
  });

  final int? reviewRevision;
  final String questionId;
  final QuestionStatus status;
  final int version;
  final String? reviewedBy;
  final DateTime updatedAt;

  factory QuestionReviewState.fromJson(Map<String, dynamic> json) => QuestionReviewState(
        reviewRevision: json['review_revision'] == null ? null : (json['review_revision'] as num).toInt(),
        questionId: json['question_id'] as String,
        status: QuestionStatus.fromJson(json['status'] as String),
        version: (json['version'] as num).toInt(),
        reviewedBy: json['reviewed_by'] == null ? null : json['reviewed_by'] as String,
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        if (reviewRevision != null) 'review_revision': reviewRevision,
        'question_id': questionId,
        'status': status.toJson(),
        'version': version,
        'reviewed_by': reviewedBy,
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class AdminQuestionSummary {
  const AdminQuestionSummary({
    this.reviewRevision,
    required this.id,
    required this.subject,
    required this.type,
    required this.answerMode,
    required this.difficulty,
    required this.title,
    required this.status,
    required this.version,
    required this.source,
    this.createdBy,
    this.reviewedBy,
    this.publishedAt,
    required this.updatedAt,
  });

  final int? reviewRevision;
  final String id;
  final Subject subject;
  final QuestionType type;
  final AnswerMode answerMode;
  final int difficulty;
  final String title;
  final QuestionStatus status;
  final int version;
  final QuestionSource source;
  final String? createdBy;
  final String? reviewedBy;
  final DateTime? publishedAt;
  final DateTime updatedAt;

  factory AdminQuestionSummary.fromJson(Map<String, dynamic> json) => AdminQuestionSummary(
        reviewRevision: json['review_revision'] == null ? null : (json['review_revision'] as num).toInt(),
        id: json['id'] as String,
        subject: Subject.fromJson(json['subject'] as String),
        type: QuestionType.fromJson(json['type'] as String),
        answerMode: AnswerMode.fromJson(json['answer_mode'] as String),
        difficulty: (json['difficulty'] as num).toInt(),
        title: json['title'] as String,
        status: QuestionStatus.fromJson(json['status'] as String),
        version: (json['version'] as num).toInt(),
        source: QuestionSource.fromJson(json['source'] as Map<String, dynamic>),
        createdBy: json['created_by'] == null ? null : json['created_by'] as String,
        reviewedBy: json['reviewed_by'] == null ? null : json['reviewed_by'] as String,
        publishedAt: json['published_at'] == null ? null : DateTime.parse(json['published_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        if (reviewRevision != null) 'review_revision': reviewRevision,
        'id': id,
        'subject': subject.toJson(),
        'type': type.toJson(),
        'answer_mode': answerMode.toJson(),
        'difficulty': difficulty,
        'title': title,
        'status': status.toJson(),
        'version': version,
        'source': source.toJson(),
        'created_by': createdBy,
        'reviewed_by': reviewedBy,
        'published_at': publishedAt?.toUtc().toIso8601String(),
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class AdminStatusCounts {
  const AdminStatusCounts({
    required this.draft,
    required this.reviewed,
    required this.published,
    required this.withdrawn,
  });

  final int draft;
  final int reviewed;
  final int published;
  final int withdrawn;

  factory AdminStatusCounts.fromJson(Map<String, dynamic> json) => AdminStatusCounts(
        draft: (json['draft'] as num).toInt(),
        reviewed: (json['reviewed'] as num).toInt(),
        published: (json['published'] as num).toInt(),
        withdrawn: (json['withdrawn'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'draft': draft,
        'reviewed': reviewed,
        'published': published,
        'withdrawn': withdrawn,
      };
}

class AdminQuestionPage {
  const AdminQuestionPage({
    required this.items,
    this.nextCursor,
    required this.statusCounts,
  });

  final List<AdminQuestionSummary> items;
  final String? nextCursor;
  final AdminStatusCounts statusCounts;

  factory AdminQuestionPage.fromJson(Map<String, dynamic> json) => AdminQuestionPage(
        items: (json['items'] as List<dynamic>).map((e) => AdminQuestionSummary.fromJson(e as Map<String, dynamic>)).toList(),
        nextCursor: json['next_cursor'] == null ? null : json['next_cursor'] as String,
        statusCounts: AdminStatusCounts.fromJson(json['status_counts'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
        'next_cursor': nextCursor,
        'status_counts': statusCounts.toJson(),
      };
}

class AdminAnswer {
  const AdminAnswer({
    this.value,
    required this.equivalenceRules,
    required this.units,
  });

  final dynamic value;
  final Map<String, dynamic> equivalenceRules;
  final Map<String, dynamic> units;

  factory AdminAnswer.fromJson(Map<String, dynamic> json) => AdminAnswer(
        value: json['value'],
        equivalenceRules: Map<String, dynamic>.from(json['equivalence_rules'] as Map),
        units: Map<String, dynamic>.from(json['units'] as Map),
      );

  Map<String, dynamic> toJson() => {
        'value': value,
        'equivalence_rules': equivalenceRules,
        'units': units,
      };
}

class AdminVisual {
  const AdminVisual({
    required this.templateId,
    required this.params,
    required this.caption,
  });

  final String templateId;
  final Map<String, double> params;
  final String caption;

  factory AdminVisual.fromJson(Map<String, dynamic> json) => AdminVisual(
        templateId: json['template_id'] as String,
        params: (json['params'] as Map).map((k, e) => MapEntry(k as String, (e as num).toDouble())),
        caption: json['caption'] as String,
      );

  Map<String, dynamic> toJson() => {
        'template_id': templateId,
        'params': params,
        'caption': caption,
      };
}

class AdminTeaching {
  const AdminTeaching({
    this.referenceLinks,
    this.concept,
    required this.hints,
    this.conceptRephrase,
    required this.optionAnalysis,
    this.visual,
    required this.leakMarkers,
  });

  final List<TeachingReferenceLink>? referenceLinks;
  final String? concept;
  final List<String> hints;
  final String? conceptRephrase;
  final Map<String, dynamic> optionAnalysis;
  final AdminVisual? visual;
  final List<String> leakMarkers;

  factory AdminTeaching.fromJson(Map<String, dynamic> json) => AdminTeaching(
        referenceLinks: json['reference_links'] == null ? null : (json['reference_links'] as List<dynamic>).map((e) => TeachingReferenceLink.fromJson(e as Map<String, dynamic>)).toList(),
        concept: json['concept'] == null ? null : json['concept'] as String,
        hints: (json['hints'] as List<dynamic>).map((e) => e as String).toList(),
        conceptRephrase: json['concept_rephrase'] == null ? null : json['concept_rephrase'] as String,
        optionAnalysis: Map<String, dynamic>.from(json['option_analysis'] as Map),
        visual: json['visual'] == null ? null : AdminVisual.fromJson(json['visual'] as Map<String, dynamic>),
        leakMarkers: (json['leak_markers'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        if (referenceLinks != null) 'reference_links': referenceLinks?.map((e) => e.toJson()).toList(),
        'concept': concept,
        'hints': hints,
        'concept_rephrase': conceptRephrase,
        'option_analysis': optionAnalysis,
        'visual': visual?.toJson(),
        'leak_markers': leakMarkers,
      };
}

class AdminSolution {
  const AdminSolution({
    required this.kind,
    required this.steps,
    required this.finalAnswer,
    required this.keyPoints,
    this.conditions,
    this.boundary,
    required this.reviewed,
    this.reviewedBy,
  });

  final SolutionKind kind;
  final List<String> steps;
  final String finalAnswer;
  final List<String> keyPoints;
  final List<String>? conditions;
  final String? boundary;
  final bool reviewed;
  final String? reviewedBy;

  factory AdminSolution.fromJson(Map<String, dynamic> json) => AdminSolution(
        kind: SolutionKind.fromJson(json['kind'] as String),
        steps: (json['steps'] as List<dynamic>).map((e) => e as String).toList(),
        finalAnswer: json['final_answer'] as String,
        keyPoints: (json['key_points'] as List<dynamic>).map((e) => e as String).toList(),
        conditions: json['conditions'] == null ? null : (json['conditions'] as List<dynamic>).map((e) => e as String).toList(),
        boundary: json['boundary'] == null ? null : json['boundary'] as String,
        reviewed: json['reviewed'] as bool,
        reviewedBy: json['reviewed_by'] == null ? null : json['reviewed_by'] as String,
      );

  Map<String, dynamic> toJson() => {
        'kind': kind.toJson(),
        'steps': steps,
        'final_answer': finalAnswer,
        'key_points': keyPoints,
        'conditions': conditions,
        'boundary': boundary,
        'reviewed': reviewed,
        'reviewed_by': reviewedBy,
      };
}

class AdminRegionTag {
  const AdminRegionTag({
    required this.recommendedRegionCode,
    this.originRegionCode,
    this.examYearFrom,
    this.examYearTo,
    required this.reviewStatus,
    this.note,
  });

  final String recommendedRegionCode;
  final String? originRegionCode;
  final int? examYearFrom;
  final int? examYearTo;
  final String reviewStatus;
  final String? note;

  factory AdminRegionTag.fromJson(Map<String, dynamic> json) => AdminRegionTag(
        recommendedRegionCode: json['recommended_region_code'] as String,
        originRegionCode: json['origin_region_code'] == null ? null : json['origin_region_code'] as String,
        examYearFrom: json['exam_year_from'] == null ? null : (json['exam_year_from'] as num).toInt(),
        examYearTo: json['exam_year_to'] == null ? null : (json['exam_year_to'] as num).toInt(),
        reviewStatus: json['review_status'] as String,
        note: json['note'] == null ? null : json['note'] as String,
      );

  Map<String, dynamic> toJson() => {
        'recommended_region_code': recommendedRegionCode,
        'origin_region_code': originRegionCode,
        'exam_year_from': examYearFrom,
        'exam_year_to': examYearTo,
        'review_status': reviewStatus,
        'note': note,
      };
}

class AdminQuestionVersion {
  const AdminQuestionVersion({
    required this.version,
    this.createdBy,
    required this.createdAt,
  });

  final int version;
  final String? createdBy;
  final DateTime createdAt;

  factory AdminQuestionVersion.fromJson(Map<String, dynamic> json) => AdminQuestionVersion(
        version: (json['version'] as num).toInt(),
        createdBy: json['created_by'] == null ? null : json['created_by'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'version': version,
        'created_by': createdBy,
        'created_at': createdAt.toUtc().toIso8601String(),
      };
}

/// 审核决策，或者 edit（修改内容、产生新版本）。
enum AdminHistoryAction {
  approve('approve'),
  reject('reject'),
  publish('publish'),
  withdraw('withdraw'),
  edit('edit'),
  import$('import'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const AdminHistoryAction(this.value);
  final String value;

  static AdminHistoryAction fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => AdminHistoryAction.$unknown);

  String toJson() => value;
}

class AdminHistoryEntry {
  const AdminHistoryEntry({
    required this.id,
    required this.action,
    this.actorId,
    this.changes,
    this.fromStatus,
    this.toStatus,
    this.version,
    this.comment,
    required this.createdAt,
  });

  final String id;
  final AdminHistoryAction action;
  final String? actorId;
  final List<String>? changes;
  final QuestionStatus? fromStatus;
  final QuestionStatus? toStatus;
  final int? version;
  final String? comment;
  final DateTime createdAt;

  factory AdminHistoryEntry.fromJson(Map<String, dynamic> json) => AdminHistoryEntry(
        id: json['id'] as String,
        action: AdminHistoryAction.fromJson(json['action'] as String),
        actorId: json['actor_id'] == null ? null : json['actor_id'] as String,
        changes: json['changes'] == null ? null : (json['changes'] as List<dynamic>).map((e) => e as String).toList(),
        fromStatus: json['from_status'] == null ? null : QuestionStatus.fromJson(json['from_status'] as String),
        toStatus: json['to_status'] == null ? null : QuestionStatus.fromJson(json['to_status'] as String),
        version: json['version'] == null ? null : (json['version'] as num).toInt(),
        comment: json['comment'] == null ? null : json['comment'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'action': action.toJson(),
        'actor_id': actorId,
        'changes': changes,
        'from_status': fromStatus?.toJson(),
        'to_status': toStatus?.toJson(),
        'version': version,
        'comment': comment,
        'created_at': createdAt.toUtc().toIso8601String(),
      };
}

class AdminSolutionInput {
  const AdminSolutionInput({
    required this.kind,
    required this.steps,
    required this.finalAnswer,
    required this.keyPoints,
    this.conditions,
    this.boundary,
  });

  final SolutionKind kind;
  final List<String> steps;
  final String finalAnswer;
  final List<String> keyPoints;
  final List<String>? conditions;
  final String? boundary;

  factory AdminSolutionInput.fromJson(Map<String, dynamic> json) => AdminSolutionInput(
        kind: SolutionKind.fromJson(json['kind'] as String),
        steps: (json['steps'] as List<dynamic>).map((e) => e as String).toList(),
        finalAnswer: json['final_answer'] as String,
        keyPoints: (json['key_points'] as List<dynamic>).map((e) => e as String).toList(),
        conditions: json['conditions'] == null ? null : (json['conditions'] as List<dynamic>).map((e) => e as String).toList(),
        boundary: json['boundary'] == null ? null : json['boundary'] as String,
      );

  Map<String, dynamic> toJson() => {
        'kind': kind.toJson(),
        'steps': steps,
        'final_answer': finalAnswer,
        'key_points': keyPoints,
        'conditions': conditions,
        'boundary': boundary,
      };
}

/// 可编辑内容的完整替换（不是补丁）：没打算改的部分原样传回。题型、学科、答题方式、来源和地区标记不在这里改。
class AdminQuestionEdit {
  const AdminQuestionEdit({
    required this.expectedReviewRevision,
    required this.expectedVersion,
    required this.title,
    required this.difficulty,
    this.grade,
    required this.content,
    required this.answer,
    required this.teaching,
    required this.solutions,
    required this.knowledge,
    required this.rubric,
    this.comment,
  });

  final int expectedReviewRevision;
  final int expectedVersion;
  final String title;
  final int difficulty;
  final Grade? grade;
  final QuestionContent content;
  final AdminAnswer answer;
  final AdminTeaching teaching;
  final List<AdminSolutionInput> solutions;
  final List<String> knowledge;
  final Map<String, dynamic> rubric;
  final String? comment;

  factory AdminQuestionEdit.fromJson(Map<String, dynamic> json) => AdminQuestionEdit(
        expectedReviewRevision: (json['expected_review_revision'] as num).toInt(),
        expectedVersion: (json['expected_version'] as num).toInt(),
        title: json['title'] as String,
        difficulty: (json['difficulty'] as num).toInt(),
        grade: json['grade'] == null ? null : Grade.fromJson(json['grade'] as String),
        content: QuestionContent.fromJson(json['content'] as Map<String, dynamic>),
        answer: AdminAnswer.fromJson(json['answer'] as Map<String, dynamic>),
        teaching: AdminTeaching.fromJson(json['teaching'] as Map<String, dynamic>),
        solutions: (json['solutions'] as List<dynamic>).map((e) => AdminSolutionInput.fromJson(e as Map<String, dynamic>)).toList(),
        knowledge: (json['knowledge'] as List<dynamic>).map((e) => e as String).toList(),
        rubric: Map<String, dynamic>.from(json['rubric'] as Map),
        comment: json['comment'] == null ? null : json['comment'] as String,
      );

  Map<String, dynamic> toJson() => {
        'expected_review_revision': expectedReviewRevision,
        'expected_version': expectedVersion,
        'title': title,
        'difficulty': difficulty,
        'grade': grade?.toJson(),
        'content': content.toJson(),
        'answer': answer.toJson(),
        'teaching': teaching.toJson(),
        'solutions': solutions.map((e) => e.toJson()).toList(),
        'knowledge': knowledge,
        'rubric': rubric,
        if (comment != null) 'comment': comment,
      };
}

/// 单题草稿内容；不含审核状态、提交者和版本号。
class AdminQuestionDraft {
  const AdminQuestionDraft({
    required this.title,
    required this.difficulty,
    this.grade,
    required this.content,
    required this.answer,
    required this.teaching,
    required this.solutions,
    required this.knowledge,
    required this.rubric,
    this.comment,
  });

  final String title;
  final int difficulty;
  final Grade? grade;
  final QuestionContent content;
  final AdminAnswer answer;
  final AdminTeaching teaching;
  final List<AdminSolutionInput> solutions;
  final List<String> knowledge;
  final Map<String, dynamic> rubric;
  final String? comment;

  factory AdminQuestionDraft.fromJson(Map<String, dynamic> json) => AdminQuestionDraft(
        title: json['title'] as String,
        difficulty: (json['difficulty'] as num).toInt(),
        grade: json['grade'] == null ? null : Grade.fromJson(json['grade'] as String),
        content: QuestionContent.fromJson(json['content'] as Map<String, dynamic>),
        answer: AdminAnswer.fromJson(json['answer'] as Map<String, dynamic>),
        teaching: AdminTeaching.fromJson(json['teaching'] as Map<String, dynamic>),
        solutions: (json['solutions'] as List<dynamic>).map((e) => AdminSolutionInput.fromJson(e as Map<String, dynamic>)).toList(),
        knowledge: (json['knowledge'] as List<dynamic>).map((e) => e as String).toList(),
        rubric: Map<String, dynamic>.from(json['rubric'] as Map),
        comment: json['comment'] == null ? null : json['comment'] as String,
      );

  Map<String, dynamic> toJson() => {
        'title': title,
        'difficulty': difficulty,
        'grade': grade?.toJson(),
        'content': content.toJson(),
        'answer': answer.toJson(),
        'teaching': teaching.toJson(),
        'solutions': solutions.map((e) => e.toJson()).toList(),
        'knowledge': knowledge,
        'rubric': rubric,
        if (comment != null) 'comment': comment,
      };
}

class AdminImportSource {
  const AdminImportSource({
    required this.sourceType,
    required this.sourceCategory,
    required this.sourceName,
    this.sourceYear,
    required this.sourceLicense,
    this.sourceUrl,
  });

  final String sourceType;
  final SourceCategory sourceCategory;
  final String sourceName;
  final int? sourceYear;
  final String sourceLicense;
  final String? sourceUrl;

  factory AdminImportSource.fromJson(Map<String, dynamic> json) => AdminImportSource(
        sourceType: json['source_type'] as String,
        sourceCategory: SourceCategory.fromJson(json['source_category'] as String),
        sourceName: json['source_name'] as String,
        sourceYear: json['source_year'] == null ? null : (json['source_year'] as num).toInt(),
        sourceLicense: json['source_license'] as String,
        sourceUrl: json['source_url'] == null ? null : json['source_url'] as String,
      );

  Map<String, dynamic> toJson() => {
        'source_type': sourceType,
        'source_category': sourceCategory.toJson(),
        'source_name': sourceName,
        'source_year': sourceYear,
        'source_license': sourceLicense,
        'source_url': sourceUrl,
      };
}

enum DocImportJobStatus {
  uploading('uploading'),
  queued('queued'),
  processing('processing'),
  needsReview('needs_review'),
  completed('completed'),
  partialFailure('partial_failure'),
  failed('failed'),
  cancelled('cancelled'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const DocImportJobStatus(this.value);
  final String value;

  static DocImportJobStatus fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => DocImportJobStatus.$unknown);

  String toJson() => value;
}

enum DocImportFileStatus {
  pending('pending'),
  processing('processing'),
  ready('ready'),
  needsOcr('needs_ocr'),
  failed('failed'),
  cancelled('cancelled'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const DocImportFileStatus(this.value);
  final String value;

  static DocImportFileStatus fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => DocImportFileStatus.$unknown);

  String toJson() => value;
}

enum DocImportFileKind {
  pdf('pdf'),
  docx('docx'),
  doc('doc'),
  png('png'),
  jpeg('jpeg'),
  json('json'),

  /// 契约里新增、而这个版本的客户端还不认识的值。
  $unknown('');

  const DocImportFileKind(this.value);
  final String value;

  static DocImportFileKind fromJson(String value) =>
      values.firstWhere((e) => e.value == value, orElse: () => DocImportFileKind.$unknown);

  String toJson() => value;
}

class DocImportOptions {
  const DocImportOptions({
    required this.serverTime,
    required this.creationDeadline,
    required this.maxFileBytes,
    required this.maxJobBytes,
    required this.maxFiles,
    required this.maxPages,
    required this.maxCandidates,
    required this.temporaryTtlMinutes,
    required this.fileKinds,
    required this.ocrMode,
    required this.docConverterAvailable,
  });

  final DateTime serverTime;
  final DateTime creationDeadline;
  final int maxFileBytes;
  final int maxJobBytes;
  final int maxFiles;
  final int maxPages;
  final int maxCandidates;
  final int temporaryTtlMinutes;
  final List<DocImportFileKind> fileKinds;
  final String ocrMode;
  final bool docConverterAvailable;

  factory DocImportOptions.fromJson(Map<String, dynamic> json) => DocImportOptions(
        serverTime: DateTime.parse(json['server_time'] as String),
        creationDeadline: DateTime.parse(json['creation_deadline'] as String),
        maxFileBytes: (json['max_file_bytes'] as num).toInt(),
        maxJobBytes: (json['max_job_bytes'] as num).toInt(),
        maxFiles: (json['max_files'] as num).toInt(),
        maxPages: (json['max_pages'] as num).toInt(),
        maxCandidates: (json['max_candidates'] as num).toInt(),
        temporaryTtlMinutes: (json['temporary_ttl_minutes'] as num).toInt(),
        fileKinds: (json['file_kinds'] as List<dynamic>).map((e) => DocImportFileKind.fromJson(e as String)).toList(),
        ocrMode: json['ocr_mode'] as String,
        docConverterAvailable: json['doc_converter_available'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'server_time': serverTime.toUtc().toIso8601String(),
        'creation_deadline': creationDeadline.toUtc().toIso8601String(),
        'max_file_bytes': maxFileBytes,
        'max_job_bytes': maxJobBytes,
        'max_files': maxFiles,
        'max_pages': maxPages,
        'max_candidates': maxCandidates,
        'temporary_ttl_minutes': temporaryTtlMinutes,
        'file_kinds': fileKinds.map((e) => e.toJson()).toList(),
        'ocr_mode': ocrMode,
        'doc_converter_available': docConverterAvailable,
      };
}

class DocImportDefaults {
  const DocImportDefaults({
    required this.subject,
    required this.answerMode,
    required this.source,
  });

  final Subject subject;
  final AnswerMode answerMode;
  final AdminImportSource source;

  factory DocImportDefaults.fromJson(Map<String, dynamic> json) => DocImportDefaults(
        subject: Subject.fromJson(json['subject'] as String),
        answerMode: AnswerMode.fromJson(json['answer_mode'] as String),
        source: AdminImportSource.fromJson(json['source'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'subject': subject.toJson(),
        'answer_mode': answerMode.toJson(),
        'source': source.toJson(),
      };
}

class DocImportJobCreate {
  const DocImportJobCreate({
    required this.creationDeadline,
    required this.title,
    required this.defaults,
  });

  final DateTime creationDeadline;
  final String title;
  final DocImportDefaults defaults;

  factory DocImportJobCreate.fromJson(Map<String, dynamic> json) => DocImportJobCreate(
        creationDeadline: DateTime.parse(json['creation_deadline'] as String),
        title: json['title'] as String,
        defaults: DocImportDefaults.fromJson(json['defaults'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'creation_deadline': creationDeadline.toUtc().toIso8601String(),
        'title': title,
        'defaults': defaults.toJson(),
      };
}

class DocImportJobSummary {
  const DocImportJobSummary({
    required this.id,
    required this.title,
    required this.status,
    required this.revision,
    required this.fileCount,
    required this.processedFiles,
    required this.candidateCount,
    required this.confirmedCount,
    required this.importedCount,
    required this.failedCount,
    this.message,
    required this.createdAt,
    required this.updatedAt,
    required this.expiresAt,
  });

  final String id;
  final String title;
  final DocImportJobStatus status;
  final int revision;
  final int fileCount;
  final int processedFiles;
  final int candidateCount;
  final int confirmedCount;
  final int importedCount;
  final int failedCount;
  final String? message;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime expiresAt;

  factory DocImportJobSummary.fromJson(Map<String, dynamic> json) => DocImportJobSummary(
        id: json['id'] as String,
        title: json['title'] as String,
        status: DocImportJobStatus.fromJson(json['status'] as String),
        revision: (json['revision'] as num).toInt(),
        fileCount: (json['file_count'] as num).toInt(),
        processedFiles: (json['processed_files'] as num).toInt(),
        candidateCount: (json['candidate_count'] as num).toInt(),
        confirmedCount: (json['confirmed_count'] as num).toInt(),
        importedCount: (json['imported_count'] as num).toInt(),
        failedCount: (json['failed_count'] as num).toInt(),
        message: json['message'] == null ? null : json['message'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
        expiresAt: DateTime.parse(json['expires_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'status': status.toJson(),
        'revision': revision,
        'file_count': fileCount,
        'processed_files': processedFiles,
        'candidate_count': candidateCount,
        'confirmed_count': confirmedCount,
        'imported_count': importedCount,
        'failed_count': failedCount,
        'message': message,
        'created_at': createdAt.toUtc().toIso8601String(),
        'updated_at': updatedAt.toUtc().toIso8601String(),
        'expires_at': expiresAt.toUtc().toIso8601String(),
      };
}

class DocImportPage {
  const DocImportPage({
    required this.number,
    required this.text,
    required this.method,
    required this.warnings,
    this.confidence,
    required this.mediaRefs,
  });

  final int number;
  final String text;
  final String method;
  final List<String> warnings;
  final double? confidence;
  final List<String> mediaRefs;

  factory DocImportPage.fromJson(Map<String, dynamic> json) => DocImportPage(
        number: (json['number'] as num).toInt(),
        text: json['text'] as String,
        method: json['method'] as String,
        warnings: (json['warnings'] as List<dynamic>).map((e) => e as String).toList(),
        confidence: json['confidence'] == null ? null : (json['confidence'] as num).toDouble(),
        mediaRefs: (json['media_refs'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        'number': number,
        'text': text,
        'method': method,
        'warnings': warnings,
        'confidence': confidence,
        'media_refs': mediaRefs,
      };
}

class DocImportFile {
  const DocImportFile({
    required this.id,
    required this.filename,
    required this.kind,
    required this.mediaType,
    required this.sizeBytes,
    required this.sha256,
    required this.status,
    required this.problems,
    required this.pages,
    required this.originalAvailable,
  });

  final String id;
  final String filename;
  final DocImportFileKind kind;
  final String mediaType;
  final int sizeBytes;
  final String sha256;
  final DocImportFileStatus status;
  final List<String> problems;
  final List<DocImportPage> pages;
  final bool originalAvailable;

  factory DocImportFile.fromJson(Map<String, dynamic> json) => DocImportFile(
        id: json['id'] as String,
        filename: json['filename'] as String,
        kind: DocImportFileKind.fromJson(json['kind'] as String),
        mediaType: json['media_type'] as String,
        sizeBytes: (json['size_bytes'] as num).toInt(),
        sha256: json['sha256'] as String,
        status: DocImportFileStatus.fromJson(json['status'] as String),
        problems: (json['problems'] as List<dynamic>).map((e) => e as String).toList(),
        pages: (json['pages'] as List<dynamic>).map((e) => DocImportPage.fromJson(e as Map<String, dynamic>)).toList(),
        originalAvailable: json['original_available'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'filename': filename,
        'kind': kind.toJson(),
        'media_type': mediaType,
        'size_bytes': sizeBytes,
        'sha256': sha256,
        'status': status.toJson(),
        'problems': problems,
        'pages': pages.map((e) => e.toJson()).toList(),
        'original_available': originalAvailable,
      };
}

class DocImportLocation {
  const DocImportLocation({
    required this.fileId,
    required this.page,
    this.block,
  });

  final String fileId;
  final int page;
  final int? block;

  factory DocImportLocation.fromJson(Map<String, dynamic> json) => DocImportLocation(
        fileId: json['file_id'] as String,
        page: (json['page'] as num).toInt(),
        block: json['block'] == null ? null : (json['block'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'file_id': fileId,
        'page': page,
        'block': block,
      };
}

class DocImportItemError {
  const DocImportItemError({
    required this.code,
    required this.message,
  });

  final String code;
  final String message;

  factory DocImportItemError.fromJson(Map<String, dynamic> json) => DocImportItemError(
        code: json['code'] as String,
        message: json['message'] as String,
      );

  Map<String, dynamic> toJson() => {
        'code': code,
        'message': message,
      };
}

class DocImportCandidate {
  const DocImportCandidate({
    required this.id,
    required this.title,
    required this.text,
    required this.locations,
    required this.warnings,
    this.payload,
    required this.confirmed,
    this.confirmedBy,
    this.questionId,
    this.error,
  });

  final String id;
  final String title;
  final String text;
  final List<DocImportLocation> locations;
  final List<String> warnings;
  final AdminQuestionImport? payload;
  final bool confirmed;
  final String? confirmedBy;
  final String? questionId;
  final DocImportItemError? error;

  factory DocImportCandidate.fromJson(Map<String, dynamic> json) => DocImportCandidate(
        id: json['id'] as String,
        title: json['title'] as String,
        text: json['text'] as String,
        locations: (json['locations'] as List<dynamic>).map((e) => DocImportLocation.fromJson(e as Map<String, dynamic>)).toList(),
        warnings: (json['warnings'] as List<dynamic>).map((e) => e as String).toList(),
        payload: json['payload'] == null ? null : AdminQuestionImport.fromJson(json['payload'] as Map<String, dynamic>),
        confirmed: json['confirmed'] as bool,
        confirmedBy: json['confirmed_by'] == null ? null : json['confirmed_by'] as String,
        questionId: json['question_id'] == null ? null : json['question_id'] as String,
        error: json['error'] == null ? null : DocImportItemError.fromJson(json['error'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'text': text,
        'locations': locations.map((e) => e.toJson()).toList(),
        'warnings': warnings,
        'payload': payload?.toJson(),
        'confirmed': confirmed,
        'confirmed_by': confirmedBy,
        'question_id': questionId,
        'error': error?.toJson(),
      };
}

class DocImportCandidateInput {
  const DocImportCandidateInput({
    this.id,
    required this.title,
    required this.text,
    required this.locations,
    this.payload,
    required this.confirmed,
  });

  final String? id;
  final String title;
  final String text;
  final List<DocImportLocation> locations;
  final AdminQuestionImport? payload;
  final bool confirmed;

  factory DocImportCandidateInput.fromJson(Map<String, dynamic> json) => DocImportCandidateInput(
        id: json['id'] == null ? null : json['id'] as String,
        title: json['title'] as String,
        text: json['text'] as String,
        locations: (json['locations'] as List<dynamic>).map((e) => DocImportLocation.fromJson(e as Map<String, dynamic>)).toList(),
        payload: json['payload'] == null ? null : AdminQuestionImport.fromJson(json['payload'] as Map<String, dynamic>),
        confirmed: json['confirmed'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'text': text,
        'locations': locations.map((e) => e.toJson()).toList(),
        'payload': payload?.toJson(),
        'confirmed': confirmed,
      };
}

class DocImportJobDetail {
  const DocImportJobDetail({
    required this.job,
    required this.defaults,
    required this.files,
    required this.candidates,
  });

  final DocImportJobSummary job;
  final DocImportDefaults defaults;
  final List<DocImportFile> files;
  final List<DocImportCandidate> candidates;

  factory DocImportJobDetail.fromJson(Map<String, dynamic> json) => DocImportJobDetail(
        job: DocImportJobSummary.fromJson(json['job'] as Map<String, dynamic>),
        defaults: DocImportDefaults.fromJson(json['defaults'] as Map<String, dynamic>),
        files: (json['files'] as List<dynamic>).map((e) => DocImportFile.fromJson(e as Map<String, dynamic>)).toList(),
        candidates: (json['candidates'] as List<dynamic>).map((e) => DocImportCandidate.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'job': job.toJson(),
        'defaults': defaults.toJson(),
        'files': files.map((e) => e.toJson()).toList(),
        'candidates': candidates.map((e) => e.toJson()).toList(),
      };
}

class DocImportJobPage {
  const DocImportJobPage({
    required this.items,
    this.nextCursor,
  });

  final List<DocImportJobSummary> items;
  final String? nextCursor;

  factory DocImportJobPage.fromJson(Map<String, dynamic> json) => DocImportJobPage(
        items: (json['items'] as List<dynamic>).map((e) => DocImportJobSummary.fromJson(e as Map<String, dynamic>)).toList(),
        nextCursor: json['next_cursor'] == null ? null : json['next_cursor'] as String,
      );

  Map<String, dynamic> toJson() => {
        'items': items.map((e) => e.toJson()).toList(),
        'next_cursor': nextCursor,
      };
}

class DocImportRevision {
  const DocImportRevision({
    required this.expectedRevision,
  });

  final int expectedRevision;

  factory DocImportRevision.fromJson(Map<String, dynamic> json) => DocImportRevision(
        expectedRevision: (json['expected_revision'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'expected_revision': expectedRevision,
      };
}

/// 本地原型通过有界 Base64 JSON 上传单个文件，多文件逐个提交；文件名只作显示，不作为存储路径。
class DocImportUpload {
  const DocImportUpload({
    required this.expectedRevision,
    required this.filename,
    required this.contentBase64,
  });

  final int expectedRevision;
  final String filename;
  final String contentBase64;

  factory DocImportUpload.fromJson(Map<String, dynamic> json) => DocImportUpload(
        expectedRevision: (json['expected_revision'] as num).toInt(),
        filename: json['filename'] as String,
        contentBase64: json['content_base64'] as String,
      );

  Map<String, dynamic> toJson() => {
        'expected_revision': expectedRevision,
        'filename': filename,
        'content_base64': contentBase64,
      };
}

class DocImportUploadResult {
  const DocImportUploadResult({
    required this.job,
    required this.file,
  });

  final DocImportJobSummary job;
  final DocImportFile file;

  factory DocImportUploadResult.fromJson(Map<String, dynamic> json) => DocImportUploadResult(
        job: DocImportJobSummary.fromJson(json['job'] as Map<String, dynamic>),
        file: DocImportFile.fromJson(json['file'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'job': job.toJson(),
        'file': file.toJson(),
      };
}

class DocImportContent {
  const DocImportContent({
    required this.filename,
    required this.mediaType,
    required this.contentBase64,
  });

  final String filename;
  final String mediaType;
  final String contentBase64;

  factory DocImportContent.fromJson(Map<String, dynamic> json) => DocImportContent(
        filename: json['filename'] as String,
        mediaType: json['media_type'] as String,
        contentBase64: json['content_base64'] as String,
      );

  Map<String, dynamic> toJson() => {
        'filename': filename,
        'media_type': mediaType,
        'content_base64': contentBase64,
      };
}

/// 整体替换候选题工作区，支持人工拆分、合并与排序；新项 id=null；已导入项不可改写或删除。确认来自当前 token。
class DocImportCandidatesEdit {
  const DocImportCandidatesEdit({
    required this.expectedRevision,
    required this.items,
  });

  final int expectedRevision;
  final List<DocImportCandidateInput> items;

  factory DocImportCandidatesEdit.fromJson(Map<String, dynamic> json) => DocImportCandidatesEdit(
        expectedRevision: (json['expected_revision'] as num).toInt(),
        items: (json['items'] as List<dynamic>).map((e) => DocImportCandidateInput.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'expected_revision': expectedRevision,
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class DocImportSubmit {
  const DocImportSubmit({
    required this.expectedRevision,
    required this.candidateIds,
  });

  final int expectedRevision;
  final List<String> candidateIds;

  factory DocImportSubmit.fromJson(Map<String, dynamic> json) => DocImportSubmit(
        expectedRevision: (json['expected_revision'] as num).toInt(),
        candidateIds: (json['candidate_ids'] as List<dynamic>).map((e) => e as String).toList(),
      );

  Map<String, dynamic> toJson() => {
        'expected_revision': expectedRevision,
        'candidate_ids': candidateIds,
      };
}

class DocImportBatchItem {
  const DocImportBatchItem({
    required this.candidateId,
    this.questionId,
    required this.status,
    this.error,
  });

  final String candidateId;
  final String? questionId;
  final String status;
  final DocImportItemError? error;

  factory DocImportBatchItem.fromJson(Map<String, dynamic> json) => DocImportBatchItem(
        candidateId: json['candidate_id'] as String,
        questionId: json['question_id'] == null ? null : json['question_id'] as String,
        status: json['status'] as String,
        error: json['error'] == null ? null : DocImportItemError.fromJson(json['error'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'candidate_id': candidateId,
        'question_id': questionId,
        'status': status,
        'error': error?.toJson(),
      };
}

class DocImportBatchResult {
  const DocImportBatchResult({
    required this.job,
    required this.items,
  });

  final DocImportJobSummary job;
  final List<DocImportBatchItem> items;

  factory DocImportBatchResult.fromJson(Map<String, dynamic> json) => DocImportBatchResult(
        job: DocImportJobSummary.fromJson(json['job'] as Map<String, dynamic>),
        items: (json['items'] as List<dynamic>).map((e) => DocImportBatchItem.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'job': job.toJson(),
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class AdminQuestionImport {
  const AdminQuestionImport({
    required this.subject,
    required this.answerMode,
    required this.source,
    required this.question,
  });

  final Subject subject;
  final AnswerMode answerMode;
  final AdminImportSource source;
  final AdminQuestionDraft question;

  factory AdminQuestionImport.fromJson(Map<String, dynamic> json) => AdminQuestionImport(
        subject: Subject.fromJson(json['subject'] as String),
        answerMode: AnswerMode.fromJson(json['answer_mode'] as String),
        source: AdminImportSource.fromJson(json['source'] as Map<String, dynamic>),
        question: AdminQuestionDraft.fromJson(json['question'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'subject': subject.toJson(),
        'answer_mode': answerMode.toJson(),
        'source': source.toJson(),
        'question': question.toJson(),
      };
}

/// 题目某一个版本里"可以被修改"的全部内容，对比两个版本用。
class AdminVersionSnapshot {
  const AdminVersionSnapshot({
    this.provenance,
    required this.questionId,
    required this.version,
    required this.isCurrent,
    this.createdBy,
    required this.createdAt,
    required this.title,
    required this.difficulty,
    this.grade,
    required this.content,
    required this.answer,
    required this.teaching,
    required this.solutions,
    required this.knowledge,
    required this.rubric,
  });

  final QuestionProvenance? provenance;
  final String questionId;
  final int version;
  final bool isCurrent;
  final String? createdBy;
  final DateTime createdAt;
  final String title;
  final int difficulty;
  final Grade? grade;
  final QuestionContent content;
  final AdminAnswer answer;
  final AdminTeaching teaching;
  final List<AdminSolution> solutions;
  final List<String> knowledge;
  final Map<String, dynamic> rubric;

  factory AdminVersionSnapshot.fromJson(Map<String, dynamic> json) => AdminVersionSnapshot(
        provenance: json['provenance'] == null ? null : QuestionProvenance.fromJson(json['provenance'] as Map<String, dynamic>),
        questionId: json['question_id'] as String,
        version: (json['version'] as num).toInt(),
        isCurrent: json['is_current'] as bool,
        createdBy: json['created_by'] == null ? null : json['created_by'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        title: json['title'] as String,
        difficulty: (json['difficulty'] as num).toInt(),
        grade: json['grade'] == null ? null : Grade.fromJson(json['grade'] as String),
        content: QuestionContent.fromJson(json['content'] as Map<String, dynamic>),
        answer: AdminAnswer.fromJson(json['answer'] as Map<String, dynamic>),
        teaching: AdminTeaching.fromJson(json['teaching'] as Map<String, dynamic>),
        solutions: (json['solutions'] as List<dynamic>).map((e) => AdminSolution.fromJson(e as Map<String, dynamic>)).toList(),
        knowledge: (json['knowledge'] as List<dynamic>).map((e) => e as String).toList(),
        rubric: Map<String, dynamic>.from(json['rubric'] as Map),
      );

  Map<String, dynamic> toJson() => {
        if (provenance != null) 'provenance': provenance?.toJson(),
        'question_id': questionId,
        'version': version,
        'is_current': isCurrent,
        'created_by': createdBy,
        'created_at': createdAt.toUtc().toIso8601String(),
        'title': title,
        'difficulty': difficulty,
        'grade': grade?.toJson(),
        'content': content.toJson(),
        'answer': answer.toJson(),
        'teaching': teaching.toJson(),
        'solutions': solutions.map((e) => e.toJson()).toList(),
        'knowledge': knowledge,
        'rubric': rubric,
      };
}

class AdminQuestionDetail {
  const AdminQuestionDetail({
    this.provenance,
    this.reviewRevision,
    required this.id,
    required this.subject,
    required this.type,
    required this.answerMode,
    required this.difficulty,
    this.grade,
    required this.title,
    required this.status,
    required this.version,
    required this.source,
    this.variantOf,
    this.createdBy,
    this.reviewedBy,
    this.publishedAt,
    required this.updatedAt,
    required this.content,
    required this.answer,
    required this.teaching,
    required this.solutions,
    required this.rubric,
    required this.knowledge,
    required this.regionTags,
    required this.checkProblems,
    required this.versions,
    required this.history,
  });

  final QuestionProvenance? provenance;
  final int? reviewRevision;
  final String id;
  final Subject subject;
  final QuestionType type;
  final AnswerMode answerMode;
  final int difficulty;
  final Grade? grade;
  final String title;
  final QuestionStatus status;
  final int version;
  final QuestionSource source;
  final String? variantOf;
  final String? createdBy;
  final String? reviewedBy;
  final DateTime? publishedAt;
  final DateTime updatedAt;
  final QuestionContent content;
  final AdminAnswer answer;
  final AdminTeaching teaching;
  final List<AdminSolution> solutions;
  final Map<String, dynamic> rubric;
  final List<KnowledgeRef> knowledge;
  final List<AdminRegionTag> regionTags;
  final List<String> checkProblems;
  final List<AdminQuestionVersion> versions;
  final List<AdminHistoryEntry> history;

  factory AdminQuestionDetail.fromJson(Map<String, dynamic> json) => AdminQuestionDetail(
        provenance: json['provenance'] == null ? null : QuestionProvenance.fromJson(json['provenance'] as Map<String, dynamic>),
        reviewRevision: json['review_revision'] == null ? null : (json['review_revision'] as num).toInt(),
        id: json['id'] as String,
        subject: Subject.fromJson(json['subject'] as String),
        type: QuestionType.fromJson(json['type'] as String),
        answerMode: AnswerMode.fromJson(json['answer_mode'] as String),
        difficulty: (json['difficulty'] as num).toInt(),
        grade: json['grade'] == null ? null : Grade.fromJson(json['grade'] as String),
        title: json['title'] as String,
        status: QuestionStatus.fromJson(json['status'] as String),
        version: (json['version'] as num).toInt(),
        source: QuestionSource.fromJson(json['source'] as Map<String, dynamic>),
        variantOf: json['variant_of'] == null ? null : json['variant_of'] as String,
        createdBy: json['created_by'] == null ? null : json['created_by'] as String,
        reviewedBy: json['reviewed_by'] == null ? null : json['reviewed_by'] as String,
        publishedAt: json['published_at'] == null ? null : DateTime.parse(json['published_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
        content: QuestionContent.fromJson(json['content'] as Map<String, dynamic>),
        answer: AdminAnswer.fromJson(json['answer'] as Map<String, dynamic>),
        teaching: AdminTeaching.fromJson(json['teaching'] as Map<String, dynamic>),
        solutions: (json['solutions'] as List<dynamic>).map((e) => AdminSolution.fromJson(e as Map<String, dynamic>)).toList(),
        rubric: Map<String, dynamic>.from(json['rubric'] as Map),
        knowledge: (json['knowledge'] as List<dynamic>).map((e) => KnowledgeRef.fromJson(e as Map<String, dynamic>)).toList(),
        regionTags: (json['region_tags'] as List<dynamic>).map((e) => AdminRegionTag.fromJson(e as Map<String, dynamic>)).toList(),
        checkProblems: (json['check_problems'] as List<dynamic>).map((e) => e as String).toList(),
        versions: (json['versions'] as List<dynamic>).map((e) => AdminQuestionVersion.fromJson(e as Map<String, dynamic>)).toList(),
        history: (json['history'] as List<dynamic>).map((e) => AdminHistoryEntry.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        if (provenance != null) 'provenance': provenance?.toJson(),
        if (reviewRevision != null) 'review_revision': reviewRevision,
        'id': id,
        'subject': subject.toJson(),
        'type': type.toJson(),
        'answer_mode': answerMode.toJson(),
        'difficulty': difficulty,
        'grade': grade?.toJson(),
        'title': title,
        'status': status.toJson(),
        'version': version,
        'source': source.toJson(),
        'variant_of': variantOf,
        'created_by': createdBy,
        'reviewed_by': reviewedBy,
        'published_at': publishedAt?.toUtc().toIso8601String(),
        'updated_at': updatedAt.toUtc().toIso8601String(),
        'content': content.toJson(),
        'answer': answer.toJson(),
        'teaching': teaching.toJson(),
        'solutions': solutions.map((e) => e.toJson()).toList(),
        'rubric': rubric,
        'knowledge': knowledge.map((e) => e.toJson()).toList(),
        'region_tags': regionTags.map((e) => e.toJson()).toList(),
        'check_problems': checkProblems,
        'versions': versions.map((e) => e.toJson()).toList(),
        'history': history.map((e) => e.toJson()).toList(),
      };
}
