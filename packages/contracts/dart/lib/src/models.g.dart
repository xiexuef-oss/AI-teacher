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

/// 作答区的渲染方式。本阶段只实现 single_choice、multiple_choice、fill 的判定。
enum AnswerMode {
  singleChoice('single_choice'),
  multipleChoice('multiple_choice'),
  fill('fill'),
  written('written'),
  experiment('experiment'),

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

class LocalIdentity {
  const LocalIdentity({
    required this.userId,
    required this.role,
    required this.accessToken,
    required this.tokenType,
  });

  final String userId;
  final String role;
  final String accessToken;
  final String tokenType;

  factory LocalIdentity.fromJson(Map<String, dynamic> json) => LocalIdentity(
        userId: json['user_id'] as String,
        role: json['role'] as String,
        accessToken: json['access_token'] as String,
        tokenType: json['token_type'] as String,
      );

  Map<String, dynamic> toJson() => {
        'user_id': userId,
        'role': role,
        'access_token': accessToken,
        'token_type': tokenType,
      };
}

class StudentProfile {
  const StudentProfile({
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
    required this.regionCode,
    required this.subjects,
    this.grade,
    this.examYear,
    this.curriculumVersion,
    this.displayName,
  });

  final RegionCode regionCode;
  final List<Subject> subjects;
  final Grade? grade;
  final int? examYear;
  final String? curriculumVersion;
  final String? displayName;

  factory ProfileUpdate.fromJson(Map<String, dynamic> json) => ProfileUpdate(
        regionCode: RegionCode.fromJson(json['region_code'] as String),
        subjects: (json['subjects'] as List<dynamic>).map((e) => Subject.fromJson(e as String)).toList(),
        grade: json['grade'] == null ? null : Grade.fromJson(json['grade'] as String),
        examYear: json['exam_year'] == null ? null : (json['exam_year'] as num).toInt(),
        curriculumVersion: json['curriculum_version'] == null ? null : json['curriculum_version'] as String,
        displayName: json['display_name'] == null ? null : json['display_name'] as String,
      );

  Map<String, dynamic> toJson() => {
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
    required this.items,
  });

  final String date;
  final List<StudyTask> items;

  factory TodayTasks.fromJson(Map<String, dynamic> json) => TodayTasks(
        date: json['date'] as String,
        items: (json['items'] as List<dynamic>).map((e) => StudyTask.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'date': date,
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

class QuestionContent {
  const QuestionContent({
    required this.stem,
    required this.options,
    required this.blanks,
    required this.subquestions,
    required this.attachments,
  });

  final String stem;
  final List<QuestionOption> options;
  final List<QuestionBlank> blanks;
  final List<Subquestion> subquestions;
  final List<QuestionAttachment> attachments;

  factory QuestionContent.fromJson(Map<String, dynamic> json) => QuestionContent(
        stem: json['stem'] as String,
        options: (json['options'] as List<dynamic>).map((e) => QuestionOption.fromJson(e as Map<String, dynamic>)).toList(),
        blanks: (json['blanks'] as List<dynamic>).map((e) => QuestionBlank.fromJson(e as Map<String, dynamic>)).toList(),
        subquestions: (json['subquestions'] as List<dynamic>).map((e) => Subquestion.fromJson(e as Map<String, dynamic>)).toList(),
        attachments: (json['attachments'] as List<dynamic>).map((e) => QuestionAttachment.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'stem': stem,
        'options': options.map((e) => e.toJson()).toList(),
        'blanks': blanks.map((e) => e.toJson()).toList(),
        'subquestions': subquestions.map((e) => e.toJson()).toList(),
        'attachments': attachments.map((e) => e.toJson()).toList(),
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
    required this.origin,
    this.reviewItemId,
    this.parentSessionId,
  });

  final String questionId;
  final SessionOrigin origin;
  final String? reviewItemId;
  final String? parentSessionId;

  factory SessionCreate.fromJson(Map<String, dynamic> json) => SessionCreate(
        questionId: json['question_id'] as String,
        origin: SessionOrigin.fromJson(json['origin'] as String),
        reviewItemId: json['review_item_id'] == null ? null : json['review_item_id'] as String,
        parentSessionId: json['parent_session_id'] == null ? null : json['parent_session_id'] as String,
      );

  Map<String, dynamic> toJson() => {
        'question_id': questionId,
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

/// 按题目的 answer_mode 填写对应字段：选择题用 selected_options，填空题用 blanks。
class AnswerPayload {
  const AnswerPayload({
    this.selectedOptions,
    this.blanks,
    this.text,
  });

  final List<String>? selectedOptions;
  final List<AnswerBlank>? blanks;
  final String? text;

  factory AnswerPayload.fromJson(Map<String, dynamic> json) => AnswerPayload(
        selectedOptions: json['selected_options'] == null ? null : (json['selected_options'] as List<dynamic>).map((e) => e as String).toList(),
        blanks: json['blanks'] == null ? null : (json['blanks'] as List<dynamic>).map((e) => AnswerBlank.fromJson(e as Map<String, dynamic>)).toList(),
        text: json['text'] == null ? null : json['text'] as String,
      );

  Map<String, dynamic> toJson() => {
        if (selectedOptions != null) 'selected_options': selectedOptions,
        if (blanks != null) 'blanks': blanks?.map((e) => e.toJson()).toList(),
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
  });

  final AnswerPayload answer;
  final int? elapsedMs;

  factory SubmitRequest.fromJson(Map<String, dynamic> json) => SubmitRequest(
        answer: AnswerPayload.fromJson(json['answer'] as Map<String, dynamic>),
        elapsedMs: json['elapsed_ms'] == null ? null : (json['elapsed_ms'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'answer': answer.toJson(),
        if (elapsedMs != null) 'elapsed_ms': elapsedMs,
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
  });

  final String id;
  final String sessionId;
  final int seqNo;
  final TutorEventType type;
  final DateTime createdAt;
  final SessionState stateAfter;
  final Map<String, dynamic> payload;
  final TutorEventMeta meta;

  factory TutorEvent.fromJson(Map<String, dynamic> json) => TutorEvent(
        id: json['id'] as String,
        sessionId: json['session_id'] as String,
        seqNo: (json['seq_no'] as num).toInt(),
        type: TutorEventType.fromJson(json['type'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
        stateAfter: SessionState.fromJson(json['state_after'] as String),
        payload: Map<String, dynamic>.from(json['payload'] as Map),
        meta: TutorEventMeta.fromJson(json['meta'] as Map<String, dynamic>),
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
      };
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
        'by_subject': bySubject.map((e) => e.toJson()).toList(),
        'by_answer_mode': byAnswerMode.map((e) => e.toJson()).toList(),
        'by_difficulty': byDifficulty.map((e) => e.toJson()).toList(),
        'disclaimer': disclaimer,
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
  });

  final String id;
  final String status;
  final double? confidence;
  final bool lowConfidence;
  final String? stemText;
  final List<ScanExpression> expressions;
  final String? matchedQuestionId;
  final String? errorCode;

  factory Scan.fromJson(Map<String, dynamic> json) => Scan(
        id: json['id'] as String,
        status: json['status'] as String,
        confidence: json['confidence'] == null ? null : (json['confidence'] as num).toDouble(),
        lowConfidence: json['low_confidence'] as bool,
        stemText: json['stem_text'] == null ? null : json['stem_text'] as String,
        expressions: (json['expressions'] as List<dynamic>).map((e) => ScanExpression.fromJson(e as Map<String, dynamic>)).toList(),
        matchedQuestionId: json['matched_question_id'] == null ? null : json['matched_question_id'] as String,
        errorCode: json['error_code'] == null ? null : json['error_code'] as String,
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

class ParentWeekly {
  const ParentWeekly({
    required this.studentId,
    required this.weekStart,
    required this.sessionsCount,
    required this.independent,
    required this.assisted,
    required this.bySubject,
  });

  final String studentId;
  final String weekStart;
  final int sessionsCount;
  final RateStat independent;
  final RateStat assisted;
  final List<ProgressBucket> bySubject;

  factory ParentWeekly.fromJson(Map<String, dynamic> json) => ParentWeekly(
        studentId: json['student_id'] as String,
        weekStart: json['week_start'] as String,
        sessionsCount: (json['sessions_count'] as num).toInt(),
        independent: RateStat.fromJson(json['independent'] as Map<String, dynamic>),
        assisted: RateStat.fromJson(json['assisted'] as Map<String, dynamic>),
        bySubject: (json['by_subject'] as List<dynamic>).map((e) => ProgressBucket.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Map<String, dynamic> toJson() => {
        'student_id': studentId,
        'week_start': weekStart,
        'sessions_count': sessionsCount,
        'independent': independent.toJson(),
        'assisted': assisted.toJson(),
        'by_subject': bySubject.map((e) => e.toJson()).toList(),
      };
}

class ReviewDecision {
  const ReviewDecision({
    required this.decision,
    required this.expectedVersion,
    this.comment,
  });

  final String decision;
  final int expectedVersion;
  final String? comment;

  factory ReviewDecision.fromJson(Map<String, dynamic> json) => ReviewDecision(
        decision: json['decision'] as String,
        expectedVersion: (json['expected_version'] as num).toInt(),
        comment: json['comment'] == null ? null : json['comment'] as String,
      );

  Map<String, dynamic> toJson() => {
        'decision': decision,
        'expected_version': expectedVersion,
        if (comment != null) 'comment': comment,
      };
}

class QuestionReviewState {
  const QuestionReviewState({
    required this.questionId,
    required this.status,
    required this.version,
    this.reviewedBy,
    required this.updatedAt,
  });

  final String questionId;
  final String status;
  final int version;
  final String? reviewedBy;
  final DateTime updatedAt;

  factory QuestionReviewState.fromJson(Map<String, dynamic> json) => QuestionReviewState(
        questionId: json['question_id'] as String,
        status: json['status'] as String,
        version: (json['version'] as num).toInt(),
        reviewedBy: json['reviewed_by'] == null ? null : json['reviewed_by'] as String,
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  Map<String, dynamic> toJson() => {
        'question_id': questionId,
        'status': status,
        'version': version,
        'reviewed_by': reviewedBy,
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}
