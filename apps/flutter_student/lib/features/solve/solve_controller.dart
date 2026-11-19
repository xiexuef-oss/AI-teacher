import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/format.dart' show jsonEquals;
import '../../core/idempotency.dart';
import '../../core/storage.dart';
import 'draft_store.dart';
import 'resource_journal_store.dart';
import 'ink/ink_controller.dart';

enum SolvePhase { loading, answering, submitted, readonly, failed }

/// 草稿的保存状态。本机保存与云端同步是两回事：本机永远先保存。
enum SaveStatus { saved, dirty, saving, offline, conflict }

enum TutorOutcome { ok, needsConfirmation, busy, failed, notAllowed }

class SolveArgs {
  const SolveArgs({
    required this.questionId,
    this.origin = 'practice',
    this.reviewItemId,
    this.parentSessionId,
    this.sessionId,
    this.attemptId,
  });

  final String questionId;

  /// task / practice / review / variant
  final String origin;
  final String? reviewItemId;
  final String? parentSessionId;
  final String? sessionId;
  final String? attemptId;
}

/// 一次作答的全部状态与动作：取题、开会话、答案与笔迹的本地保存和云端同步、提交、辅导。
///
/// 几条原则：
/// - 学生的输入先落本机，再同步云端；断网、重启、切后台都不丢；
/// - 同步带版本号，冲突时不覆盖任何一方，交给学生选；
/// - 每个会改变服务端状态的动作带幂等键，失败后重试复用同一个键；
/// - 提交前看解析必须学生明确确认；复测在提交前不提供辅助。
class SolveController extends ChangeNotifier {
  SolveController({
    required this.api,
    required KeyValueStore store,
    required this.userId,
    required this.args,
    this.onUnauthenticated,
    this.isCurrentUser,
    this.autosaveDelay = const Duration(seconds: 2),
    this.syncDelay = const Duration(seconds: 4),
    this.retryDelay = const Duration(seconds: 12),
  }) : drafts = DraftStore(store, userId),
       resources = ResourceJournalStore(store, userId) {
    ink = InkController(onCommit: _onChanged);
  }

  final TutorApiClient api;
  final String userId;
  final SolveArgs args;
  final VoidCallback? onUnauthenticated;
  final bool Function()? isCurrentUser;
  bool get _mayUseIdentity => !_disposed && (isCurrentUser?.call() ?? true);

  /// 本机自动保存的间隔（docs/02：笔迹每 2 秒本地增量保存）。
  final Duration autosaveDelay;

  /// 停笔多久之后把草稿同步到云端。
  final Duration syncDelay;

  /// 断网后重试的间隔。
  final Duration retryDelay;

  DraftStore drafts;
  final ResourceJournalStore resources;
  static final _resourceQueues = Expando<Map<String, Future<void>>>();
  ReviewCompletion? historicalReviewCompletion;
  ResourceCommand? pendingTutor;
  ResourceCommand? pendingReview;
  ReviewState? reviewState;
  bool get needsTutorRecovery => _resourcePending(pendingTutor);
  bool get needsReviewRecovery => _resourcePending(pendingReview);
  bool _resourcePending(ResourceCommand? command) =>
      command != null && !['acked', 'rejected'].contains(command.phase);

  late final InkController ink;

  final Stopwatch _stopwatch = Stopwatch();

  SolvePhase phase = SolvePhase.loading;
  Object? failure;

  Question? question;
  bool questionFromCache = false;
  StudySession? session;
  Attempt? attempt;

  final Set<String> _selected = {};
  final Map<String, String> _blanks = {};

  /// 解答题、实验题各小问的文字，键是小问的 key。
  final Map<String, String> _parts = {};

  /// 实验题数据表里学生填的格子，键是 "表键.行键.列键"。
  final Map<String, String> _cells = {};

  /// 证明题一步一步写的证明，顺序就是证明的顺序。答题期间证明题至少有一张卡片（可以是空白的）。
  final List<ProofStepDraft> _steps = [];

  /// 步骤结构的版本号：添加、删除、挪动、整体换掉时加一，输入框据此整体重新同步。
  int _stepsRevision = 0;

  /// 证明题最多写多少步，每步的文字、依据最多多少字（与契约一致）。
  static const int maxProofSteps = 30;
  static const int maxStepText = 1000;
  static const int maxStepReason = 400;

  SaveStatus sync = SaveStatus.saved;
  bool localSaveFailed = false;
  Draft? conflictServerDraft;
  List<LocalDraft> recoveryCopies = const [];
  bool recoveryBusy = false;
  bool _recoveryBlocked = false;
  int? _recoveryGeneration;
  Future<void>? _conflictWrite;

  List<TutorEvent> events = const [];
  String? _cachedEventSessionId;
  String? get eventSessionId => session?.id ?? _cachedEventSessionId;
  Evaluation? evaluation;
  ReviewItem? reviewItem;
  ReviewCompletion? reviewCompletion;
  Object? reviewError;

  /// 解答题提交后对照要点做的自查。要点只在提交之后才取：独立作答阶段不泄题。
  SelfCheck? selfCheck;
  final Map<String, SelfCheckLevel> _marks = {};
  SubmissionCapture? unboundSubmission;
  WriteCommand? pendingSubmission;
  List<DraftContinuation> continuations = const [];
  bool get needsSubmissionRecovery =>
      pendingSubmission != null || unboundSubmission != null;
  Future<void> _marksWrite = Future<void>.value();
  bool selfCheckRemoteConflict = false;
  bool selfCheckBusy = false;
  Object? selfCheckError;

  Object? actionError;
  bool submitting = false;
  bool tutorBusy = false;
  bool authExpired = false;

  int _serverRevision = 0;
  String? _localAttemptId;
  String? _localSessionId;
  ActiveRef? _restoringRef;
  bool _useInitialRoute = true;
  bool _openingWorkspace = false;
  int _workspaceGeneration = 0;
  bool get hasOpenedNewWorkspace => !_useInitialRoute;
  bool get _sessionRoute =>
      _useInitialRoute && args.sessionId != null && args.attemptId == null;
  String? get _routedLocalId =>
      _sessionRoute ? 'session-${args.sessionId}' : null;
  bool get _explicitRoute =>
      _useInitialRoute && (args.attemptId != null || args.sessionId != null);
  bool _currentWorkspace(int generation) =>
      _mayUseIdentity && generation == _workspaceGeneration;
  bool _dirtyRemote = false;
  int _localVersion = 0;
  bool _syncing = false;
  Completer<void>? _syncCompletion;
  bool _attaching = false;
  bool _attachedDurably = false;
  bool _unboundLocalScope = false;
  DraftWorkspaceContext? _workspace;
  String? creationBlockedReason;
  ActiveRef? selectableCopy;
  String? _selectableCopyKey;
  DraftStore? _selectableCopySource;
  bool get hasVerifiedWorkspace => _workspace != null;
  bool get canResumeCreation =>
      creationBlockedReason?.startsWith('authentication_required:') ?? false;
  bool _disposed = false;
  Timer? _autosaveTimer;
  Timer? _syncTimer;
  Timer? _retryTimer;

  Set<String> get selected => Set.unmodifiable(_selected);
  Map<String, String> get blanks => Map.unmodifiable(_blanks);
  Map<String, String> get parts => Map.unmodifiable(_parts);
  Map<String, String> get cells => Map.unmodifiable(_cells);
  List<ProofStepDraft> get steps => List.unmodifiable(_steps);
  int get stepsRevision => _stepsRevision;
  bool get canAddStep =>
      hasVerifiedWorkspace &&
      phase == SolvePhase.answering &&
      _steps.length < maxProofSteps;
  Map<String, SelfCheckLevel> get marks => Map.unmodifiable(_marks);

  /// 每个要点都标过了。
  bool get selfCheckComplete =>
      selfCheck != null &&
      selfCheck!.points.isNotEmpty &&
      selfCheck!.points.every((p) => _marks.containsKey(p.key));

  /// 标过的内容和已经保存的不一样（包括还一次都没保存过）。
  bool get selfCheckDirty {
    final saved = {
      for (final m in selfCheck?.marks ?? const <SelfCheckMark>[])
        m.pointKey: m.level,
    };
    if (saved.length != _marks.length) return true;
    return _marks.entries.any((e) => saved[e.key] != e.value);
  }

  bool get isFinished => session?.state == SessionState.done;
  bool get isRetest => args.origin == 'review';

  /// 复测在提交之前不提供任何提示和解析。
  bool get assistanceAllowed =>
      !isFinished && !(isRetest && phase != SolvePhase.submitted);

  AnswerMode? get _mode => question?.answerMode;

  bool get _answerValid {
    switch (_mode) {
      case AnswerMode.singleChoice:
        return _selected.length == 1;
      case AnswerMode.multipleChoice:
        return _selected.isNotEmpty;
      case AnswerMode.fill:
        final keys = question!.content.blanks.map((b) => b.key);
        return keys.isNotEmpty &&
            keys.every((k) => (_blanks[k] ?? '').trim().isNotEmpty);
      case AnswerMode.written:
        // 有文字或有笔迹就可以提交，也可以只写其中几问
        return _hasPartsText || ink.hasInk;
      case AnswerMode.experiment:
        // 填了格子、写了文字或有笔迹都可以提交，也可以只填其中几个
        return _hasCellsText || _hasPartsText || ink.hasInk;
      case AnswerMode.proof:
        // 至少有一步写了文字，或有笔迹就可以提交；依据可以不写
        return _hasStepsText || ink.hasInk;
      default:
        return false;
    }
  }

  bool get _hasPartsText => _parts.values.any((v) => v.trim().isNotEmpty);
  bool get _hasCellsText => _cells.values.any((v) => v.trim().isNotEmpty);
  bool get _hasStepsText => _steps.any((s) => s.text.trim().isNotEmpty);

  /// 不自动评分、提交后对照要点自查的题（解答题、实验题、证明题）。
  bool get _isSubjective =>
      _mode == AnswerMode.written ||
      _mode == AnswerMode.experiment ||
      _mode == AnswerMode.proof;

  bool get canSubmit =>
      !_openingWorkspace &&
      !isFinished &&
      !_attaching &&
      creationBlockedReason == null &&
      hasVerifiedWorkspace &&
      phase == SolvePhase.answering &&
      !submitting &&
      !recoveryBusy &&
      !_recoveryBlocked &&
      sync != SaveStatus.conflict &&
      question != null &&
      _answerValid &&
      !needsSubmissionRecovery;

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  // ------------------------------------------------------------ 开始

  Future<void> start() async {
    phase = SolvePhase.loading;
    _notify();
    try {
      final savedActive = await drafts.readActive(args.questionId);
      final active = _sessionRoute && savedActive?.sessionId != args.sessionId
          ? null
          : savedActive;
      var routedActive = active;
      if (_sessionRoute) {
        try {
          final existing = await api.getSession(sessionId: args.sessionId!);
          if (!_mayUseIdentity) return;
          if (existing.questionId != args.questionId ||
              existing.origin != SessionOrigin.fromJson(args.origin) ||
              existing.reviewItemId != args.reviewItemId) {
            throw StateError('指定会话与当前题目或来源不符');
          }
          final selected =
              existing.firstSubmittedAttemptId ?? existing.activeAttemptId;
          routedActive = selected == null
              ? null
              : ActiveRef(sessionId: existing.id, attemptId: selected);
        } on ApiException catch (error) {
          if (!error.isNetwork) rethrow;
        }
      }
      final legacy = active == null && !_explicitRoute
          ? await drafts.readDraft(args.questionId)
          : null;
      _restoringRef =
          _useInitialRoute && args.sessionId != null && args.attemptId != null
          ? ActiveRef(sessionId: args.sessionId!, attemptId: args.attemptId!)
          : routedActive ??
                (legacy?.sessionId != null && legacy?.attemptId != null
                    ? ActiveRef(
                        sessionId: legacy!.sessionId!,
                        attemptId: legacy.attemptId!,
                      )
                    : null);
      final selectedId = _restoringRef?.attemptId;
      _unboundLocalScope = selectedId == null;
      drafts = selectedId == null
          ? drafts.forLocal(
              _routedLocalId ??
                  await drafts.readOrCreateLocalId(args.questionId),
            )
          : drafts.forAttempt(selectedId);
      if (_disposed) return;
      await drafts.claimScope(args.questionId);
      final saved = await drafts.readDraft(args.questionId);
      if (saved != null) _applyLocal(saved);
      _workspace = await drafts.readWorkspaceContext(args.questionId);
      unboundSubmission = await drafts.readUnboundSubmission(args.questionId);
      final submitCommand = await drafts.readWrite(args.questionId, 'submit');
      pendingSubmission = _pending(submitCommand) ? submitCommand : null;
      continuations = await drafts.readContinuations(args.questionId);
      final command = await drafts.readCreation(args.questionId);
      creationBlockedReason = command?.phase == 'blocked'
          ? command!.blockedReason
          : null;
      if (_workspace != null) {
        question = _workspace!.question;
        questionFromCache = true;
        if (_restoringRef != null) await _loadQuestion();
      } else if (saved?.hasContent == true && _restoringRef == null) {
        creationBlockedReason = '旧稿缺少可靠题面版本，已保留原文；请另开新版';
        question = await drafts.readQuestion(args.questionId);
        if (question == null) throw StateError(creationBlockedReason!);
      } else {
        await _loadQuestion();
        if (questionFromCache && _restoringRef == null) {
          creationBlockedReason = '缓存缺少可靠来源，请联网另开新版后作答';
        } else {
          if (saved != null &&
              _restoringRef != null &&
              saved.sessionId == null) {
            final verified = await api.getAttempt(
              attemptId: _restoringRef!.attemptId,
            );
            if (verified.sessionId != _restoringRef!.sessionId) {
              throw StateError('草稿会话不匹配');
            }
            await drafts.writeDraft(
              LocalDraft.fromJson(
                saved.toJson()..['sessionId'] = verified.sessionId,
              ),
            );
          }
          await _saveWorkspace(
            _restoringRef?.attemptId ??
                _routedLocalId ??
                await drafts.readOrCreateLocalId(args.questionId),
            trustedSessionId:
                _restoringRef?.sessionId ??
                (_sessionRoute ? args.sessionId : null),
          );
        }
      }
    } catch (error) {
      failure = error;
      phase = SolvePhase.failed;
      _checkAuth(error);
      _notify();
      return;
    }
    LocalDraft? local;
    try {
      local = await drafts.readDraft(args.questionId);
      if (local != null) _applyLocal(local);
    } catch (error) {
      failure = error;
      localSaveFailed = true;
      _recoveryBlocked = true;
      phase = SolvePhase.failed;
      _notify();
      return;
    }
    try {
      final recovery = await drafts.readRecovery(args.questionId);
      _recoveryGeneration = recovery?.generation;
      recoveryCopies = recovery?.copies ?? const [];
      if (recovery?.pending ?? false) {
        _recoveryBlocked = true;
        final archived = recovery!.copies[recovery.copies.length - 2];
        if (local == null || archived.savedAt.isAfter(local.savedAt)) {
          _applyLocal(archived);
        }
        conflictServerDraft = recovery.copies.last.asServer();
        sync = SaveStatus.conflict;
      }
    } catch (error) {
      _recoveryBlocked = true;
      actionError = error;
      localSaveFailed = true;
      sync = SaveStatus.conflict;
    }
    _ensureStep();
    phase = SolvePhase.answering;
    _stopwatch.start();
    _notify();

    await _attachRemote();
    if (session == null && sync == SaveStatus.offline) {
      await _restoreCachedTutorHistory();
    }
    if (_mayUseIdentity && attempt != null) {
      final command = await drafts.readWrite(args.questionId, 'submit');
      pendingSubmission = _pending(command) ? command : null;
      unboundSubmission = await drafts.readUnboundSubmission(args.questionId);
    }
    if (session != null) await _loadResourceCommands();
    if (_dirtyRemote &&
        !needsSubmissionRecovery &&
        !_recoveryBlocked &&
        sync != SaveStatus.conflict &&
        sync != SaveStatus.offline) {
      sync = SaveStatus.dirty;
      _scheduleSync();
    }
    _notify();
  }

  Future<void> _loadQuestion() async {
    try {
      final active = await drafts.readActive(args.questionId);
      final fixedSessionId =
          _restoringRef?.sessionId ??
          (_useInitialRoute ? args.sessionId : null) ??
          active?.sessionId;
      final loaded = fixedSessionId == null
          ? await api.getQuestion(questionId: args.questionId)
          : await api.getSessionQuestion(sessionId: fixedSessionId);
      if (loaded.id != args.questionId ||
          (_workspace != null &&
              loaded.version != _workspace!.question.version)) {
        creationBlockedReason = '固定题面版本与来源不符，原稿保留';
        throw StateError(creationBlockedReason!);
      }
      question = loaded;
      questionFromCache = false;
      try {
        await drafts.writeQuestion(loaded);
      } catch (_) {
        // 缓存写不进去不影响作答
      }
    } on ApiException catch (error) {
      if (error.isNetwork) {
        final cached = await drafts.readQuestion(args.questionId);
        if (cached != null) {
          question = cached;
          questionFromCache = true;
          return;
        }
      }
      rethrow;
    }
  }

  Future<void> _saveWorkspace(String id, {String? trustedSessionId}) async {
    final context = DraftWorkspaceContext(
      workspaceId: id,
      question: question!,
      trustedSessionId: trustedSessionId,
      sessionBody: SessionCreate(
        questionId: args.questionId,
        origin: SessionOrigin.fromJson(args.origin),
        reviewItemId: args.reviewItemId,
        parentSessionId: args.parentSessionId,
        expectedQuestionVersion: question!.version,
      ).toJson(),
    );
    await drafts.saveWorkspaceContext(args.questionId, context);
    _workspace = context;
  }

  Future<void> openLatestWorkspace() async {
    if (!_mayUseIdentity) return;
    if (_openingWorkspace ||
        _attaching ||
        _syncing ||
        recoveryBusy ||
        submitting ||
        _disposed) {
      return;
    }
    _openingWorkspace = true;
    try {
      if (phase == SolvePhase.answering) await drafts.writeDraft(_snapshot());
      final id = await drafts.newWorkspace(args.questionId);
      if (_disposed) return;
      _workspaceGeneration++;
      _useInitialRoute = false;
      _resetWorkspaceState();
      drafts = drafts.forLocal(id);
      await drafts.claimScope(args.questionId);
      _notify();
      if (!_mayUseIdentity) return;
      final generation = _workspaceGeneration;
      final loaded = await api.getQuestion(questionId: args.questionId);
      if (!_currentWorkspace(generation)) return;
      question = loaded;
      await _saveWorkspace(id);
      await drafts.writeQuestion(question!);
      _ensureStep();
      phase = SolvePhase.answering;
      localSaveFailed = false;
      _openingWorkspace = false;
      _stopwatch.start();
      await _attachRemote();
    } catch (error) {
      failure = error;
      phase = SolvePhase.failed;
    } finally {
      _openingWorkspace = false;
      _notify();
    }
  }

  void _resetWorkspaceState() {
    _autosaveTimer?.cancel();
    _autosaveTimer = null;
    _syncTimer?.cancel();
    _syncTimer = null;
    _stopRetry();
    _stopwatch
      ..stop()
      ..reset();
    phase = SolvePhase.loading;
    failure = null;
    question = null;
    questionFromCache = false;
    _workspace = null;
    _restoringRef = null;
    selectableCopy = null;
    _selectableCopyKey = null;
    _selectableCopySource = null;
    creationBlockedReason = null;
    session = null;
    attempt = null;
    _localAttemptId = null;
    _localSessionId = null;
    _attachedDurably = false;
    _unboundLocalScope = true;
    _recoveryBlocked = false;
    _recoveryGeneration = null;
    recoveryCopies = const [];
    conflictServerDraft = null;
    _conflictWrite = null;
    _selected.clear();
    _blanks.clear();
    _parts.clear();
    _cells.clear();
    _steps.clear();
    _stepsRevision++;
    ink.loadContract(null);
    _serverRevision = 0;
    _dirtyRemote = false;
    _localVersion++;
    events = const [];
    _cachedEventSessionId = null;
    evaluation = null;
    reviewItem = null;
    reviewCompletion = null;
    reviewError = null;
    selfCheck = null;
    selfCheckRemoteConflict = false;
    _marksWrite = Future<void>.value();
    pendingSubmission = null;
    unboundSubmission = null;
    continuations = const [];
    _marks.clear();
    selfCheckBusy = false;
    selfCheckError = null;
    actionError = null;
    submitting = false;
    tutorBusy = false;
    pendingTutor = null;
    pendingReview = null;
    historicalReviewCompletion = null;
    reviewState = null;
    authExpired = false;
    localSaveFailed = false;
    sync = SaveStatus.saved;
  }

  Future<void> resumeAuthenticatedCreation() async {
    if (!_mayUseIdentity || !canResumeCreation || _attaching) return;
    try {
      final command = await drafts.readCreation(args.questionId);
      if (command?.phase != 'blocked' || command?.resumePhase == null) return;
      final next = _nextCreation(command!, command.resumePhase!, {
        'blockedReason': null,
        'resumePhase': null,
      });
      await drafts.advanceCreation(
        args.questionId,
        next,
        expectedGeneration: command.generation,
      );
      creationBlockedReason = null;
      authExpired = false;
      await _attachRemote();
    } catch (error) {
      actionError = error;
    }
    _notify();
  }

  Future<List<({String id, LocalDraft draft, Question? question})>>
  readLocalWorkspaces() async {
    final results = <({String id, LocalDraft draft, Question? question})>[];
    for (final id in await drafts.listLocalWorkspaceIds(args.questionId)) {
      final scope = drafts.forLocal(id);
      final draft = await scope.readDraft(args.questionId);
      if (draft == null || !draft.hasContent) continue;
      final context = await scope.readWorkspaceContext(args.questionId);
      results.add((id: id, draft: draft, question: context?.question));
    }
    return results;
  }

  DraftCreationCommand _nextCreation(
    DraftCreationCommand old,
    String phase,
    Map<String, dynamic> fields,
  ) => DraftCreationCommand.fromJson({
    ...old.toJson(),
    ...fields,
    'phase': phase,
    'generation': old.generation + 1,
  });

  Future<bool> _runCreation({
    bool retry = false,
    String? continuationId,
  }) async {
    if (!_mayUseIdentity) return false;
    final source = drafts;
    var command = await source.readCreation(args.questionId);
    final context = _workspace ?? (throw StateError('没有可靠来源，不能创建会话'));
    if (_unboundLocalScope && phase == SolvePhase.answering) {
      await source.writeDraft(
        LocalDraft.fromJson(
          _snapshot().toJson()
            ..['sessionId'] = null
            ..['attemptId'] = null,
        ),
      );
    }
    if (command?.phase == 'blocked') {
      creationBlockedReason = command!.blockedReason;
      return false;
    }
    if (command == null || command.phase == 'attached') {
      command = DraftCreationCommand(
        intentId: newIdempotencyKey('create-intent'),
        transferPolicy: continuationId == null
            ? null
            : {'kind': 'continuation', 'continuationId': continuationId},
        generation: 1,
        phase: retry ? 'attempt_prepared' : 'session_prepared',
        sessionKey: newIdempotencyKey('create-session'),
        attemptKey: newIdempotencyKey('create-attempt'),
        sessionBody: context.sessionBody,
        attemptBody: retry
            ? AttemptCreate(sessionId: session!.id).toJson()
            : null,
        sessionId: retry ? session!.id : null,
        questionVersion: retry ? question!.version : null,
      );
      await source.prepareCreation(args.questionId, command);
      command = (await source.readCreation(args.questionId))!;
    }
    try {
      if (command.phase == 'session_prepared') {
        if (!_mayUseIdentity) return false;
        final created = await api.createSession(
          body: command.sessionRequest,
          idempotencyKey: command.sessionKey,
        );
        if (!_mayUseIdentity) return false;
        if (created.questionId != args.questionId ||
            created.questionVersion != context.question.version) {
          throw StateError('创建会话版本不符，旧稿已保留');
        }
        final next = _nextCreation(command, 'session_known', {
          'sessionId': created.id,
          'questionVersion': created.questionVersion,
        });
        await source.advanceCreation(
          args.questionId,
          next,
          expectedGeneration: command.generation,
        );
        command = next;
      }
      if (command.phase == 'session_known') {
        final next = _nextCreation(command, 'attempt_prepared', {
          'attemptBody': AttemptCreate(sessionId: command.sessionId!).toJson(),
        });
        await source.advanceCreation(
          args.questionId,
          next,
          expectedGeneration: command.generation,
        );
        command = next;
      }
      if (command.phase == 'attempt_prepared') {
        if (!_mayUseIdentity) return false;
        final created = await api.createAttempt(
          body: command.attemptRequest,
          idempotencyKey: command.attemptKey,
        );
        if (!_mayUseIdentity) return false;
        if (created.sessionId != command.sessionId) throw StateError('作答会话不符');
        final next = _nextCreation(command, 'attempt_known', {
          'attemptId': created.id,
        });
        await source.advanceCreation(
          args.questionId,
          next,
          expectedGeneration: command.generation,
        );
        command = next;
      }
      if (!_mayUseIdentity) return false;
      final freshSession = await api.getSession(sessionId: command.sessionId!);
      if (!_mayUseIdentity) return false;
      final freshAttempt = await api.getAttempt(attemptId: command.attemptId!);
      if (freshSession.questionId != args.questionId ||
          freshSession.questionVersion != context.question.version ||
          freshAttempt.sessionId != freshSession.id ||
          freshAttempt.status != AttemptStatus.draft ||
          freshSession.state == SessionState.done) {
        throw StateError('已创建的作答不可编辑，旧稿保留');
      }
      if (!_mayUseIdentity) return false;
      final version = _localVersion;
      final isRetry = context.trustedSessionId != null && !_unboundLocalScope;
      final targetData =
          (isRetry
                ? LocalDraft(
                    questionId: args.questionId,
                    savedAt: DateTime.now(),
                  ).toJson()
                : _snapshot().toJson())
            ..['sessionId'] = freshSession.id
            ..['attemptId'] = freshAttempt.id
            ..['baseRevision'] = freshAttempt.draftRevision;
      final target = LocalDraft.fromJson(targetData);
      if (_unboundLocalScope) {
        await source.writeDraft(
          LocalDraft.fromJson(
            _snapshot().toJson()
              ..['sessionId'] = null
              ..['attemptId'] = null,
          ),
        );
      }
      final targetStore = source.forAttempt(freshAttempt.id);
      await targetStore.writeQuestion(context.question);
      final activated = await source.attachCreation(
        target,
        intentId: command.intentId,
        expectedGeneration: command.generation,
      );
      if (!activated) {
        creationBlockedReason = '已选择其他草稿，本次创建结果已保留，未切换编辑器';
        return false;
      }
      if (!_mayUseIdentity) return false;
      if (retry && isRetry) {
        _workspaceGeneration++;
        _useInitialRoute = false;
        selfCheckBusy = false;
        selfCheckRemoteConflict = false;
        historicalReviewCompletion ??= reviewCompletion;
        reviewCompletion = null;
        reviewError = null;
        tutorBusy = false;
        _marksWrite = Future<void>.value();
      }
      drafts = targetStore;
      await drafts.claimScope(args.questionId);
      session = freshSession;
      attempt = freshAttempt;
      _unboundLocalScope = false;
      _attachedDurably = true;
      _workspace = await drafts.readWorkspaceContext(args.questionId);
      if (version == _localVersion) {
        _applyLocal(await drafts.readDraft(args.questionId) ?? target);
      }
      phase = SolvePhase.answering;
      await _reconcileDraft();
      return true;
    } on ApiException catch (error) {
      if (error.statusCode > 0 && error.statusCode < 500) {
        final current = command!;
        final blocked = _nextCreation(current, 'blocked', {
          'blockedReason': error.statusCode == 401
              ? 'authentication_required:${error.code}'
              : error.code,
          'resumePhase': current.phase,
        });
        await source.advanceCreation(
          args.questionId,
          blocked,
          expectedGeneration: current.generation,
        );
        creationBlockedReason = blocked.blockedReason;
      }
      rethrow;
    }
  }

  void _applyLocal(LocalDraft draft) {
    _selected
      ..clear()
      ..addAll(draft.selected);
    _blanks
      ..clear()
      ..addAll(draft.blanks);
    _parts
      ..clear()
      ..addAll(draft.parts);
    _cells
      ..clear()
      ..addAll(draft.cells);
    _steps
      ..clear()
      ..addAll(draft.steps);
    _stepsRevision += 1;
    ink.loadContract(draft.strokes);
    _serverRevision = draft.baseRevision;
    _localAttemptId = draft.attemptId;
    _localSessionId = draft.sessionId;
    // 没有对应作答的本机内容（离线时写的）一定还没同步过
    _dirtyRemote = draft.dirty || (draft.attemptId == null && draft.hasContent);
  }

  // ------------------------------------------------------------ 连上云端：会话与作答

  /// 保证云端有会话和一份未提交的作答。失败时（断网等）返回 false，并把状态设成离线。
  /// 已经提交之后只需要会话，不能再新建作答（再试一次由 [retry] 负责）。
  Future<bool> _attachRemote() async {
    if (!_mayUseIdentity) {
      authExpired = true;
      return false;
    }
    if (_attachedDurably &&
        session != null &&
        (phase == SolvePhase.submitted ||
            attempt?.status == AttemptStatus.draft)) {
      return true;
    }
    if (_attaching || phase == SolvePhase.failed) return false;
    _attaching = true;
    try {
      final activeEpoch = await drafts.readActiveEpoch(args.questionId);
      if (_workspace == null || creationBlockedReason != null) return false;
      if (_sessionRoute && session == null && _restoringRef == null) {
        final existing = await api.getSession(sessionId: args.sessionId!);
        if (!_mayUseIdentity) return false;
        if (existing.questionId != args.questionId ||
            existing.questionVersion != question!.version ||
            existing.origin != SessionOrigin.fromJson(args.origin) ||
            existing.reviewItemId != args.reviewItemId) {
          throw StateError('指定会话与当前题面或来源不符，保留原稿');
        }
        final selected =
            existing.firstSubmittedAttemptId ?? existing.activeAttemptId;
        if (selected != null) {
          _restoringRef = ActiveRef(
            sessionId: existing.id,
            attemptId: selected,
          );
        } else {
          if (existing.state == SessionState.done) {
            throw StateError('已结束会话缺少可回看的作答');
          }
          session = existing;
        }
      }
      final pending = await drafts.readCreation(args.questionId);
      if (pending != null && pending.phase != 'attached') {
        return await _runCreation(retry: session != null);
      }
      var resumed = false;
      if (session == null) {
        resumed = await _resumeActive();
      }
      if (!resumed && _restoringRef != null && session == null) {
        creationBlockedReason = '原会话不可恢复，请保留旧稿另开新版';
        return false;
      }
      if (_recoveryBlocked &&
          (session == null || attempt?.status != AttemptStatus.draft)) {
        return false;
      }
      if (attempt?.status == AttemptStatus.submitted &&
          needsSubmissionRecovery &&
          session?.state != SessionState.done) {
        _attachedDurably = true;
        return true;
      }
      if (attempt?.status == AttemptStatus.submitted ||
          session?.state == SessionState.done) {
        final generation = _workspaceGeneration;
        final origin = await drafts.readResourceOrigin(
          args.questionId,
          viewGeneration: generation,
        );
        final latest = session!;
        final selected = attempt!;
        await _restoreEvents();
        await _acceptResourceState(
          latest,
          events,
          origin,
          generation,
          verifiedAttempt: selected,
        );
        _attachedDurably = true;
        if (_isSubjective && phase == SolvePhase.submitted) {
          await loadSelfCheck();
        }
        return true;
      }
      if (session == null ||
          attempt == null ||
          attempt!.status != AttemptStatus.draft) {
        return await _runCreation(retry: session != null);
      }
      if (_disposed) return false;
      final targetStore = drafts.forAttempt(attempt!.id);
      if (_unboundLocalScope) {
        final version = _localVersion;
        final target = LocalDraft.fromJson(
          _snapshot().toJson()..['baseRevision'] = attempt!.draftRevision,
        );
        final sourceData = _snapshot().toJson()
          ..['attemptId'] = null
          ..['sessionId'] = null;
        await drafts.writeDraft(LocalDraft.fromJson(sourceData));
        if (question != null) await targetStore.writeQuestion(question!);
        final promoted = await drafts.promoteToAttempt(
          target,
          expectedActiveEpoch: activeEpoch,
        );
        if (!promoted) return false;
        if (_disposed) return false;
        drafts = targetStore;
        _unboundLocalScope = false;
        await drafts.claimScope(args.questionId);
        final persisted = await drafts.readDraft(args.questionId);
        if (!_disposed && version == _localVersion && persisted != null) {
          _applyLocal(persisted);
        }
      } else {
        drafts = targetStore;
        await drafts.claimScope(args.questionId);
      }
      await _reconcileDraft();
      if (question != null) await drafts.writeQuestion(question!);
      if (resumed) await _restoreEvents();
      final currentRef = await drafts.readActive(args.questionId);
      final activated =
          currentRef?.sessionId == session!.id &&
              currentRef?.attemptId == attempt!.id
          ? true
          : await drafts.writeActive(
              args.questionId,
              ActiveRef(sessionId: session!.id, attemptId: attempt!.id),
              expectedEpoch: activeEpoch,
            );
      if (!activated) {
        creationBlockedReason = '已选择其他草稿，未切换当前草稿指针';
        return false;
      }
      _attachedDurably = true;
      if (sync == SaveStatus.offline) {
        sync = _dirtyRemote ? SaveStatus.dirty : SaveStatus.saved;
      }
      return true;
    } on ApiException catch (error) {
      if (error.statusCode >= 400 &&
          error.statusCode < 500 &&
          error.statusCode != 401) {
        final command = await drafts.readWrite(args.questionId, 'draft_sync');
        if (_pending(command)) {
          await drafts.blockWrite(
            args.questionId,
            lane: 'draft_sync',
            intentId: command!.intentId,
            expectedGeneration: command.generation,
            reason: error.code,
            rejected: error.code == 'draft_revision_conflict',
          );
        }
      }
      _handleSyncError(error);
      return false;
    } catch (error) {
      actionError = error;
      localSaveFailed = true;
      sync = SaveStatus.offline;
      return false;
    } finally {
      _attaching = false;
      _notify();
    }
  }

  /// The explicit draft selector stays strict. A verified local recovery may
  /// reopen its submitted resource for reading, without treating GET as an ACK.
  Future<bool> _hasReadonlyRecovery(
    StudySession existing,
    ActiveRef active,
  ) async {
    if (_unboundLocalScope ||
        _workspace == null ||
        _workspace!.trustedSessionId != existing.id) {
      return false;
    }
    final origin = await drafts.readResourceOrigin(
      args.questionId,
      viewGeneration: _workspaceGeneration,
    );
    if (origin.owner != userId ||
        origin.questionId != existing.questionId ||
        origin.questionVersion != existing.questionVersion ||
        origin.sessionId != existing.id ||
        origin.attemptId != active.attemptId ||
        origin.origin != existing.origin.toJson() ||
        origin.reviewId != existing.reviewItemId) {
      return false;
    }
    final resourceView = await resources.readView(
      ResourceTarget.session(existing.id),
    );
    final terminal = resourceView?.session;
    if (terminal?.state == SessionState.done &&
        terminal!.id == existing.id &&
        terminal.questionId == existing.questionId &&
        terminal.questionVersion == existing.questionVersion &&
        terminal.origin == existing.origin &&
        terminal.reviewItemId == existing.reviewItemId) {
      return true;
    }
    final submit = await drafts.readWrite(args.questionId, 'submit');
    if (submit?.phase == 'acked' &&
        submit!.attemptId == active.attemptId &&
        submit.sessionId == existing.id &&
        submit.questionVersion == existing.questionVersion &&
        submit.result != null) {
      final acknowledged = SubmitResult.fromJson(submit.result!);
      if (acknowledged.attempt.id == active.attemptId &&
          acknowledged.attempt.status == AttemptStatus.submitted &&
          acknowledged.session.id == existing.id &&
          acknowledged.session.questionId == existing.questionId &&
          acknowledged.session.questionVersion == existing.questionVersion) {
        return true;
      }
    }
    final candidates = <ResourceCommand?>[
      await resources.read(ResourceTarget.session(existing.id)),
      if (existing.reviewItemId != null)
        await resources.read(ResourceTarget.review(existing.reviewItemId!)),
    ];
    return candidates.any(
      (command) =>
          _resourcePending(command) &&
          command!.source.owner == userId &&
          command.source.questionId == existing.questionId &&
          command.source.questionVersion == existing.questionVersion &&
          command.source.sessionId == existing.id &&
          command.source.origin == existing.origin.toJson() &&
          command.source.reviewId == existing.reviewItemId,
    );
  }

  /// 本机记着一个进行中的会话，并且云端还认：接着用。
  Future<bool> _resumeActive() async {
    final active =
        _useInitialRoute && args.sessionId != null && args.attemptId != null
        ? ActiveRef(sessionId: args.sessionId!, attemptId: args.attemptId!)
        : _restoringRef ?? await drafts.readActive(args.questionId);
    if (active == null) return false;
    try {
      final existing = await api.getSession(sessionId: active.sessionId);
      if (!_mayUseIdentity) return false;
      final sameKind =
          existing.origin == SessionOrigin.fromJson(args.origin) &&
          existing.reviewItemId == args.reviewItemId;
      if (!sameKind) {
        if (_explicitRoute) {
          _recoveryBlocked = true;
          throw StateError('所选草稿不能继续编辑，请重新选择');
        }
        creationBlockedReason = '原会话来源不同，保留旧稿后可另开新版';
        return false;
      }
      final selected = await api.getAttempt(attemptId: active.attemptId);
      if (selected.sessionId != existing.id ||
          existing.questionId != args.questionId) {
        throw StateError('所选草稿不属于当前题目或会话');
      }
      final readonlyRecovery =
          (_sessionRoute && selected.status == AttemptStatus.submitted) ||
          await _hasReadonlyRecovery(existing, active);
      if (existing.state == SessionState.done &&
          !needsSubmissionRecovery &&
          !readonlyRecovery) {
        if (_explicitRoute) {
          _recoveryBlocked = true;
          throw StateError('所选草稿不能继续编辑，请重新选择');
        }
        creationBlockedReason = '原会话已完成，保留旧稿后可另开新版';
        return false;
      }
      if (_explicitRoute &&
          selected.status != AttemptStatus.draft &&
          !needsSubmissionRecovery &&
          !readonlyRecovery) {
        _recoveryBlocked = true;
        throw StateError('所选草稿已经提交，请重新选择');
      }
      session = existing;
      attempt = selected;
      return true;
    } on ApiException catch (error) {
      if (_explicitRoute) rethrow;
      if (error.isNetwork ||
          error.statusCode == 401 ||
          error.statusCode >= 500) {
        rethrow;
      }
      creationBlockedReason = '原会话或作答已不可提供，旧稿保留；不会自动另开会话';
      return false;
    }
  }

  /// 本机内容与刚连上的作答对不对得上，决定是推送、采用云端还是保持。
  Future<void> _reconcileDraft() async {
    if (_recoveryBlocked || sync == SaveStatus.conflict) return;
    final current = attempt!;
    final hasLocalContent =
        _selected.isNotEmpty ||
        _blanks.values.any((v) => v.trim().isNotEmpty) ||
        _hasPartsText ||
        _hasCellsText ||
        _steps.any((s) => !s.isBlank) ||
        ink.hasInk;
    if (_localAttemptId == current.id) {
      // 本机草稿就是这份作答的草稿。本机没有未同步的改动、而云端往前走了（别处写过）：采用云端。
      // 本机有未同步的改动：保留，版本对不上时同步会走冲突流程。
      if (!_dirtyRemote && current.draftRevision != _serverRevision) {
        await _adoptServerDraft();
      }
    } else {
      // 本机内容不属于这份作答（离线时写的，或作答被换过）：以云端版本为基准，把本机内容推上去
      _serverRevision = current.draftRevision;
      if (hasLocalContent) {
        _dirtyRemote = true;
      } else if (current.draftRevision > 0) {
        await _adoptServerDraft();
      }
    }
    _localAttemptId = current.id;
  }

  Future<ResourceEventRefresh> _readResourceEvents(String id) async {
    final result = ResourceEventRefresh(id);
    while (true) {
      final cursor = result.nextAfterSeq;
      result.addPage(
        await api.listSessionEvents(
          sessionId: id,
          afterSeq: cursor,
          limit: 200,
        ),
      );
      if (result.complete) return result;
      if (result.nextAfterSeq <= cursor) throw StateError('事件分页尚未完整，原动作保留');
    }
  }

  Future<void> _restoreCachedTutorHistory() async {
    if (_unboundLocalScope || _workspace?.trustedSessionId == null) return;
    final generation = _workspaceGeneration;
    try {
      final origin = await drafts.readResourceOrigin(
        args.questionId,
        viewGeneration: generation,
      );
      final view = await resources.readView(
        ResourceTarget.session(origin.sessionId),
      );
      final cached = view?.session;
      if (cached == null ||
          cached.id != origin.sessionId ||
          cached.questionId != question?.id ||
          cached.questionVersion != question?.version ||
          cached.origin.toJson() != origin.origin ||
          cached.reviewItemId != origin.reviewId) {
        return;
      }
      final history = view!.events;
      if (history.any(
        (event) =>
            event.sessionId != cached.id ||
            event.meta.questionId != cached.questionId ||
            event.meta.questionVersion != cached.questionVersion,
      )) {
        return;
      }
      if (!_currentWorkspace(generation)) return;
      events = history;
      _cachedEventSessionId = cached.id;
    } catch (error) {
      if (_currentWorkspace(generation)) actionError = error;
    }
  }

  Future<void> _restoreEvents() async {
    final generation = _workspaceGeneration;
    try {
      final history = await _readResourceEvents(session!.id);
      if (!_currentWorkspace(generation)) return;
      events = history.events;
    } catch (error) {
      if (_currentWorkspace(generation)) actionError = error;
    }
  }

  Future<void> _loadResourceCommands() async {
    final generation = _workspaceGeneration;
    final id = session!.id;
    try {
      final tutor = await resources.read(ResourceTarget.session(id));
      final review = isRetest && args.reviewItemId != null
          ? await resources.read(ResourceTarget.review(args.reviewItemId!))
          : null;
      if (!_currentWorkspace(generation) || session?.id != id) return;
      pendingTutor = _resourcePending(tutor) ? tutor : null;
      pendingReview = _resourcePending(review) ? review : null;
      if (isRetest && args.reviewItemId != null) {
        final state = await api.getReviewState(reviewId: args.reviewItemId!);
        if (!_currentWorkspace(generation)) return;
        reviewState = state;
      }
    } catch (error) {
      if (_currentWorkspace(generation)) actionError = error;
    }
  }

  Future<T> _inResourceScope<T>(
    ResourceTarget target,
    Future<T> Function() work,
  ) async {
    final queues = _resourceQueues[resources.store] ??= {};
    final key = '$userId/${target.scope}';
    final previous = queues[key];
    final done = Completer<void>();
    queues[key] = done.future;
    if (previous != null) await previous;
    try {
      return await work();
    } finally {
      done.complete();
      if (identical(queues[key], done.future)) queues.remove(key);
    }
  }

  Future<bool> _resourceViewCurrent(
    ResourceSourceGuard captured,
    int generation,
  ) async {
    if (!_currentWorkspace(generation)) return false;
    try {
      final current = await drafts.readResourceOrigin(
        args.questionId,
        viewGeneration: generation,
      );
      return _currentWorkspace(generation) &&
          current.sessionId == captured.sessionId &&
          current.questionVersion == captured.questionVersion &&
          current.workspaceId == captured.workspaceId &&
          current.activeEpoch == captured.activeEpoch;
    } catch (_) {
      return false;
    }
  }

  Future<void> _acceptResourceState(
    StudySession latest,
    List<TutorEvent> history,
    ResourceSourceGuard viewOrigin,
    int generation, {
    Attempt? verifiedAttempt,
  }) async {
    if (!await _resourceViewCurrent(viewOrigin, generation)) return;
    final selected =
        verifiedAttempt ??
        await api.getAttempt(attemptId: viewOrigin.attemptId);
    if (selected.id != viewOrigin.attemptId ||
        selected.sessionId != latest.id ||
        latest.id != viewOrigin.sessionId ||
        latest.questionId != viewOrigin.questionId ||
        latest.questionVersion != viewOrigin.questionVersion) {
      throw StateError('刷新作答来源不符');
    }
    if (!await _resourceViewCurrent(viewOrigin, generation)) return;
    if (latest.state == SessionState.done ||
        selected.status == AttemptStatus.submitted) {
      final stored = await drafts.readDraft(args.questionId);
      final known = await drafts.readWrite(args.questionId, 'submit');
      final ownAcknowledgement =
          known?.phase == 'acked' &&
          known!.attemptId == selected.id &&
          known.sessionId == latest.id &&
          known.questionVersion == latest.questionVersion;
      final acknowledgedAnswerMatches =
          ownAcknowledgement &&
          known.result != null &&
          jsonEquals(
            selected.answer?.toJson(),
            SubmitResult.fromJson(known.result!).attempt.answer?.toJson(),
          );
      final sameAcknowledgedAnswer =
          acknowledgedAnswerMatches &&
          ((stored == null && _localVersion == 0) ||
              _sameSnapshot(_snapshot(), known.sourceSnapshot));
      if (sameAcknowledgedAnswer &&
          selected.status == AttemptStatus.submitted) {
        _applyLocal(known.sourceSnapshot);
        evaluation = selected.evaluation;
        phase = SolvePhase.submitted;
        _dirtyRemote = false;
        sync = SaveStatus.saved;
      } else {
        // A GET establishes remote resource state, never the receipt for local B.
        // Freeze B before awaiting its final local write; do not close/delete it.
        ink.endStroke();
        ink.endErase();
        final localInput = _snapshot();
        final preserve =
            phase == SolvePhase.answering &&
            (stored != null || _localVersion > 0 || localInput.hasContent);
        phase = SolvePhase.readonly;
        _notify();
        evaluation = null;
        selfCheck = null;
        _marks.clear();
        if (preserve) {
          try {
            await drafts.writeDraft(localInput);
            localSaveFailed = false;
          } catch (_) {
            localSaveFailed = true;
          }
        }
        sync = _dirtyRemote ? SaveStatus.dirty : SaveStatus.saved;
      }
      _autosaveTimer?.cancel();
      _autosaveTimer = null;
      _syncTimer?.cancel();
      _syncTimer = null;
      _stopRetry();
      _stopwatch.stop();
    }
    if (!await _resourceViewCurrent(viewOrigin, generation)) return;
    session = latest;
    attempt = selected;
    events = history;
    _notify();
  }

  Future<void> _adoptServerDraft() async {
    final draft = await api.getDraft(attemptId: attempt!.id);
    _applyServerDraft(draft);
  }

  void _applyServerDraft(Draft draft) {
    final answer = draft.answer;
    _selected
      ..clear()
      ..addAll(answer?.selectedOptions ?? const []);
    _blanks
      ..clear()
      ..addEntries(
        (answer?.blanks ?? const []).map((b) => MapEntry(b.key, b.value)),
      );
    _parts
      ..clear()
      ..addEntries(
        (answer?.parts ?? const []).map((p) => MapEntry(p.key, p.text)),
      );
    _cells
      ..clear()
      ..addEntries(
        (answer?.cells ?? const []).map(
          (c) => MapEntry('${c.table}.${c.row}.${c.col}', c.value),
        ),
      );
    _steps
      ..clear()
      ..addAll(
        (answer?.steps ?? const []).map(
          (s) => ProofStepDraft(text: s.text, reason: s.reason),
        ),
      );
    _ensureStep();
    _stepsRevision += 1;
    ink.loadContract(draft.strokes);
    _serverRevision = draft.revision;
    _dirtyRemote = false;
  }

  // ------------------------------------------------------------ 学生的输入

  void selectOption(String key) {
    if (!hasVerifiedWorkspace) return;
    if (phase != SolvePhase.answering || !hasVerifiedWorkspace) return;
    if (_mode == AnswerMode.singleChoice) {
      if (_selected.length == 1 && _selected.contains(key)) return;
      _selected
        ..clear()
        ..add(key);
    } else if (!_selected.remove(key)) {
      _selected.add(key);
    }
    _onChanged();
  }

  void setBlank(String key, String value) {
    if (phase != SolvePhase.answering || !hasVerifiedWorkspace) return;
    final bounded = value.length > 200 ? value.substring(0, 200) : value;
    if (bounded.isEmpty) {
      _blanks.remove(key);
    } else {
      _blanks[key] = bounded;
    }
    _onChanged();
  }

  /// 解答题某一小问的文字。只认题目里有的小问；超过 4000 字的部分截掉。
  void setPart(String key, String value) {
    if (phase != SolvePhase.answering || !hasVerifiedWorkspace) return;
    if (!(question?.content.subquestions.any((s) => s.key == key) ?? false)) {
      return;
    }
    final bounded = value.length > 4000 ? value.substring(0, 4000) : value;
    if (bounded.isEmpty) {
      _parts.remove(key);
    } else {
      _parts[key] = bounded;
    }
    _onChanged();
  }

  /// 实验题数据表里留空的格子：(表键, 行键, 列键)，按表、行、列的顺序。
  List<(String, String, String)> get _blankCells => [
    for (final table in question?.content.dataTables ?? const <DataTable>[])
      for (final row in table.rows)
        for (final cell in row.cells)
          if (cell.text == null) (table.key, row.key, cell.col),
  ];

  /// 实验题数据表里的一个格子。只认题目里留空的格子；超过 40 个字的部分截掉。
  void setCell(String table, String row, String col, String value) {
    if (phase != SolvePhase.answering || !hasVerifiedWorkspace) return;
    if (!_blankCells.contains((table, row, col))) return;
    final bounded = value.length > 40 ? value.substring(0, 40) : value;
    final key = '$table.$row.$col';
    if (bounded.isEmpty) {
      _cells.remove(key);
    } else {
      _cells[key] = bounded;
    }
    _onChanged();
  }

  /// 证明题答题期间至少有一张卡片，学生一打开就能写。
  void _ensureStep() {
    if (_mode == AnswerMode.proof && _steps.isEmpty) {
      _steps.add(const ProofStepDraft());
      _stepsRevision += 1;
    }
  }

  /// 证明题第 [index] 步写了什么。超过 1000 字的部分截掉。
  void setStepText(int index, String value) {
    if (phase != SolvePhase.answering ||
        !hasVerifiedWorkspace ||
        index < 0 ||
        index >= _steps.length) {
      return;
    }
    final bounded = value.length > maxStepText
        ? value.substring(0, maxStepText)
        : value;
    _steps[index] = _steps[index].copyWith(text: bounded);
    _onChanged();
  }

  /// 证明题第 [index] 步的依据。超过 400 字的部分截掉。
  void setStepReason(int index, String value) {
    if (phase != SolvePhase.answering ||
        !hasVerifiedWorkspace ||
        index < 0 ||
        index >= _steps.length) {
      return;
    }
    final bounded = value.length > maxStepReason
        ? value.substring(0, maxStepReason)
        : value;
    _steps[index] = _steps[index].copyWith(reason: bounded);
    _onChanged();
  }

  /// 在最后添加一张空白的卡片。最多 30 步。
  void addStep() {
    if (!canAddStep) return;
    _steps.add(const ProofStepDraft());
    _stepsRevision += 1;
    _onChanged();
  }

  /// 删掉第 [index] 步。只剩一步时把它清成空白，不让卡片消失。
  void removeStep(int index) {
    if (phase != SolvePhase.answering ||
        !hasVerifiedWorkspace ||
        index < 0 ||
        index >= _steps.length) {
      return;
    }
    if (_steps.length == 1) {
      _steps[0] = const ProofStepDraft();
    } else {
      _steps.removeAt(index);
    }
    _stepsRevision += 1;
    _onChanged();
  }

  /// 把第 [index] 步往前（delta=-1）或往后（delta=1）挪一位。到头了就什么都不做。
  void moveStep(int index, int delta) {
    final target = index + delta;
    if (phase != SolvePhase.answering ||
        !hasVerifiedWorkspace ||
        index < 0 ||
        index >= _steps.length ||
        target < 0 ||
        target >= _steps.length) {
      return;
    }
    final step = _steps.removeAt(index);
    _steps.insert(target, step);
    _stepsRevision += 1;
    _onChanged();
  }

  void _onChanged() {
    if (phase != SolvePhase.answering || !hasVerifiedWorkspace) return;
    _localVersion += 1;
    _dirtyRemote = true;
    if (!_recoveryBlocked &&
        sync != SaveStatus.conflict &&
        sync != SaveStatus.offline) {
      sync = SaveStatus.dirty;
    }
    _autosaveTimer ??= Timer(autosaveDelay, () {
      _autosaveTimer = null;
      unawaited(_persistLocal());
    });
    _scheduleSync();
    _notify();
  }

  // ------------------------------------------------------------ 本机保存

  LocalDraft _snapshot() => LocalDraft(
    questionId: args.questionId,
    sessionId: session?.id ?? _localSessionId,
    attemptId: attempt?.id ?? _localAttemptId,
    baseRevision: _serverRevision,
    dirty: _dirtyRemote,
    selected: _selected.toList(),
    blanks: Map.of(_blanks),
    parts: Map.of(_parts),
    cells: Map.of(_cells),
    steps: List.of(_steps),
    strokes: ink.hasInk ? ink.toContract() : null,
    savedAt: DateTime.now().toUtc(),
  );

  Future<void> _persistLocal() async {
    if ((phase != SolvePhase.answering && phase != SolvePhase.readonly) ||
        !hasVerifiedWorkspace) {
      return;
    }
    final generation = _workspaceGeneration;
    try {
      await drafts.writeDraft(_snapshot());
      if (!_currentWorkspace(generation)) return;
      localSaveFailed = false;
    } catch (_) {
      if (!_currentWorkspace(generation)) return;
      localSaveFailed = true;
    }
    _notify();
  }

  /// 立刻把草稿存到本机（应用切到后台、离开页面时）。不碰网络。
  Future<void> flushNow() async {
    _autosaveTimer?.cancel();
    _autosaveTimer = null;
    await _persistLocal();
  }

  // ------------------------------------------------------------ 云端同步

  void _scheduleSync() {
    _syncTimer?.cancel();
    _syncTimer = Timer(syncDelay, () => unawaited(_syncDraft()));
  }

  AnswerPayload? _draftAnswer() {
    final mode = _mode;
    if (mode == AnswerMode.fill) {
      final blanks = [
        for (final blank in question!.content.blanks)
          if ((_blanks[blank.key] ?? '').isNotEmpty)
            AnswerBlank(key: blank.key, value: _blanks[blank.key]!),
      ];
      return blanks.isEmpty ? null : AnswerPayload(blanks: blanks);
    }
    if (mode == AnswerMode.written) {
      final parts = _partsInOrder(trim: false);
      return parts.isEmpty ? null : AnswerPayload(parts: parts);
    }
    if (mode == AnswerMode.experiment) {
      final cells = _cellsInOrder(trim: false);
      final parts = _partsInOrder(trim: false);
      if (cells.isEmpty && parts.isEmpty) return null;
      return AnswerPayload(
        cells: cells.isEmpty ? null : cells,
        parts: parts.isEmpty ? null : parts,
      );
    }
    if (mode == AnswerMode.proof) {
      final steps = _stepsToSend(trim: false);
      return steps.isEmpty ? null : AnswerPayload(steps: steps);
    }
    if (_selected.isEmpty) return null;
    final options = question!.content.options
        .map((o) => o.key)
        .where(_selected.contains)
        .toList();
    return AnswerPayload(selectedOptions: options);
  }

  /// 写了东西的步骤（文字或依据有一样不是空白），按学生排的顺序；整张卡片是空白的不发。
  List<AnswerStep> _stepsToSend({required bool trim}) => [
    for (final step in _steps)
      if (!step.isBlank)
        AnswerStep(
          text: trim ? step.text.trim() : step.text,
          reason: trim ? step.reason.trim() : step.reason,
        ),
  ];

  /// 有文字的小问，按题目里的顺序。
  List<AnswerPart> _partsInOrder({required bool trim}) => [
    for (final sub in question!.content.subquestions)
      if ((_parts[sub.key] ?? '').trim().isNotEmpty)
        AnswerPart(
          key: sub.key,
          text: trim ? _parts[sub.key]!.trim() : _parts[sub.key]!,
        ),
  ];

  /// 填了的格子，按表、行、列的顺序。
  List<AnswerCell> _cellsInOrder({required bool trim}) => [
    for (final (table, row, col) in _blankCells)
      if ((_cells['$table.$row.$col'] ?? '').trim().isNotEmpty)
        AnswerCell(
          table: table,
          row: row,
          col: col,
          value: trim
              ? _cells['$table.$row.$col']!.trim()
              : _cells['$table.$row.$col']!,
        ),
  ];

  StrokeDoc? _draftStrokes() => ink.hasInk ? ink.toContract() : null;

  bool _sameContent(Draft server) =>
      jsonEquals(_draftAnswer()?.toJson(), server.answer?.toJson()) &&
      jsonEquals(_draftStrokes()?.toJson(), server.strokes?.toJson());

  bool _pending(WriteCommand? command) =>
      command != null &&
      command.phase != 'acked' &&
      command.phase != 'rejected';

  bool _sameSnapshot(LocalDraft left, LocalDraft right) =>
      jsonEquals(left.selected, right.selected) &&
      jsonEquals(left.blanks, right.blanks) &&
      jsonEquals(left.parts, right.parts) &&
      jsonEquals(left.cells, right.cells) &&
      jsonEquals(
        left.steps.map((s) => s.toJson()).toList(),
        right.steps.map((s) => s.toJson()).toList(),
      ) &&
      jsonEquals(left.strokes?.toJson(), right.strokes?.toJson());

  Future<WriteCommand> _prepareSync(LocalDraft snapshot) async {
    final existing = await drafts.readWrite(args.questionId, 'draft_sync');
    if (existing?.phase == 'blocked') {
      throw StateError('原草稿同步已阻断，原文保留：${existing!.blockedReason}');
    }
    if (_pending(existing)) return existing!;
    return drafts.prepareWrite(
      args.questionId,
      lane: 'draft_sync',
      sourceSnapshot: snapshot,
      body: _syncBody(snapshot),
    );
  }

  Map<String, dynamic> _syncBody(LocalDraft snapshot) {
    final payload = AnswerPayload(
      selectedOptions: snapshot.selected.isEmpty ? null : snapshot.selected,
      blanks: snapshot.blanks.isEmpty
          ? null
          : [
              for (final e in snapshot.blanks.entries)
                AnswerBlank(key: e.key, value: e.value),
            ],
      parts: snapshot.parts.isEmpty
          ? null
          : [
              for (final e in snapshot.parts.entries)
                if (e.value.trim().isNotEmpty)
                  AnswerPart(key: e.key, text: e.value),
            ],
      cells: snapshot.cells.isEmpty
          ? null
          : [
              for (final e in snapshot.cells.entries)
                if (e.value.trim().isNotEmpty)
                  AnswerCell(
                    table: e.key.split('.')[0],
                    row: e.key.split('.')[1],
                    col: e.key.split('.')[2],
                    value: e.value,
                  ),
            ],
      steps: snapshot.steps.isEmpty
          ? null
          : [
              for (final step in snapshot.steps)
                AnswerStep(text: step.text, reason: step.reason),
            ],
    );
    final answer = payload.toJson();
    answer.removeWhere((key, value) => value is List && value.isEmpty);
    for (final field in ['parts', 'blanks']) {
      if (answer[field] is! List) continue;
      final order = field == 'parts'
          ? question!.content.subquestions.map((s) => s.key).toList()
          : question!.content.blanks.map((b) => b.key).toList();
      (answer[field] as List).sort(
        (a, b) => order
            .indexOf(a['key'] as String)
            .compareTo(order.indexOf(b['key'] as String)),
      );
    }
    if (answer['cells'] is List) {
      final order = _blankCells.map((c) => '${c.$1}.${c.$2}.${c.$3}').toList();
      String cellKey(dynamic c) => '${c['table']}.${c['row']}.${c['col']}';
      (answer['cells'] as List).sort(
        (a, b) =>
            order.indexOf(cellKey(a)).compareTo(order.indexOf(cellKey(b))),
      );
    }
    if (answer['steps'] is List) {
      answer['steps'] = (answer['steps'] as List)
          .where(
            (s) =>
                (s['text'] as String).trim().isNotEmpty ||
                (s['reason'] as String? ?? '').trim().isNotEmpty,
          )
          .toList();
      if ((answer['steps'] as List).isEmpty) answer.remove('steps');
    }
    return DraftSync(
      baseRevision: _serverRevision,
      answer: answer.isEmpty ? null : AnswerPayload.fromJson(answer),
      strokes: snapshot.strokes,
    ).toJson();
  }

  Future<bool> _syncDraft({
    bool force = false,
    bool resolving = false,
    bool submissionDependency = false,
  }) async {
    if (_openingWorkspace ||
        (needsSubmissionRecovery && !submissionDependency) ||
        _syncing ||
        (recoveryBusy && !resolving) ||
        _recoveryBlocked ||
        (phase != SolvePhase.answering &&
            !(submissionDependency && phase == SolvePhase.readonly)) ||
        sync == SaveStatus.conflict) {
      return false;
    }
    if (!_dirtyRemote && !force) return true;
    final generation = _workspaceGeneration;
    if (!await _attachRemote() ||
        !_currentWorkspace(generation) ||
        _openingWorkspace) {
      return false;
    }
    if ((phase != SolvePhase.answering &&
            !(submissionDependency && phase == SolvePhase.readonly)) ||
        _recoveryBlocked ||
        sync == SaveStatus.conflict) {
      return false;
    }

    if (_syncing) return false;
    _syncing = true;
    final completion = Completer<void>();
    _syncCompletion = completion;
    sync = SaveStatus.saving;
    _notify();
    final version = _localVersion;
    try {
      await drafts.writeDraft(_snapshot());
      var command = await _prepareSync(_snapshot());
      final saved = command.result != null
          ? Draft.fromJson(command.result!)
          : await api.syncDraft(
              attemptId: command.attemptId,
              body: DraftSync.fromJson(command.body!),
              idempotencyKey: command.idempotencyKey,
            );
      if (!_currentWorkspace(generation)) return false;
      if (command.result == null) {
        command = await drafts.recordWriteResult(
          args.questionId,
          lane: 'draft_sync',
          intentId: command.intentId,
          expectedGeneration: command.generation,
          result: saved.toJson(),
        );
      }
      // Capture any edits made while the request was in flight before ACK.
      await drafts.writeDraft(_snapshot());
      final ack = await drafts.ackDraftSync(
        args.questionId,
        intentId: command.intentId,
        expectedGeneration: command.generation,
      );
      if (!_currentWorkspace(generation)) return false;
      _serverRevision = _serverRevision > ack.revision
          ? _serverRevision
          : ack.revision;
      if (_localVersion == version && ack.current) {
        _dirtyRemote = false;
        sync = SaveStatus.saved;
      } else {
        // 同步的过程中又有新的改动：下一轮再同步
        sync = SaveStatus.dirty;
        _scheduleSync();
      }
      _stopRetry();
      await _persistLocal();
      return true;
    } on ApiException catch (error) {
      if (!_currentWorkspace(generation)) return false;
      if (error.statusCode >= 400 &&
          error.statusCode < 500 &&
          error.statusCode != 401) {
        final command = await drafts.readWrite(args.questionId, 'draft_sync');
        if (_pending(command)) {
          await drafts.blockWrite(
            args.questionId,
            lane: 'draft_sync',
            intentId: command!.intentId,
            expectedGeneration: command.generation,
            reason: error.code,
            rejected: error.code == 'draft_revision_conflict',
          );
        }
      }
      _handleSyncError(error);
      return false;
    } catch (error) {
      if (!_currentWorkspace(generation)) return false;
      actionError = error;
      localSaveFailed = true;
      sync = SaveStatus.offline;
      return false;
    } finally {
      if (!completion.isCompleted) completion.complete();
      if (_currentWorkspace(generation)) {
        _syncing = false;
        _syncCompletion = null;
        _notify();
      }
    }
  }

  void _handleSyncError(ApiException error) {
    if (_recoveryBlocked) {
      _checkAuth(error);
      sync = SaveStatus.conflict;
      _stopRetry();
      return;
    }
    if (error.code == 'draft_revision_conflict') {
      _onConflict(error);
    } else if (error.statusCode == 401) {
      _expire();
    } else if (error.isNetwork || error.statusCode >= 500) {
      sync = SaveStatus.offline;
      _startRetry();
    } else {
      // 其他 4xx（例如作答已经提交）：不是重试能解决的，交给界面显示
      actionError = error;
      sync = SaveStatus.dirty;
    }
  }

  void _onConflict(ApiException error) {
    final raw = error.details['server_draft'];
    if (raw is Map) {
      final server = Draft.fromJson(Map<String, dynamic>.from(raw));
      if (_sameContent(server)) {
        // 云端已经是同样的内容（例如上次的同步成功了、响应丢了）：悄悄对上版本，不打扰学生
        _serverRevision = server.revision;
        _dirtyRemote = false;
        sync = SaveStatus.saved;
        unawaited(_persistLocal());
        return;
      }
      conflictServerDraft = server;
      _conflictWrite = _archiveConflict(server);
    }
    sync = SaveStatus.conflict;
    _recoveryBlocked = true;
    _stopRetry();
  }

  /// 保留本地稿：以云端当前版本为基准重新同步，覆盖云端。
  Future<void> resolveConflictCreateCopy() async {
    if (recoveryBusy || !_mayUseIdentity) return;
    final sourceStore = drafts;
    final version = _localVersion;
    try {
      final activeEpoch = await sourceStore.readActiveEpoch(args.questionId);
      var pending = await sourceStore.readPendingCopy(args.questionId);
      if (pending == null) {
        final server = conflictServerDraft;
        if (server == null || !await _prepareResolution(server)) return;
        pending = PendingDraftCopy(
          snapshot: _snapshot(),
          sourceAttemptId: server.attemptId,
          observedRevision: server.revision,
          idempotencyKey: newIdempotencyKey('draft-copy'),
          recoveryGeneration: _recoveryGeneration!,
        );
        await sourceStore.savePendingCopy(args.questionId, pending);
        pending = (await sourceStore.readPendingCopy(args.questionId))!;
        if (pending.activationEpoch != activeEpoch) return;
      } else {
        recoveryBusy = true;
        _notify();
      }
      // The pending request is immutable, but edits made since it was created
      // must be durable in the source slot before opening its older copy.
      await sourceStore.writeDraft(_snapshot());
      localSaveFailed = false;
      if (!_mayUseIdentity) return;
      final payload = pending.snapshot.asServer();
      final result = await api.createDraftCopy(
        attemptId: pending.sourceAttemptId,
        body: DraftCopyCreate(
          sourceRevision: pending.observedRevision,
          answer: payload.answer,
          strokes: payload.strokes,
        ),
        idempotencyKey: pending.idempotencyKey,
      );
      if (!_mayUseIdentity) return;
      final refreshed = await api.getSession(sessionId: result.session.id);
      if (!_mayUseIdentity) return;
      final currentAttempt = await api.getAttempt(attemptId: result.attempt.id);
      if (currentAttempt.sessionId != refreshed.id ||
          refreshed.questionId != args.questionId) {
        throw StateError('副本与会话或题目不匹配，输入已保留');
      }
      if (currentAttempt.status != AttemptStatus.draft ||
          refreshed.state == SessionState.done) {
        throw StateError('副本已提交或会话已结束，未切换编辑器；本机输入保留');
      }
      final currentDraft = currentAttempt.draftRevision == result.draft.revision
          ? result.draft
          : await api.getDraft(attemptId: currentAttempt.id);
      final data = LocalDraft.fromServer(args.questionId, currentDraft).toJson()
        ..['sessionId'] = refreshed.id;
      final copy = LocalDraft.fromJson(data);
      selectableCopy = ActiveRef(
        sessionId: refreshed.id,
        attemptId: currentAttempt.id,
      );
      _selectableCopyKey = pending.idempotencyKey;
      _selectableCopySource = sourceStore;
      final completed = await sourceStore.completePendingCopy(
        args.questionId,
        idempotencyKey: pending.idempotencyKey,
        copy: copy,
      );
      final alreadyActive = await sourceStore.readActive(args.questionId);
      if (pending.activationEpoch != null &&
          alreadyActive?.attemptId == result.attempt.id &&
          alreadyActive?.sessionId == refreshed.id) {
        await sourceStore.acknowledgePendingCopy(
          args.questionId,
          idempotencyKey: pending.idempotencyKey,
        );
        actionError = StateError('副本已激活，旧稿输入仍保留；请从云端草稿继续');
        return;
      }
      if (!completed) {
        actionError = StateError('副本已留档，当前草稿已改变；请从云端草稿选择副本');
        return;
      }
      // Persist the new ID before changing editors. A late result only records a reference.
      if (_disposed || version != _localVersion) return;
      final activated = await sourceStore.writeActive(
        args.questionId,
        ActiveRef(sessionId: result.session.id, attemptId: result.attempt.id),
        expectedEpoch: pending.activationEpoch ?? -1,
      );
      if (!activated) return;
      if (_disposed || version != _localVersion) return;
      final targetStore = sourceStore.forAttempt(result.attempt.id);
      await targetStore.claimScope(args.questionId);
      if (question != null) await targetStore.writeQuestion(question!);
      if (_workspace != null) {
        await targetStore.saveWorkspaceContext(
          args.questionId,
          DraftWorkspaceContext(
            workspaceId: result.attempt.id,
            question: question!,
            sessionBody: _workspace!.sessionBody,
            trustedSessionId: refreshed.id,
          ),
        );
      }
      await sourceStore.acknowledgePendingCopy(
        args.questionId,
        idempotencyKey: pending.idempotencyKey,
      );
      if (_disposed || version != _localVersion) return;
      drafts = targetStore;
      _workspace = await drafts.readWorkspaceContext(args.questionId);
      session = refreshed;
      attempt = currentAttempt;
      _attachedDurably = true;
      _applyLocal(await targetStore.readDraft(args.questionId) ?? copy);
      conflictServerDraft = null;
      _recoveryBlocked = false;
      _recoveryGeneration = null;
      recoveryCopies = const [];
      localSaveFailed = false;
      sync = _dirtyRemote ? SaveStatus.dirty : SaveStatus.saved;
      if (_dirtyRemote) _scheduleSync();
      actionError = null;
      selectableCopy = null;
    } catch (error) {
      actionError = error;
      if (error is ApiException) {
        _checkAuth(error);
      } else {
        localSaveFailed = true;
      }
    } finally {
      recoveryBusy = false;
      _notify();
    }
  }

  /// 保留本地稿：以云端当前版本为基准重新同步，覆盖云端。
  Future<void> openCreatedCopy() async {
    final ref = selectableCopy,
        key = _selectableCopyKey,
        source = _selectableCopySource;
    if (ref == null ||
        key == null ||
        source == null ||
        recoveryBusy ||
        _attaching ||
        _syncing ||
        submitting ||
        _disposed) {
      return;
    }
    recoveryBusy = true;
    final version = _localVersion;
    _notify();
    try {
      final epoch = await source.readActiveEpoch(args.questionId);
      await drafts.writeDraft(_snapshot());
      final currentSession = await api.getSession(sessionId: ref.sessionId);
      final currentAttempt = await api.getAttempt(attemptId: ref.attemptId);
      final fixedQuestion = await api.getSessionQuestion(
        sessionId: ref.sessionId,
      );
      if (currentSession.questionId != args.questionId ||
          fixedQuestion.id != args.questionId ||
          fixedQuestion.version != currentSession.questionVersion ||
          currentAttempt.sessionId != ref.sessionId ||
          currentAttempt.status != AttemptStatus.draft ||
          currentSession.state == SessionState.done) {
        throw StateError('该副本不能继续编辑，源稿保留');
      }
      final remote = await api.getDraft(attemptId: ref.attemptId);
      if (_disposed || version != _localVersion) return;
      final target = source.forAttempt(ref.attemptId);
      await target.claimScope(args.questionId);
      final existing = await target.readDraft(args.questionId);
      if (existing == null) {
        await target.writeDraft(
          LocalDraft.fromJson(
            LocalDraft.fromServer(args.questionId, remote).toJson()
              ..['sessionId'] = ref.sessionId,
          ),
        );
      }
      await target.writeQuestion(fixedQuestion);
      await target.saveWorkspaceContext(
        args.questionId,
        DraftWorkspaceContext(
          workspaceId: ref.attemptId,
          question: fixedQuestion,
          trustedSessionId: ref.sessionId,
          sessionBody: SessionCreate(
            questionId: args.questionId,
            origin: currentSession.origin,
            reviewItemId: currentSession.reviewItemId,
            parentSessionId: currentSession.parentSessionId,
            expectedQuestionVersion: fixedQuestion.version,
          ).toJson(),
        ),
      );
      if (_disposed || version != _localVersion) return;
      if (!await source.writeActive(
        args.questionId,
        ref,
        expectedEpoch: epoch,
      )) {
        return;
      }
      if (await source.readPendingCopy(args.questionId) != null) {
        await source.acknowledgeCopySelection(
          args.questionId,
          idempotencyKey: key,
          selectedRef: ref,
        );
      }
      if (_disposed || version != _localVersion) return;
      drafts = target;
      session = currentSession;
      attempt = currentAttempt;
      question = fixedQuestion;
      _workspace = await target.readWorkspaceContext(args.questionId);
      _applyLocal((await target.readDraft(args.questionId))!);
      conflictServerDraft = null;
      _recoveryBlocked = false;
      _recoveryGeneration = null;
      recoveryCopies = const [];
      selectableCopy = null;
      _attachedDurably = true;
      creationBlockedReason = null;
      actionError = null;
      sync = _dirtyRemote ? SaveStatus.dirty : SaveStatus.saved;
      if (_dirtyRemote) _scheduleSync();
    } catch (error) {
      actionError = error;
    } finally {
      recoveryBusy = false;
      _notify();
    }
  }

  /// 保留本地稿：以云端当前版本为基准重新同步，覆盖云端。
  Future<void> resolveConflictKeepLocal() async {
    final server = conflictServerDraft;
    if (server == null || recoveryBusy) return;
    if (!await _prepareResolution(server)) return;
    _recoveryBlocked = false;
    _serverRevision = server.revision;
    conflictServerDraft = null;
    _dirtyRemote = true;
    sync = SaveStatus.dirty;
    _notify();
    try {
      if (await _syncDraft(force: true, resolving: true)) {
        await drafts.resolveRecovery(
          args.questionId,
          expectedGeneration: _recoveryGeneration!,
        );
      }
    } catch (error) {
      actionError = error;
      localSaveFailed = true;
      _recoveryBlocked = true;
      sync = SaveStatus.conflict;
      conflictServerDraft = server;
    } finally {
      recoveryBusy = false;
      _notify();
    }
  }

  /// 使用云端稿：本地内容换成云端的。
  Future<void> resolveConflictUseServer() async {
    final server = conflictServerDraft;
    if (server == null || recoveryBusy) return;
    if (!await _prepareResolution(server)) return;
    final version = _localVersion;
    try {
      await drafts.writeDraft(LocalDraft.fromServer(args.questionId, server));
      if (_disposed || version != _localVersion) {
        await _persistLocal();
        return;
      }
      // Keep pending until the chosen draft is durably written.
      await drafts.resolveRecovery(
        args.questionId,
        expectedGeneration: _recoveryGeneration!,
      );
      if (_disposed || version != _localVersion) {
        await _archiveConflict(server);
        await _persistLocal();
        return;
      }
      _applyServerDraft(server);
      conflictServerDraft = null;
      _recoveryBlocked = false;
      sync = SaveStatus.saved;
      localSaveFailed = false;
    } catch (error) {
      actionError = error;
      localSaveFailed = true;
    } finally {
      recoveryBusy = false;
      _notify();
    }
  }

  Future<void> _archiveConflict(Draft server) async {
    try {
      final recovery = await drafts.archivePair(
        args.questionId,
        _snapshot(),
        LocalDraft.fromServer(args.questionId, server),
        pending: true,
      );
      recoveryCopies = recovery.copies;
      _recoveryGeneration = recovery.generation;
    } catch (error) {
      localSaveFailed = true;
      actionError = error;
    }
    _notify();
  }

  Future<bool> _prepareResolution(Draft server) async {
    recoveryBusy = true;
    _notify();
    final version = _localVersion;
    try {
      await _conflictWrite;
      if (attempt == null) await _attachRemote();
      if (attempt?.id != server.attemptId) throw StateError('作答已改变，请保留本机副本');
      final recovery = await drafts.archivePair(
        args.questionId,
        _snapshot(),
        LocalDraft.fromServer(args.questionId, server),
        pending: true,
        expectedGeneration: _recoveryGeneration,
      );
      recoveryCopies = recovery.copies;
      _recoveryGeneration = recovery.generation;
      if (_disposed || version != _localVersion) {
        throw StateError('内容已更新，请重新选择');
      }
      return true;
    } catch (error) {
      actionError = error;
      localSaveFailed = true;
      recoveryBusy = false;
      _notify();
      return false;
    }
  }

  Future<void> restoreCopy(int index) async {
    if (recoveryBusy ||
        submitting ||
        _syncing ||
        _attaching ||
        phase != SolvePhase.answering ||
        index < 0 ||
        index >= recoveryCopies.length) {
      return;
    }
    recoveryBusy = true;
    final version = _localVersion;
    final chosen = recoveryCopies[index];
    final current = _snapshot();
    _syncTimer?.cancel();
    try {
      await _conflictWrite;
      final recovery = await drafts.archivePair(
        args.questionId,
        current,
        conflictServerDraft == null
            ? chosen
            : LocalDraft.fromServer(args.questionId, conflictServerDraft!),
        pending: conflictServerDraft != null,
        expectedGeneration: _recoveryGeneration,
      );
      recoveryCopies = recovery.copies;
      _recoveryGeneration = recovery.generation;
      if (_disposed ||
          version != _localVersion ||
          phase != SolvePhase.answering ||
          current.attemptId != (attempt?.id ?? _localAttemptId)) {
        throw StateError('内容已更新，请重新恢复');
      }
      // Persist chosen content before changing the editor; never rebind its old attempt.
      final data = chosen.toJson()
        ..['attemptId'] = current.attemptId
        ..['sessionId'] = current.sessionId
        ..['baseRevision'] = current.baseRevision
        ..['dirty'] = true;
      data['savedAt'] = DateTime.now().toUtc().toIso8601String();
      final restored = LocalDraft.fromJson(data);
      await drafts.writeDraft(restored);
      if (_disposed ||
          version != _localVersion ||
          phase != SolvePhase.answering ||
          current.attemptId != (attempt?.id ?? _localAttemptId)) {
        await _persistLocal();
        return;
      }
      _applyLocal(restored);
      _localVersion += 1;
      _ensureStep();
      if (!_recoveryBlocked && sync != SaveStatus.conflict) {
        sync = SaveStatus.dirty;
      }
      localSaveFailed = false;
      // Restoration stays local until the student explicitly retries or continues editing.
    } catch (error) {
      localSaveFailed = true;
      actionError = error;
    } finally {
      recoveryBusy = false;
      _notify();
    }
  }

  /// 学生点"立即重试"。
  Future<void> retryNow() async {
    await _syncDraft(force: true);
  }

  void _startRetry() {
    _retryTimer ??= Timer.periodic(retryDelay, (_) async {
      if (sync != SaveStatus.offline) {
        _stopRetry();
        return;
      }
      await _syncDraft(force: true);
    });
  }

  void _stopRetry() {
    _retryTimer?.cancel();
    _retryTimer = null;
  }

  void _expire() {
    if (authExpired) return;
    authExpired = true;
    onUnauthenticated?.call();
  }

  void _checkAuth(Object error) {
    if (error is ApiException && error.statusCode == 401) _expire();
  }

  // ------------------------------------------------------------ 提交

  AnswerPayload _submitAnswer() {
    if (_mode == AnswerMode.fill) {
      return AnswerPayload(
        blanks: [
          for (final blank in question!.content.blanks)
            AnswerBlank(
              key: blank.key,
              value: (_blanks[blank.key] ?? '').trim(),
            ),
        ],
      );
    }
    if (_mode == AnswerMode.written) {
      return AnswerPayload(parts: _partsInOrder(trim: true));
    }
    if (_mode == AnswerMode.experiment) {
      return AnswerPayload(
        cells: _cellsInOrder(trim: true),
        parts: _partsInOrder(trim: true),
      );
    }
    if (_mode == AnswerMode.proof) {
      return AnswerPayload(steps: _stepsToSend(trim: true));
    }
    final options = question!.content.options
        .map((o) => o.key)
        .where(_selected.contains)
        .toList();
    return AnswerPayload(selectedOptions: options);
  }

  Future<void> submit() async {
    if (isFinished) return;
    if (needsSubmissionRecovery && !submitting) {
      final sourceSnapshot =
          pendingSubmission?.sourceSnapshot ??
          unboundSubmission!.sourceSnapshot;
      if (_sameSnapshot(_snapshot(), sourceSnapshot)) {
        await recoverOriginalSubmission();
      } else {
        // A read may discover submission, but is never evidence of this intent's receipt.
        try {
          if (pendingSubmission != null) {
            await api.getAttempt(attemptId: pendingSubmission!.attemptId);
          }
        } catch (error) {
          actionError = error;
        }
        _notify();
      }
      return;
    }
    if (!canSubmit) return;
    final snapshot = _snapshot();
    final answer = _submitAnswer().toJson();
    final elapsed = _stopwatch.elapsedMilliseconds;
    submitting = true;
    actionError = null;
    _notify();
    final generation = _workspaceGeneration;
    try {
      if (_unboundLocalScope) {
        await drafts.writeDraft(snapshot);
        unboundSubmission = await drafts.prepareUnboundSubmission(
          args.questionId,
          sourceSnapshot: snapshot,
          answer: answer,
          elapsedMs: elapsed,
          bodyTemplate: _syncBody(snapshot),
        );
      } else {
        final frozen = LocalDraft.fromJson(
          snapshot.toJson()
            ..['sessionId'] = snapshot.sessionId ?? _workspace!.trustedSessionId
            ..['attemptId'] = snapshot.attemptId ?? _workspace!.workspaceId,
        );
        await drafts.writeDraft(frozen);
        final capture = await drafts.prepareSubmissionCapture(
          args.questionId,
          sourceSnapshot: frozen,
          answer: answer,
          elapsedMs: elapsed,
          body: _syncBody(frozen),
        );
        pendingSubmission = capture.submit;
      }
      if (!await _attachRemote() || !_currentWorkspace(generation)) {
        actionError ??= ApiException.network('连不上服务，原提交与答案已在本机保留');
        return;
      }
      if (unboundSubmission != null) {
        final bound = await drafts.readWrite(args.questionId, 'submit');
        if (!_pending(bound)) throw StateError('原提交尚未绑定新作答，原稿保留');
        pendingSubmission = bound;
        unboundSubmission = null;
      }
      await _sendSubmission();
    } catch (error) {
      if (!_currentWorkspace(generation)) return;
      actionError = error;
      await _submissionFailure(error);
      if (error is! ApiException) {
        localSaveFailed = true;
      }
    } finally {
      if (_currentWorkspace(generation)) {
        submitting = false;
        if (needsSubmissionRecovery) _stopRetry();
        _notify();
      }
    }
  }

  /// Only a deliberate recovery action may replay A after the student edited B.
  Future<void> recoverOriginalSubmission() async {
    if (submitting || !_mayUseIdentity || !needsSubmissionRecovery) return;
    submitting = true;
    final generation = _workspaceGeneration;
    _notify();
    try {
      if (unboundSubmission != null) {
        if (!await _attachRemote() || !_currentWorkspace(generation)) return;
        final bound = await drafts.readWrite(args.questionId, 'submit');
        if (!_pending(bound)) throw StateError('原提交尚未绑定，原文保留');
        pendingSubmission = bound;
        unboundSubmission = null;
      }
      await _sendSubmission();
    } catch (error) {
      if (_currentWorkspace(generation)) {
        actionError = error;
        await _submissionFailure(error);
        if (error is! ApiException) {
          localSaveFailed = true;
        }
      }
    } finally {
      if (_currentWorkspace(generation)) {
        submitting = false;
        if (needsSubmissionRecovery) _stopRetry();
        _notify();
      }
    }
  }

  Future<void> _submissionFailure(Object error) async {
    if (error is! ApiException || pendingSubmission == null) return;
    _checkAuth(error);
    if (error.statusCode >= 400 &&
        error.statusCode < 500 &&
        error.statusCode != 401) {
      final command = pendingSubmission!;
      pendingSubmission = await drafts.blockWrite(
        args.questionId,
        lane: 'submit',
        intentId: command.intentId,
        expectedGeneration: command.generation,
        reason: error.code,
        rejected:
            error.statusCode == 422 ||
            error.code == 'submission_draft_revision_conflict',
      );
      if (error.code == 'submission_draft_revision_conflict') {
        final raw = error.details['server_draft'];
        if (raw is Map) {
          conflictServerDraft = Draft.fromJson(Map<String, dynamic>.from(raw));
          _conflictWrite = _archiveConflict(conflictServerDraft!);
          _recoveryBlocked = true;
          sync = SaveStatus.conflict;
        }
      }
      if (pendingSubmission!.phase == 'rejected') pendingSubmission = null;
    }
  }

  Future<void> _sendSubmission() async {
    final generation = _workspaceGeneration;
    final source = drafts;
    var command = pendingSubmission!;
    if (command.phase == 'blocked' || command.phase == 'rejected') {
      throw StateError('原提交已阻断，原稿保留：${command.phase}');
    }
    if (command.phase == 'waiting_dependency') {
      if (_syncing) await _syncCompletion?.future;
      if (!_currentWorkspace(generation)) return;
      final dependency = await source.readWrite(args.questionId, 'draft_sync');
      if (_pending(dependency)) {
        if (!await _syncDraft(force: true, submissionDependency: true)) {
          actionError ??= ApiException.network('先恢复原草稿同步，再恢复提交；当前修改已保留');
          return;
        }
      }
      final prepared = await source.prepareSubmitDependency(
        args.questionId,
        intentId: command.intentId,
        expectedGeneration: command.generation,
      );
      command = prepared.submit;
      pendingSubmission = command;
    }
    if (command.phase == 'awaiting_sync') {
      final dependency = await source.readWrite(args.questionId, 'draft_sync');
      final dependencyAcknowledged =
          dependency?.intentId == command.syncIntentId &&
          dependency?.phase == 'acked';
      if (!dependencyAcknowledged &&
          !await _syncDraft(force: true, submissionDependency: true)) {
        actionError ??= ApiException.network('连不上服务，原提交已保留，请联网后恢复');
        return;
      }
      command = await source.finalizeSubmit(
        args.questionId,
        intentId: command.intentId,
        expectedGeneration: command.generation,
      );
      pendingSubmission = command;
    }
    if (!_currentWorkspace(generation)) return;
    final result = command.result != null
        ? SubmitResult.fromJson(command.result!)
        : await api.submitAttempt(
            attemptId: command.attemptId,
            body: SubmitRequest.fromJson(command.body!),
            idempotencyKey: command.idempotencyKey,
          );
    if (!_currentWorkspace(generation)) return;
    if (command.result == null) {
      command = await source.recordWriteResult(
        args.questionId,
        lane: 'submit',
        intentId: command.intentId,
        expectedGeneration: command.generation,
        result: result.toJson(),
      );
      pendingSubmission = command;
    }
    // B must reach disk before the atomic A acknowledgement can move it.
    await source.writeDraft(_snapshot());
    await source.ackSubmit(
      args.questionId,
      intentId: command.intentId,
      expectedGeneration: command.generation,
    );
    if (!_currentWorkspace(generation)) return;
    continuations = await source.readContinuations(args.questionId);
    pendingSubmission = null;
    _applyLocal(command.sourceSnapshot);
    _applyResult(result);
    creationBlockedReason = null;
    // Refresh mutable assistance/state from authoritative reads after receipt recovery.
    final freshSession = await api.getSession(sessionId: result.session.id);
    if (!_currentWorkspace(generation)) return;
    session = freshSession;
    final freshAttempt = await api.getAttempt(attemptId: result.attempt.id);
    if (!_currentWorkspace(generation)) return;
    attempt = freshAttempt;
    await _restoreEvents();
    if (isRetest && args.reviewItemId != null) await _completeReview();
    if (_isSubjective) await loadSelfCheck();
  }

  void _applyResult(SubmitResult result) {
    attempt = result.attempt;
    evaluation = result.evaluation;
    session = result.session;
    reviewItem = result.reviewItem;
    events = [...events, ...result.events];
    phase = SolvePhase.submitted;
    sync = SaveStatus.saved;
    _dirtyRemote = false;
    _autosaveTimer?.cancel();
    _autosaveTimer = null;
    _syncTimer?.cancel();
    _syncTimer = null;
    _stopRetry();
    _stopwatch.stop();
  }

  Future<void> _completeReview() async {
    if (needsSubmissionRecovery ||
        args.reviewItemId == null ||
        attempt == null) {
      return;
    }
    // Later submissions belong to B; recording the session's first C is a separate explicit action.
    if (attempt!.submissionNo != 1) return;
    final generation = _workspaceGeneration;
    final target = ResourceTarget.review(args.reviewItemId!);
    try {
      final existing = await resources.read(target);
      if (_resourcePending(existing)) {
        if (_currentWorkspace(generation)) pendingReview = existing;
        return;
      }
      final proof = await drafts.findConfirmedFirstSubmission(
        args.questionId,
        session!.id,
      );
      if (proof == null) throw StateError('没有原提交确认记录；需明确选择记录已提交复测');
      if (existing != null &&
          existing.toJson()['provenance']?['firstAttemptId'] ==
              proof.attemptId) {
        return;
      }
      final state = await api.getReviewState(reviewId: target.id);
      final command = await resources.prepareReviewCompletion(
        source: drafts,
        questionId: args.questionId,
        reviewId: target.id,
        providedAttempt: attempt!,
        firstAttemptId: proof.attemptId,
        submitIntentId: proof.intentId,
        review: state,
        viewGeneration: generation,
      );
      if (_currentWorkspace(generation)) pendingReview = command;
      await _executeReview(command, generation);
    } catch (error) {
      if (_currentWorkspace(generation)) {
        reviewError = error;
        _checkAuth(error);
      }
    }
  }

  bool get canRecordSubmittedReview =>
      isRetest &&
      session?.firstSubmittedAttemptId != null &&
      !needsSubmissionRecovery &&
      !needsReviewRecovery &&
      !tutorBusy &&
      !submitting;

  Future<void> recordSubmittedReview({
    required bool explicitConfirmation,
  }) async {
    if (!explicitConfirmation ||
        !canRecordSubmittedReview ||
        args.reviewItemId == null ||
        attempt == null) {
      return;
    }
    final generation = _workspaceGeneration;
    tutorBusy = true;
    reviewError = null;
    _notify();
    try {
      if (await drafts.hasUnresolvedSubmission(args.questionId, session!.id)) {
        throw StateError('请先恢复原提交回执');
      }
      final latest = await api.getSession(sessionId: session!.id);
      final firstId =
          latest.firstSubmittedAttemptId ?? (throw StateError('服务器尚无首次提交'));
      final first = await api.getAttempt(attemptId: firstId);
      final state = await api.getReviewState(reviewId: args.reviewItemId!);
      if (!_currentWorkspace(generation)) return;
      final proof = await drafts.findConfirmedFirstSubmission(
        args.questionId,
        latest.id,
      );
      final command = proof != null
          ? await resources.prepareReviewCompletion(
              source: drafts,
              questionId: args.questionId,
              reviewId: args.reviewItemId!,
              providedAttempt: attempt!,
              firstAttemptId: first.id,
              submitIntentId: proof.intentId,
              review: state,
              viewGeneration: generation,
            )
          : await resources.prepareObservedReviewCompletion(
              source: drafts,
              questionId: args.questionId,
              reviewId: args.reviewItemId!,
              providedAttempt: attempt!,
              firstAttempt: first,
              session: latest,
              review: state,
              explicitConfirmation: true,
              viewGeneration: generation,
            );
      pendingReview = command;
      await _executeReview(command, generation);
    } catch (error) {
      if (_currentWorkspace(generation)) {
        reviewError = error;
        _checkAuth(error);
      }
    } finally {
      if (_currentWorkspace(generation)) {
        tutorBusy = false;
        _notify();
      }
    }
  }

  Future<void> recoverReviewCompletion() async {
    if (pendingReview == null ||
        tutorBusy ||
        !_mayUseIdentity ||
        needsSubmissionRecovery) {
      return;
    }
    tutorBusy = true;
    final generation = _workspaceGeneration;
    _notify();
    try {
      await _executeReview(pendingReview!, generation);
    } catch (error) {
      if (_currentWorkspace(generation)) {
        reviewError = error;
        _checkAuth(error);
      }
    } finally {
      if (_currentWorkspace(generation)) {
        tutorBusy = false;
        _notify();
      }
    }
  }

  Future<void> _executeReview(ResourceCommand supplied, int generation) =>
      _inResourceScope(
        ResourceTarget.review(supplied.source.reviewId!),
        () => _performReview(supplied, generation),
      );

  Future<void> _performReview(ResourceCommand supplied, int generation) async {
    if (!_currentWorkspace(generation)) return;
    final viewOrigin = await drafts.readResourceOrigin(
      args.questionId,
      viewGeneration: generation,
    );
    if (viewOrigin.reviewId != supplied.source.reviewId ||
        viewOrigin.origin != 'review') {
      throw StateError('当前复测来源不匹配');
    }
    final target = ResourceTarget.review(supplied.source.reviewId!);
    var command = await resources.read(target) ?? (throw StateError('原复测记录缺失'));
    if (command.intentId != supplied.intentId) throw StateError('复测记录已改变');
    if (command.phase == 'blocked') throw StateError('原复测记录已阻断');
    if (['acked', 'rejected'].contains(command.phase)) {
      final latest = await api.getReviewState(reviewId: target.id);
      final summary = command.toJson()['resultSummary'] as Map?;
      if (latest.id != target.id ||
          latest.questionId != viewOrigin.questionId) {
        throw StateError('复测刷新来源不符');
      }
      if (await _resourceViewCurrent(viewOrigin, generation)) {
        reviewState = latest;
        pendingReview = null;
        final oldResult = summary?['completion'] as Map?;
        final known = oldResult == null
            ? null
            : ReviewCompletion.fromJson(Map<String, dynamic>.from(oldResult));
        if (command.source.sessionId == viewOrigin.sessionId) {
          reviewCompletion = known;
        } else {
          historicalReviewCompletion = known;
        }
        final code = (summary?['rejection'] as Map?)?['code'];
        reviewError = code == null ? null : StateError(code.toString());
      }
      return;
    }
    String? rejection = command.toJson()['rejection']?['code'] as String?;
    ReviewCompletion? receipt = command.result == null
        ? null
        : ReviewCompletion.fromJson(command.result!);
    if (command.phase == 'prepared') {
      try {
        receipt = await api.completeReview(
          reviewId: target.id,
          body: ReviewComplete.fromJson(command.body),
          idempotencyKey: command.idempotencyKey,
        );
        command = await resources.recordResult(
          target,
          intentId: command.intentId,
          expectedGeneration: command.generation,
          result: receipt.toJson(),
        );
      } on ApiException catch (error) {
        if (error.statusCode >= 400 &&
            error.statusCode < 500 &&
            error.statusCode != 401) {
          rejection = error.code;
          command = await resources.recordRejection(
            target,
            intentId: command.intentId,
            expectedGeneration: command.generation,
            status: error.statusCode,
            code: error.code,
          );
        } else {
          rethrow;
        }
      }
    }
    if (!_mayUseIdentity) return;
    if (_currentWorkspace(generation)) pendingReview = command;
    final ticket = await resources.beginRefresh(
      target,
      intentId: command.intentId,
      expectedGeneration: command.generation,
    );
    final latest = await api.getReviewState(reviewId: target.id);
    final view = await resources.ackReview(ticket, latestState: latest);
    if (await _resourceViewCurrent(viewOrigin, generation)) {
      reviewState = view.review;
      if (command.source.sessionId == viewOrigin.sessionId) {
        reviewCompletion = rejection == null ? receipt : null;
      } else {
        historicalReviewCompletion = rejection == null ? receipt : null;
      }
      reviewError = rejection == null ? null : StateError(rejection);
      pendingReview = null;
    }
  }

  /// 答完之后再试一次：新建一份作答，清掉答案和笔迹。
  Future<void> continueDraft(String continuationId) async {
    if (!continuations.any((c) => c.id == continuationId)) return;
    await retry(continuationId: continuationId);
  }

  Future<void> retry({String? continuationId}) async {
    if ((phase != SolvePhase.submitted &&
            !(phase == SolvePhase.readonly &&
                attempt?.status == AttemptStatus.submitted)) ||
        session == null ||
        isFinished) {
      return;
    }
    if (phase == SolvePhase.readonly &&
        (_snapshot().hasContent || needsSubmissionRecovery)) {
      actionError = StateError('本机未提交内容已保留，请先查看原作答记录；不会用空白作答替换它');
      _notify();
      return;
    }
    if (continuationId == null && continuations.isNotEmpty) {
      actionError = StateError('请先查看未提交续稿，选择在原会话继续');
      _notify();
      return;
    }
    actionError = null;
    submitting = true;
    _notify();
    try {
      if (!await _runCreation(retry: true, continuationId: continuationId)) {
        return;
      }
      if (continuationId != null) {
        final restored = await drafts.readDraft(args.questionId);
        if (restored == null) throw StateError('续稿没有迁入，原稿仍保留');
        _applyLocal(restored);
        continuations = await drafts.readContinuations(args.questionId);
        evaluation = null;
        selfCheck = null;
        _marks.clear();
        selfCheckError = null;
        phase = SolvePhase.answering;
        sync = SaveStatus.dirty;
        _scheduleSync();
        _stopwatch
          ..reset()
          ..start();
        return;
      }
      if (_disposed) return;
      _selected.clear();
      _blanks.clear();
      _parts.clear();
      _cells.clear();
      _steps.clear();
      _ensureStep();
      _stepsRevision += 1;
      _marks.clear();
      selfCheck = null;
      selfCheckError = null;
      ink.loadContract(null);
      evaluation = null;
      reviewItem = null;
      _serverRevision = attempt!.draftRevision;
      _localAttemptId = attempt!.id;
      _dirtyRemote = false;
      _localVersion = 0;
      sync = SaveStatus.saved;
      phase = SolvePhase.answering;
      _stopwatch
        ..reset()
        ..start();
    } on ApiException catch (error) {
      actionError = error;
      _checkAuth(error);
    } catch (error) {
      actionError = error;
      localSaveFailed = true;
    } finally {
      submitting = false;
      _notify();
    }
  }

  // ------------------------------------------------------------ 解答题的自查

  /// 取这份作答的自查要点和已保存的自评。要点只在提交之后才给，所以只在提交之后调用。
  /// 失败不影响已经提交的作答：[selfCheckError] 里有原因，可以再调用一次。
  Future<void> loadSelfCheck() async {
    if (_openingWorkspace ||
        !_isSubjective ||
        phase != SolvePhase.submitted ||
        attempt == null ||
        selfCheckBusy) {
      return;
    }
    selfCheckBusy = true;
    selfCheckError = null;
    _notify();
    final generation = _workspaceGeneration;
    try {
      final loaded = await api.getSelfCheck(attemptId: attempt!.id);
      if (!_currentWorkspace(generation)) return;
      selfCheck = loaded;
      final local = await drafts.readEditState(args.questionId);
      if (!_currentWorkspace(generation)) return;
      final remoteMarks = {for (final m in loaded.marks) m.pointKey: m.level};
      selfCheckRemoteConflict =
          local.confirmedMarks.isNotEmpty &&
          !jsonEquals(
            local.confirmedMarks.map((k, v) => MapEntry(k, v.toJson())),
            remoteMarks.map((k, v) => MapEntry(k, v.toJson())),
          );
      _marks
        ..clear()
        ..addAll(
          local.marks.isNotEmpty
              ? local.marks
              : {for (final m in loaded.marks) m.pointKey: m.level},
        );
    } on ApiException catch (error) {
      if (!_currentWorkspace(generation)) return;
      selfCheckError = error;
      _checkAuth(error);
    } finally {
      if (_currentWorkspace(generation)) {
        selfCheckBusy = false;
        _notify();
      }
    }
  }

  /// 给一个要点标"做到了 / 做到一部分 / 没做到"。还没有保存，点保存才会发给服务端。
  void markPoint(String pointKey, SelfCheckLevel level) {
    final points = selfCheck?.points;
    if (points == null || !points.any((p) => p.key == pointKey)) return;
    _marks[pointKey] = level;
    final source = drafts;
    final marks = Map<String, SelfCheckLevel>.of(_marks);
    final generation = _workspaceGeneration;
    _marksWrite = _marksWrite.catchError((Object _) {}).then((_) async {
      try {
        await source.saveLocalMarks(args.questionId, marks);
      } catch (error) {
        if (_currentWorkspace(generation)) {
          selfCheckError = error;
          localSaveFailed = true;
          _notify();
        }
        rethrow;
      }
    });
    // Observe failures while retaining the failed future so save cannot send unsaved marks.
    unawaited(_marksWrite.catchError((Object _) {}));
    _notify();
  }

  /// 保存自评：每个要点都标完才发。幂等键随内容变化——同样的内容重试复用同一个键，改了内容就换新键。
  Future<void> chooseRemoteSelfCheck() async {
    if (!selfCheckRemoteConflict || selfCheck == null) return;
    final generation = _workspaceGeneration;
    final source = drafts;
    final marks = {for (final m in selfCheck!.marks) m.pointKey: m.level};
    try {
      final pending = await source.readWrite(args.questionId, 'self_check');
      if (_pending(pending)) {
        await source.blockWrite(
          args.questionId,
          lane: 'self_check',
          intentId: pending!.intentId,
          expectedGeneration: pending.generation,
          reason: 'explicit_remote_selection',
          rejected: true,
        );
      }
      await source.saveLocalMarks(args.questionId, marks, confirmed: true);
      if (!_currentWorkspace(generation)) return;
      _marks
        ..clear()
        ..addAll(marks);
      selfCheckRemoteConflict = false;
      _notify();
    } catch (error) {
      if (!_currentWorkspace(generation)) return;
      selfCheckError = error;
      localSaveFailed = true;
      _notify();
    }
  }

  Future<void> keepLocalSelfCheck() async {
    if (!selfCheckRemoteConflict) return;
    selfCheckRemoteConflict = false;
    await saveSelfCheck();
  }

  Future<void> saveSelfCheck() async {
    final current = selfCheck;
    if (_openingWorkspace ||
        current == null ||
        !selfCheckComplete ||
        selfCheckRemoteConflict ||
        selfCheckBusy) {
      return;
    }
    selfCheckBusy = true;
    selfCheckError = null;
    _notify();
    final generation = _workspaceGeneration;
    try {
      final body = SelfCheckSave(
        marks: [
          for (final point in current.points)
            SelfCheckMark(pointKey: point.key, level: _marks[point.key]!),
        ],
      );
      await _marksWrite;
      var command = await drafts.readWrite(args.questionId, 'self_check');
      if (!_pending(command)) {
        command = await drafts.prepareWrite(
          args.questionId,
          lane: 'self_check',
          body: body.toJson(),
          sourceSnapshot: _snapshot(),
        );
      }
      if (command?.phase == 'blocked') {
        throw StateError('原自查保存已阻断，勾选保留：${command!.blockedReason}');
      }
      final saved = command!.result != null
          ? SelfCheck.fromJson(command.result!)
          : await api.saveSelfCheck(
              attemptId: command.attemptId,
              body: SelfCheckSave.fromJson(command.body!),
              idempotencyKey: command.idempotencyKey,
            );
      if (!_currentWorkspace(generation)) return;
      if (command.result == null) {
        command = await drafts.recordWriteResult(
          args.questionId,
          lane: 'self_check',
          intentId: command.intentId,
          expectedGeneration: command.generation,
          result: saved.toJson(),
        );
      }
      await _marksWrite;
      await drafts.ackSelfCheck(
        args.questionId,
        intentId: command.intentId,
        expectedGeneration: command.generation,
      );
      if (!_currentWorkspace(generation)) return;
      selfCheck = saved;
    } on ApiException catch (error) {
      if (!_currentWorkspace(generation)) return;
      if (error.statusCode >= 400 &&
          error.statusCode < 500 &&
          error.statusCode != 401) {
        final command = await drafts.readWrite(args.questionId, 'self_check');
        if (_pending(command)) {
          await drafts.blockWrite(
            args.questionId,
            lane: 'self_check',
            intentId: command!.intentId,
            expectedGeneration: command.generation,
            reason: error.code,
            rejected: error.statusCode == 422,
          );
        }
      }
      selfCheckError = error;
      _checkAuth(error);
    } catch (error) {
      if (!_currentWorkspace(generation)) return;
      selfCheckError = error;
      localSaveFailed = true;
    } finally {
      if (_currentWorkspace(generation)) {
        selfCheckBusy = false;
        _notify();
      }
    }
  }

  // ------------------------------------------------------------ 辅导

  Future<TutorOutcome> tutor(
    TutorActionType action, {
    bool confirmEndIndependent = false,
  }) async {
    if (_openingWorkspace || tutorBusy) return TutorOutcome.busy;
    if (!assistanceAllowed) return TutorOutcome.notAllowed;
    tutorBusy = true;
    actionError = null;
    _notify();
    final generation = _workspaceGeneration;
    try {
      if (!await _attachRemote() || !_currentWorkspace(generation)) {
        return TutorOutcome.failed;
      }
      final target = ResourceTarget.session(session!.id);
      final body = TutorAction(
        action: action,
        confirmEndIndependent: confirmEndIndependent,
      );
      var command = await resources.read(target);
      if (!_resourcePending(command)) {
        command = await resources.prepareTutor(
          source: drafts,
          questionId: args.questionId,
          sessionId: session!.id,
          body: body,
          viewGeneration: generation,
        );
      } else if (!jsonEquals(command!.body, body.toJson())) {
        pendingTutor = command;
        throw StateError('请先恢复原辅导动作，再选择新的动作');
      }
      pendingTutor = command;
      return await _executeTutor(command, generation);
    } catch (error) {
      if (_currentWorkspace(generation)) {
        actionError = error;
        _checkAuth(error);
      }
      return TutorOutcome.failed;
    } finally {
      if (_currentWorkspace(generation)) {
        tutorBusy = false;
        _notify();
      }
    }
  }

  Future<void> recoverTutor() async {
    if (tutorBusy || pendingTutor == null || !_mayUseIdentity) return;
    tutorBusy = true;
    final generation = _workspaceGeneration;
    _notify();
    try {
      await _executeTutor(pendingTutor!, generation);
    } catch (error) {
      if (_currentWorkspace(generation)) {
        actionError = error;
        _checkAuth(error);
      }
    } finally {
      if (_currentWorkspace(generation)) {
        tutorBusy = false;
        _notify();
      }
    }
  }

  Future<TutorOutcome> _executeTutor(
    ResourceCommand supplied,
    int generation,
  ) => _inResourceScope(
    ResourceTarget.session(supplied.source.sessionId),
    () => _performTutor(supplied, generation),
  );

  Future<TutorOutcome> _performTutor(
    ResourceCommand supplied,
    int generation,
  ) async {
    if (!_currentWorkspace(generation)) return TutorOutcome.failed;
    final viewOrigin = await drafts.readResourceOrigin(
      args.questionId,
      viewGeneration: generation,
    );
    if (viewOrigin.sessionId != supplied.source.sessionId) {
      throw StateError('当前辅导会话不匹配');
    }
    final target = ResourceTarget.session(supplied.source.sessionId);
    var command = await resources.read(target) ?? (throw StateError('原辅导记录缺失'));
    if (command.intentId != supplied.intentId) throw StateError('辅导记录已改变');
    if (['acked', 'rejected'].contains(command.phase)) {
      final cached = await resources.readView(target);
      final latest = await api.getSession(sessionId: target.id);
      final history = await _readResourceEvents(target.id);
      if (latest.id != target.id ||
          latest.questionId != viewOrigin.questionId ||
          latest.questionVersion != viewOrigin.questionVersion) {
        throw StateError('辅导刷新来源不符');
      }
      final fetched = {for (final event in history.events) event.id: event};
      for (final old in cached?.events ?? <TutorEvent>[]) {
        if (!jsonEquals(fetched[old.id]?.toJson(), old.toJson())) {
          throw StateError('历史事件已改变，保留原记录');
        }
      }
      final refreshed = latest.toJson();
      for (final key in ['assisted', 'used_solution', 'independent_ended']) {
        refreshed[key] =
            refreshed[key] == true || cached?.session?.toJson()[key] == true;
      }
      if ((cached?.session?.hintLevelRevealed ?? 0) >
          latest.hintLevelRevealed) {
        refreshed['hint_level_revealed'] = cached!.session!.hintLevelRevealed;
      }
      if (await _resourceViewCurrent(viewOrigin, generation)) {
        await _acceptResourceState(
          StudySession.fromJson(refreshed),
          history.events,
          viewOrigin,
          generation,
        );
        pendingTutor = null;
      }
      return command.phase == 'acked' ? TutorOutcome.ok : TutorOutcome.failed;
    }
    if (command.phase == 'blocked') throw StateError('原辅导已阻断，原文保留');
    String? rejected = command.toJson()['rejection']?['code'] as String?;
    if (command.phase == 'prepared') {
      try {
        final result = await api.tutorNext(
          sessionId: target.id,
          body: TutorAction.fromJson(command.body),
          idempotencyKey: command.idempotencyKey,
        );
        command = await resources.recordResult(
          target,
          intentId: command.intentId,
          expectedGeneration: command.generation,
          result: result.toJson(),
        );
      } on ApiException catch (error) {
        if (error.statusCode >= 400 &&
            error.statusCode < 500 &&
            error.statusCode != 401) {
          rejected = error.code;
          command = await resources.recordRejection(
            target,
            intentId: command.intentId,
            expectedGeneration: command.generation,
            status: error.statusCode,
            code: error.code,
          );
        } else {
          rethrow;
        }
      }
    }
    if (!_mayUseIdentity) return TutorOutcome.failed;
    if (_currentWorkspace(generation)) pendingTutor = command;
    final ticket = await resources.beginRefresh(
      target,
      intentId: command.intentId,
      expectedGeneration: command.generation,
    );
    final latest = await api.getSession(sessionId: target.id);
    final history = await _readResourceEvents(target.id);
    final view = await resources.ackTutor(
      ticket,
      latestSession: latest,
      events: history,
    );
    if (await _resourceViewCurrent(viewOrigin, generation)) {
      await _acceptResourceState(
        view.session!,
        view.events,
        viewOrigin,
        generation,
      );
      pendingTutor = null;
      if (rejected != null) actionError = StateError(rejected);
    }
    return rejected == 'independent_attempt_in_progress'
        ? TutorOutcome.needsConfirmation
        : rejected != null
        ? TutorOutcome.failed
        : TutorOutcome.ok;
  }

  // ------------------------------------------------------------ 收尾

  @override
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _autosaveTimer?.cancel();
    _syncTimer?.cancel();
    _retryTimer?.cancel();
    ink.dispose();
    super.dispose();
  }
}
