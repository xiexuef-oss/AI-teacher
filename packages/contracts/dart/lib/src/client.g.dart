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

  /// 获取本人最近一轮三题摸底及恢复进度
  Future<DiagnosticWorkspace> getDiagnosticWorkspace({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/diagnostics',
      requestId: requestId,
    );
    return DiagnosticWorkspace.fromJson(data as Map<String, dynamic>);
  }

  /// 按本人资料创建一轮三题摸底
  Future<DiagnosticWorkspace> createDiagnostic({
    required DiagnosticCreate body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/diagnostics',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return DiagnosticWorkspace.fromJson(data as Map<String, dynamic>);
  }

  /// 按开始时间倒序分页回看本人摸底轮次
  Future<DiagnosticHistoryPage> listDiagnosticHistory({
    String? cursor,
    int? limit,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/diagnostics/history',
      query: {'cursor': cursor, 'limit': limit?.toString()},
      requestId: requestId,
    );
    return DiagnosticHistoryPage.fromJson(data as Map<String, dynamic>);
  }

  /// 回看本人固定轮次及首份提交的本轮计数
  Future<DiagnosticRun> getDiagnostic({
    required String diagnosticId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/diagnostics/${Uri.encodeComponent(diagnosticId)}',
      requestId: requestId,
    );
    return DiagnosticRun.fromJson(data as Map<String, dynamic>);
  }

  /// 打开固定题目版本的作答会话，已打开时返回原会话
  Future<StudySession> openDiagnosticSession({
    required String diagnosticId,
    required String position,
    required DiagnosticRevision body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/diagnostics/${Uri.encodeComponent(diagnosticId)}/items/${Uri.encodeComponent(position)}/session',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return StudySession.fromJson(data as Map<String, dynamic>);
  }

  /// 明确结束本人当前轮次，保留题目、会话及所有草稿
  Future<DiagnosticWorkspace> abandonDiagnostic({
    required String diagnosticId,
    required DiagnosticRevision body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/diagnostics/${Uri.encodeComponent(diagnosticId)}/abandon',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return DiagnosticWorkspace.fromJson(data as Map<String, dynamic>);
  }

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

  /// 下载本人当前可访问学生用途媒体的ZIP档案
  Future<StudentMediaExport> getStudentMediaExport({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/profile/media-export',
      requestId: requestId,
    );
    return StudentMediaExport.fromJson(data as Map<String, dynamic>);
  }

  /// 导出当前学生的服务端学习记录
  Future<StudentLearningExport> getStudentLearningExport({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/profile/learning-export',
      requestId: requestId,
    );
    return StudentLearningExport.fromJson(data as Map<String, dynamic>);
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
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/profile',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return StudentProfile.fromJson(data as Map<String, dynamic>);
  }

  /// 分页列出本人已发布的纸包
  Future<LearningPackHistory> listLearningPacks({
    String? after,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/learning/packs',
      query: {'after': after},
      requestId: requestId,
    );
    return LearningPackHistory.fromJson(data as Map<String, dynamic>);
  }

  /// 提交学习包准备任务
  Future<LearningJobStatus> createLearningPack({
    required LearningPackRequest body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/learning/packs',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return LearningJobStatus.fromJson(data as Map<String, dynamic>);
  }

  /// 下载本人已发布学习包的学生版
  Future<LearningPackPdf> downloadLearningPackStudentPdf({
    required String jobId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/learning/packs/${Uri.encodeComponent(jobId)}/student-pdf',
      requestId: requestId,
    );
    return LearningPackPdf.fromJson(data as Map<String, dynamic>);
  }

  /// 主动结束本人纸包的独立作答并开放解析
  Future<LearningJobStatus> abandonLearningPack({
    required String jobId,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/learning/packs/${Uri.encodeComponent(jobId)}/abandon',
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return LearningJobStatus.fromJson(data as Map<String, dynamic>);
  }

  /// 下载本人已完成回收的解析版
  Future<LearningPackPdf> downloadLearningPackSolutionPdf({
    required String jobId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/learning/packs/${Uri.encodeComponent(jobId)}/solution-pdf',
      requestId: requestId,
    );
    return LearningPackPdf.fromJson(data as Map<String, dynamic>);
  }

  /// 列出本人已发布纸包的题目定位信息
  Future<LearningPackItems> listLearningPackItems({
    required String jobId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/learning/packs/${Uri.encodeComponent(jobId)}/items',
      requestId: requestId,
    );
    return LearningPackItems.fromJson(data as Map<String, dynamic>);
  }

  /// 用二维码定位本人纸包中的印刷题目
  Future<LearningPackItem> resolveLearningPackPage({
    required String jobId,
    String? token,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/learning/packs/${Uri.encodeComponent(jobId)}/page',
      query: {'token': token},
      requestId: requestId,
    );
    return LearningPackItem.fromJson(data as Map<String, dynamic>);
  }

  /// 按包号和短码定位本人纸包中的已打印题目版本
  Future<LearningPackItem> resolveLearningPackItem({
    required String jobId,
    required String code,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/learning/packs/${Uri.encodeComponent(jobId)}/items/${Uri.encodeComponent(code)}',
      requestId: requestId,
    );
    return LearningPackItem.fromJson(data as Map<String, dynamic>);
  }

  /// 读取本人已确认的纸笔作答转写
  Future<LearningPackReturnRecord> getLearningPackReturn({
    required String jobId,
    required String code,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/learning/packs/${Uri.encodeComponent(jobId)}/items/${Uri.encodeComponent(code)}/returns',
      requestId: requestId,
    );
    return LearningPackReturnRecord.fromJson(data as Map<String, dynamic>);
  }

  /// 按版本校正本人已回收的转写
  Future<LearningPackReturnRecord> correctLearningPackReturn({
    required String jobId,
    required String code,
    required LearningPackCorrection body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/learning/packs/${Uri.encodeComponent(jobId)}/items/${Uri.encodeComponent(code)}/returns',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return LearningPackReturnRecord.fromJson(data as Map<String, dynamic>);
  }

  /// 保存本人确认过的纸笔作答转写
  Future<LearningPackItem> submitLearningPackReturn({
    required String jobId,
    required String code,
    required LearningPackReturnRequest body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/learning/packs/${Uri.encodeComponent(jobId)}/items/${Uri.encodeComponent(code)}/returns',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return LearningPackItem.fromJson(data as Map<String, dynamic>);
  }

  /// 查看本人的纸笔复测候选日期
  Future<PaperReviewSchedule> getPaperReviewSchedule({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/learning/review-schedule',
      requestId: requestId,
    );
    return PaperReviewSchedule.fromJson(data as Map<String, dynamic>);
  }

  /// 查询本人学习任务
  Future<LearningJobStatus> getLearningJob({
    required String jobId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/learning/jobs/${Uri.encodeComponent(jobId)}',
      requestId: requestId,
    );
    return LearningJobStatus.fromJson(data as Map<String, dynamic>);
  }

  /// 取消本人尚未结束的学习任务
  Future<LearningJobStatus> cancelLearningJob({
    required String jobId,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/learning/jobs/${Uri.encodeComponent(jobId)}/cancel',
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return LearningJobStatus.fromJson(data as Map<String, dynamic>);
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
    String? knowledgeId,
    QuestionScope? scope,
    String? cursor,
    int? limit,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/questions',
      query: {'subject': subject?.value, 'answer_mode': answerMode?.value, 'source_category': sourceCategory?.value, 'knowledge_id': knowledgeId, 'scope': scope?.value, 'cursor': cursor, 'limit': limit?.toString()},
      requestId: requestId,
    );
    return QuestionPage.fromJson(data as Map<String, dynamic>);
  }

  /// 当前可练题目的知识点与题量
  Future<QuestionTopicPage> listQuestionTopics({
    Subject? subject,
    AnswerMode? answerMode,
    QuestionScope? scope,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/questions/topics',
      query: {'subject': subject?.value, 'answer_mode': answerMode?.value, 'scope': scope?.value},
      requestId: requestId,
    );
    return QuestionTopicPage.fromJson(data as Map<String, dynamic>);
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

  /// 读取本人学习会话固定版本的题面
  Future<Question> getSessionQuestion({
    required String sessionId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/sessions/${Uri.encodeComponent(sessionId)}/question',
      requestId: requestId,
    );
    return Question.fromJson(data as Map<String, dynamic>);
  }

  /// 分页发现本人该题的未提交草稿与副本
  Future<QuestionDraftPage> listQuestionDrafts({
    required String questionId,
    String? cursor,
    int? limit,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/questions/${Uri.encodeComponent(questionId)}/drafts',
      query: {'cursor': cursor, 'limit': limit?.toString()},
      requestId: requestId,
    );
    return QuestionDraftPage.fromJson(data as Map<String, dynamic>);
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

  /// 明确保留本机快照为同会话独立草稿副本
  Future<DraftCopy> createDraftCopy({
    required String attemptId,
    required DraftCopyCreate body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/attempts/${Uri.encodeComponent(attemptId)}/copies',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return DraftCopy.fromJson(data as Map<String, dynamic>);
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

  /// 读取本人复测项的当前紧凑状态
  Future<ReviewState> getReviewState({
    required String reviewId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/reviews/${Uri.encodeComponent(reviewId)}/state',
      requestId: requestId,
    );
    return ReviewState.fromJson(data as Map<String, dynamic>);
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

  /// 学生读取已发布题目当前引用且独立审校确认的静态题面图片
  Future<MediaContent> getPublishedQuestionMedia({
    required String questionId,
    required String mediaId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/questions/${Uri.encodeComponent(questionId)}/media/${Uri.encodeComponent(mediaId)}/content',
      requestId: requestId,
    );
    return MediaContent.fromJson(data as Map<String, dynamic>);
  }

  /// 审核员声明已查看当前版本题面图片
  Future<MediaReviewDeclaration> confirmQuestionMediaReview({
    required String questionId,
    required String mediaId,
    required MediaReviewConfirmation body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/questions/${Uri.encodeComponent(questionId)}/media/${Uri.encodeComponent(mediaId)}/review-confirmations',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return MediaReviewDeclaration.fromJson(data as Map<String, dynamic>);
  }

  /// 创建本地短期附件上传凭据
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

  /// 上传者读取已确认附件
  Future<MediaContent> getMediaContent({
    required String mediaId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/media/${Uri.encodeComponent(mediaId)}/content',
      requestId: requestId,
    );
    return MediaContent.fromJson(data as Map<String, dynamic>);
  }

  /// 上传有界本地附件字节
  Future<MediaAssetInfo> uploadMediaContent({
    required String mediaId,
    required MediaBlobUpload body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/media/${Uri.encodeComponent(mediaId)}/content',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return MediaAssetInfo.fromJson(data as Map<String, dynamic>);
  }

  /// 确认本地附件大小摘要和格式
  Future<MediaAssetInfo> confirmMediaUpload({
    required String mediaId,
    required MediaConfirm body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/media/${Uri.encodeComponent(mediaId)}/confirm',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return MediaAssetInfo.fromJson(data as Map<String, dynamic>);
  }

  /// 幂等删除本地附件
  Future<MediaDeleted> deleteMedia({
    required String mediaId,
    required MediaDelete body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/media/${Uri.encodeComponent(mediaId)}/delete',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return MediaDeleted.fromJson(data as Map<String, dynamic>);
  }

  /// 审核员读取当前题目实际引用的附件
  Future<MediaContent> getQuestionMediaContent({
    required String mediaId,
    required String questionId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/admin/questions/${Uri.encodeComponent(questionId)}/media/${Uri.encodeComponent(mediaId)}/content',
      requestId: requestId,
    );
    return MediaContent.fromJson(data as Map<String, dynamic>);
  }

  /// 提交本人已上传的学校材料
  Future<LearningJobStatus> submitSchoolMaterial({
    required SchoolMaterialSubmitRequest body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/school-materials',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return LearningJobStatus.fromJson(data as Map<String, dynamic>);
  }

  /// 查看本人学校材料的待核对页面
  Future<SchoolMaterialPages> listSchoolMaterialPages({
    required String jobId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/school-materials/${Uri.encodeComponent(jobId)}/pages',
      requestId: requestId,
    );
    return SchoolMaterialPages.fromJson(data as Map<String, dynamic>);
  }

  /// 保存本人学校材料的逐页转写校正
  Future<SchoolMaterialCorrectionReceipt> correctSchoolMaterialPage({
    required String jobId,
    required String pageNumber,
    required SchoolMaterialPageCorrection body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/school-materials/${Uri.encodeComponent(jobId)}/pages/${Uri.encodeComponent(pageNumber)}/correction',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return SchoolMaterialCorrectionReceipt.fromJson(data as Map<String, dynamic>);
  }

  /// 查看本人学校材料的分题候选
  Future<SchoolMaterialCandidates> listSchoolMaterialCandidates({
    required String jobId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/school-materials/${Uri.encodeComponent(jobId)}/candidates',
      requestId: requestId,
    );
    return SchoolMaterialCandidates.fromJson(data as Map<String, dynamic>);
  }

  /// 保存本人核对过的学校材料分题
  Future<SchoolMaterialConfirmationReceipt> confirmSchoolMaterialCandidates({
    required String jobId,
    required SchoolMaterialConfirmationRequest body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/school-materials/${Uri.encodeComponent(jobId)}/confirmation',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return SchoolMaterialConfirmationReceipt.fromJson(data as Map<String, dynamic>);
  }

  /// 预览本人学校材料原件的一页
  Future<MediaContent> getSchoolMaterialPagePreview({
    required String jobId,
    required String pageNumber,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/school-materials/${Uri.encodeComponent(jobId)}/pages/${Uri.encodeComponent(pageNumber)}/preview',
      requestId: requestId,
    );
    return MediaContent.fromJson(data as Map<String, dynamic>);
  }

  /// 预留本人学校材料临时上传凭据
  Future<MediaUpload> createSchoolMaterialUpload({
    required SchoolMaterialUploadRequest body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/school-materials/uploads',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return MediaUpload.fromJson(data as Map<String, dynamic>);
  }

  /// 上传本人学校材料原件
  Future<SchoolMaterialSource> uploadSchoolMaterialContent({
    required String mediaId,
    required MediaBlobUpload body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/school-materials/uploads/${Uri.encodeComponent(mediaId)}/content',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return SchoolMaterialSource.fromJson(data as Map<String, dynamic>);
  }

  /// 学生专用本地临时拍题图片（Mock，不实际识别）
  Future<MediaUpload> createScanUpload({
    required MediaUploadRequest body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/scans/uploads',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return MediaUpload.fromJson(data as Map<String, dynamic>);
  }

  /// 预览本人仍有效的临时作答照片
  Future<MediaContent> getScanUploadContent({
    required String mediaId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/scans/uploads/${Uri.encodeComponent(mediaId)}/content',
      requestId: requestId,
    );
    return MediaContent.fromJson(data as Map<String, dynamic>);
  }

  /// 学生专用本地临时拍题图片（Mock，不实际识别）
  Future<MediaAssetInfo> uploadScanContent({
    required String mediaId,
    required MediaBlobUpload body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'PUT', '/scans/uploads/${Uri.encodeComponent(mediaId)}/content',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return MediaAssetInfo.fromJson(data as Map<String, dynamic>);
  }

  /// 本地Mock：返回空候选，未实际识别图片
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
    required ParentInviteCreate body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/me/parent-invites',
      body: body.toJson(),
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
    required ParentLinkRevoke body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/me/parent-links/${Uri.encodeComponent(linkId)}/revoke',
      body: body.toJson(),
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

  /// 查看已授权学生的周报快照
  Future<ParentWeeklySnapshot> getParentWeeklySnapshot({
    required String studentId,
    required String weekStart,
    int? revision,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/parents/students/${Uri.encodeComponent(studentId)}/weekly-snapshots/${Uri.encodeComponent(weekStart)}',
      query: {'revision': revision?.toString()},
      requestId: requestId,
    );
    return ParentWeeklySnapshot.fromJson(data as Map<String, dynamic>);
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

  /// 文档导入限额与可用能力
  Future<DocImportOptions> getDocumentImportOptions({
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/admin/import-options',
      requestId: requestId,
    );
    return DocImportOptions.fromJson(data as Map<String, dynamic>);
  }

  /// 我的导入任务
  Future<DocImportJobPage> listDocumentImportJobs({
    String? cursor,
    int? limit,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/admin/import-jobs',
      query: {'cursor': cursor, 'limit': limit?.toString()},
      requestId: requestId,
    );
    return DocImportJobPage.fromJson(data as Map<String, dynamic>);
  }

  /// 创建多文件导入任务
  Future<DocImportJobSummary> createDocumentImportJob({
    required DocImportJobCreate body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/import-jobs',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return DocImportJobSummary.fromJson(data as Map<String, dynamic>);
  }

  /// 导入进度与候选题
  Future<DocImportJobDetail> getDocumentImportJob({
    required String jobId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/admin/import-jobs/${Uri.encodeComponent(jobId)}',
      requestId: requestId,
    );
    return DocImportJobDetail.fromJson(data as Map<String, dynamic>);
  }

  /// 上传文件到导入任务
  Future<DocImportUploadResult> uploadDocumentImportFile({
    required String jobId,
    required DocImportUpload body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/import-jobs/${Uri.encodeComponent(jobId)}/files',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return DocImportUploadResult.fromJson(data as Map<String, dynamic>);
  }

  /// 读取临时原文件
  Future<DocImportContent> getDocumentImportContent({
    required String jobId,
    required String fileId,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/admin/import-jobs/${Uri.encodeComponent(jobId)}/files/${Uri.encodeComponent(fileId)}/content',
      requestId: requestId,
    );
    return DocImportContent.fromJson(data as Map<String, dynamic>);
  }

  /// 读取受控页面预览
  Future<DocImportContent> getDocumentImportPreview({
    required String jobId,
    required String fileId,
    required String page,
    int? mediaIndex,
    String? requestId,
  }) async {
    final data = await _core.send(
      'GET', '/admin/import-jobs/${Uri.encodeComponent(jobId)}/files/${Uri.encodeComponent(fileId)}/previews/${Uri.encodeComponent(page)}',
      query: {'media_index': mediaIndex?.toString()},
      requestId: requestId,
    );
    return DocImportContent.fromJson(data as Map<String, dynamic>);
  }

  /// 排队提取文件并建议切题
  Future<DocImportJobSummary> processDocumentImportJob({
    required String jobId,
    required DocImportRevision body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/import-jobs/${Uri.encodeComponent(jobId)}/process',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return DocImportJobSummary.fromJson(data as Map<String, dynamic>);
  }

  /// 取消尚未完成的导入工作
  Future<DocImportJobSummary> cancelDocumentImportJob({
    required String jobId,
    required DocImportRevision body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/import-jobs/${Uri.encodeComponent(jobId)}/cancel',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return DocImportJobSummary.fromJson(data as Map<String, dynamic>);
  }

  /// 保存拆分合并与人工校对结果
  Future<DocImportJobDetail> editDocumentImportCandidates({
    required String jobId,
    required DocImportCandidatesEdit body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/import-jobs/${Uri.encodeComponent(jobId)}/candidates',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return DocImportJobDetail.fromJson(data as Map<String, dynamic>);
  }

  /// 批量创建已确认候选题的待审草稿
  Future<DocImportBatchResult> submitDocumentImportCandidates({
    required String jobId,
    required DocImportSubmit body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/import-jobs/${Uri.encodeComponent(jobId)}/submit',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return DocImportBatchResult.fromJson(data as Map<String, dynamic>);
  }

  /// 导入结构化题目为待审草稿
  Future<AdminQuestionDetail> importQuestionDraft({
    required AdminQuestionImport body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/question-imports',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
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

  /// 逐题显式确认后的批量审核
  Future<ReviewBatchResult> reviewQuestionBatch({
    required ReviewBatch body,
    required String idempotencyKey,
    String? requestId,
  }) async {
    final data = await _core.send(
      'POST', '/admin/question-reviews/batch',
      body: body.toJson(),
      idempotencyKey: idempotencyKey,
      requestId: requestId,
    );
    return ReviewBatchResult.fromJson(data as Map<String, dynamic>);
  }
}
