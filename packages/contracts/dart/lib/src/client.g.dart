// GENERATED CODE - DO NOT MODIFY BY HAND
// 由 tools/gen_dart_contracts.py 根据 contracts/openapi.yaml 生成。要改动请改契约后重新生成。
// dart format off
// ignore_for_file: type=lint

import 'models.g.dart';
import 'runtime.dart';

/// 生成时的契约版本。
const String contractVersion = '1.3.0-slice.1';

/// 每个契约操作一个方法。请求与响应对象都是由契约生成的类型。
class TutorApiClient {
  TutorApiClient(this._core);

  final ApiCore _core;

  /// 服务健康状态与关键开关
  Future<Health> getHealth({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/health',
      requestId: requestId,
      authenticated: false,
    );
    return Health.fromJson(data as Map<String, dynamic>);
  }

  /// 首发地区、年级、学科、教材选项与考试年份估算
  Future<LaunchConfig> getLaunchConfig({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/meta/launch-config',
      requestId: requestId,
      authenticated: false,
    );
    return LaunchConfig.fromJson(data as Map<String, dynamic>);
  }

  /// 创建一个本地身份并返回随机 bearer
  Future<LocalIdentity> createLocalIdentity({
    LocalRole? role,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/dev/local-identities',
      query: {'role': role?.value},
      requestId: requestId,
      authenticated: false,
    );
    return LocalIdentity.fromJson(data as Map<String, dynamic>);
  }

  /// 当前学生的资料
  Future<StudentProfile> getProfile({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/profile',
      requestId: requestId,
    );
    return StudentProfile.fromJson(data as Map<String, dynamic>);
  }

  /// 保存地区、年级、学科、考试年份与教材版本
  Future<StudentProfile> updateProfile({
    required ProfileUpdate body,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/profile',
      body: body.toJson(),
      requestId: requestId,
    );
    return StudentProfile.fromJson(data as Map<String, dynamic>);
  }

  /// 今日任务
  Future<TodayTasks> getTodayTasks({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/tasks/today',
      requestId: requestId,
    );
    return TodayTasks.fromJson(data as Map<String, dynamic>);
  }

  /// 练习选题列表
  Future<QuestionPage> listQuestions({
    Subject? subject,
    AnswerMode? answerMode,
    SourceCategory? sourceCategory,
    QuestionScope? scope,
    String? cursor,
    int? limit,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/questions',
      query: {'subject': subject?.value, 'answer_mode': answerMode?.value, 'source_category': sourceCategory?.value, 'scope': scope?.value, 'cursor': cursor, 'limit': limit?.toString()},
      requestId: requestId,
    );
    return QuestionPage.fromJson(data as Map<String, dynamic>);
  }

  /// 题目与结构
  Future<Question> getQuestion({
    required String questionId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/questions/${Uri.encodeComponent(questionId)}',
      requestId: requestId,
    );
    return Question.fromJson(data as Map<String, dynamic>);
  }

  /// 为一道题开启学习会话
  Future<StudySession> createSession({
    required SessionCreate body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/sessions',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return StudySession.fromJson(data as Map<String, dynamic>);
  }

  /// 会话当前状态
  Future<StudySession> getSession({
    required String sessionId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/sessions/${Uri.encodeComponent(sessionId)}',
      requestId: requestId,
    );
    return StudySession.fromJson(data as Map<String, dynamic>);
  }

  /// 按 seq 恢复教学事件
  Future<TutorEventPage> listSessionEvents({
    required String sessionId,
    int? afterSeq,
    int? limit,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/sessions/${Uri.encodeComponent(sessionId)}/events',
      query: {'after_seq': afterSeq?.toString(), 'limit': limit?.toString()},
      requestId: requestId,
    );
    return TutorEventPage.fromJson(data as Map<String, dynamic>);
  }

  /// 在会话中新建一次作答草稿
  Future<Attempt> createAttempt({
    required AttemptCreate body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/attempts',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return Attempt.fromJson(data as Map<String, dynamic>);
  }

  /// 一次作答及其评估
  Future<Attempt> getAttempt({
    required String attemptId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/attempts/${Uri.encodeComponent(attemptId)}',
      requestId: requestId,
    );
    return Attempt.fromJson(data as Map<String, dynamic>);
  }

  /// 云端草稿（未提交的答案与笔迹）
  Future<Draft> getDraft({
    required String attemptId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/attempts/${Uri.encodeComponent(attemptId)}/draft',
      requestId: requestId,
    );
    return Draft.fromJson(data as Map<String, dynamic>);
  }

  /// 同步草稿
  Future<Draft> syncDraft({
    required String attemptId,
    required DraftSync body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/attempts/${Uri.encodeComponent(attemptId)}/draft',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return Draft.fromJson(data as Map<String, dynamic>);
  }

  /// 提交作答并返回评估状态
  Future<SubmitResult> submitAttempt({
    required String attemptId,
    required SubmitRequest body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/attempts/${Uri.encodeComponent(attemptId)}/submit',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return SubmitResult.fromJson(data as Map<String, dynamic>);
  }

  /// 解答题、实验题、证明题提交后的对照自查：要点，以及已保存的自评
  Future<SelfCheck> getSelfCheck({
    required String attemptId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/attempts/${Uri.encodeComponent(attemptId)}/self-check',
      requestId: requestId,
    );
    return SelfCheck.fromJson(data as Map<String, dynamic>);
  }

  /// 保存对照自查的结果
  Future<SelfCheck> saveSelfCheck({
    required String attemptId,
    required SelfCheckSave body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/attempts/${Uri.encodeComponent(attemptId)}/self-check',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return SelfCheck.fromJson(data as Map<String, dynamic>);
  }

  /// 教学下一步
  Future<TutorStep> tutorNext({
    required String sessionId,
    required TutorAction body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/tutor/sessions/${Uri.encodeComponent(sessionId)}/next',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return TutorStep.fromJson(data as Map<String, dynamic>);
  }

  /// 复测队列
  Future<ReviewPage> listDueReviews({
    ReviewScope? scope,
    String? cursor,
    int? limit,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/reviews/due',
      query: {'scope': scope?.value, 'cursor': cursor, 'limit': limit?.toString()},
      requestId: requestId,
    );
    return ReviewPage.fromJson(data as Map<String, dynamic>);
  }

  /// 用一次已判定的复测作答完成复测项
  Future<ReviewCompletion> completeReview({
    required String reviewId,
    required ReviewComplete body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/reviews/${Uri.encodeComponent(reviewId)}/complete',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return ReviewCompletion.fromJson(data as Map<String, dynamic>);
  }

  /// 学情摘要
  Future<ProgressSummary> getProgressSummary({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/progress/summary',
      requestId: requestId,
    );
    return ProgressSummary.fromJson(data as Map<String, dynamic>);
  }

  /// 获取短期上传 URL（planned）
  ///
  /// 契约已规划、服务端尚未实现：调用会得到 501 `not_implemented`。
  Future<MediaUpload> createMediaUpload({
    required MediaUploadRequest body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/media/uploads',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return MediaUpload.fromJson(data as Map<String, dynamic>);
  }

  /// 对已上传的单题图片启动 OCR（planned）
  ///
  /// 契约已规划、服务端尚未实现：调用会得到 501 `not_implemented`。
  Future<Scan> createScan({
    required ScanCreate body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/scans',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return Scan.fromJson(data as Map<String, dynamic>);
  }

  /// OCR 状态与可编辑题干（planned）
  ///
  /// 契约已规划、服务端尚未实现：调用会得到 501 `not_implemented`。
  Future<Scan> getScan({
    required String scanId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/scans/${Uri.encodeComponent(scanId)}',
      requestId: requestId,
    );
    return Scan.fromJson(data as Map<String, dynamic>);
  }

  /// 学生确认题干后关联已有题或生成待审题草案（planned）
  ///
  /// 契约已规划、服务端尚未实现：调用会得到 501 `not_implemented`。
  Future<ScanConfirmation> confirmScan({
    required String scanId,
    required ScanConfirm body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/scans/${Uri.encodeComponent(scanId)}/confirm',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return ScanConfirmation.fromJson(data as Map<String, dynamic>);
  }

  /// 学生生成一次性的家长邀请码（学生明确授权的第一步）
  Future<ParentInvite> createParentInvite({
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/me/parent-invites',
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return ParentInvite.fromJson(data as Map<String, dynamic>);
  }

  /// 学生看自己授权过哪些家长，以及有没有还没被使用的邀请码
  Future<ParentLinks> listParentLinks({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/me/parent-links',
      requestId: requestId,
    );
    return ParentLinks.fromJson(data as Map<String, dynamic>);
  }

  /// 学生撤销对一位家长的授权
  Future<ParentLink> revokeParentLink({
    required String linkId,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/me/parent-links/${Uri.encodeComponent(linkId)}/revoke',
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return ParentLink.fromJson(data as Map<String, dynamic>);
  }

  /// 家长输入学生给的邀请码，建立绑定
  Future<ParentStudent> redeemParentInvite({
    required ParentInviteRedeem body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/parents/links',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return ParentStudent.fromJson(data as Map<String, dynamic>);
  }

  /// 这位家长现在能看的学生
  Future<ParentStudents> listParentStudents({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/parents/students',
      requestId: requestId,
    );
    return ParentStudents.fromJson(data as Map<String, dynamic>);
  }

  /// 已授权绑定学生某一周的汇总
  Future<ParentWeekly> getParentWeekly({
    required String studentId,
    String? weekStart,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/parents/students/${Uri.encodeComponent(studentId)}/weekly',
      query: {'week_start': weekStart},
      requestId: requestId,
    );
    return ParentWeekly.fromJson(data as Map<String, dynamic>);
  }

  /// 审核队列：全部状态的题目
  Future<AdminQuestionPage> listAdminQuestions({
    QuestionStatus? status,
    Subject? subject,
    SourceCategory? sourceCategory,
    String? cursor,
    int? limit,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/admin/questions',
      query: {'status': status?.value, 'subject': subject?.value, 'source_category': sourceCategory?.value, 'cursor': cursor, 'limit': limit?.toString()},
      requestId: requestId,
    );
    return AdminQuestionPage.fromJson(data as Map<String, dynamic>);
  }

  /// 审核用的题目全貌
  Future<AdminQuestionDetail> getAdminQuestion({
    required String questionId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/admin/questions/${Uri.encodeComponent(questionId)}',
      requestId: requestId,
    );
    return AdminQuestionDetail.fromJson(data as Map<String, dynamic>);
  }

  /// 修改题目并产生新版本
  Future<AdminQuestionDetail> createQuestionVersion({
    required String questionId,
    required AdminQuestionEdit body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/questions/${Uri.encodeComponent(questionId)}/versions',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return AdminQuestionDetail.fromJson(data as Map<String, dynamic>);
  }

  /// 题目某一个版本的完整内容
  Future<AdminVersionSnapshot> getQuestionVersion({
    required String questionId,
    required String version,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/admin/questions/${Uri.encodeComponent(questionId)}/versions/${Uri.encodeComponent(version)}',
      requestId: requestId,
    );
    return AdminVersionSnapshot.fromJson(data as Map<String, dynamic>);
  }

  /// 审核决策
  Future<QuestionReviewState> reviewQuestion({
    required String questionId,
    required ReviewDecision body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/questions/${Uri.encodeComponent(questionId)}/review',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return QuestionReviewState.fromJson(data as Map<String, dynamic>);
  }
}
