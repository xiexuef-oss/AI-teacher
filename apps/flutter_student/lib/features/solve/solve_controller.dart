import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/format.dart' show jsonEquals;
import '../../core/idempotency.dart';
import '../../core/storage.dart';
import 'draft_store.dart';
import 'ink/ink_controller.dart';

enum SolvePhase { loading, answering, submitted, failed }

/// 草稿的保存状态。本机保存与云端同步是两回事：本机永远先保存。
enum SaveStatus { saved, dirty, saving, offline, conflict }

enum TutorOutcome { ok, needsConfirmation, busy, failed, notAllowed }

class SolveArgs {
  const SolveArgs({
    required this.questionId,
    this.origin = 'practice',
    this.reviewItemId,
    this.parentSessionId,
  });

  final String questionId;

  /// task / practice / review / variant
  final String origin;
  final String? reviewItemId;
  final String? parentSessionId;
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
    this.autosaveDelay = const Duration(seconds: 2),
    this.syncDelay = const Duration(seconds: 4),
    this.retryDelay = const Duration(seconds: 12),
  }) : drafts = DraftStore(store, userId) {
    ink = InkController(onCommit: _onChanged);
  }

  final TutorApiClient api;
  final String userId;
  final SolveArgs args;
  final VoidCallback? onUnauthenticated;

  /// 本机自动保存的间隔（docs/02：笔迹每 2 秒本地增量保存）。
  final Duration autosaveDelay;

  /// 停笔多久之后把草稿同步到云端。
  final Duration syncDelay;

  /// 断网后重试的间隔。
  final Duration retryDelay;

  final DraftStore drafts;
  late final InkController ink;

  final PendingKeys _keys = PendingKeys();
  final Stopwatch _stopwatch = Stopwatch();

  SolvePhase phase = SolvePhase.loading;
  Object? failure;

  Question? question;
  bool questionFromCache = false;
  StudySession? session;
  Attempt? attempt;

  final Set<String> _selected = {};
  final Map<String, String> _blanks = {};

  /// 解答题各小问的文字，键是小问的 key。
  final Map<String, String> _parts = {};

  SaveStatus sync = SaveStatus.saved;
  bool localSaveFailed = false;
  Draft? conflictServerDraft;

  List<TutorEvent> events = const [];
  Evaluation? evaluation;
  ReviewItem? reviewItem;
  ReviewCompletion? reviewCompletion;
  Object? reviewError;

  /// 解答题提交后对照要点做的自查。要点只在提交之后才取：独立作答阶段不泄题。
  SelfCheck? selfCheck;
  final Map<String, SelfCheckLevel> _marks = {};
  bool selfCheckBusy = false;
  Object? selfCheckError;

  Object? actionError;
  bool submitting = false;
  bool tutorBusy = false;
  bool authExpired = false;

  int _serverRevision = 0;
  String? _localAttemptId;
  bool _dirtyRemote = false;
  int _localVersion = 0;
  bool _syncing = false;
  bool _attaching = false;
  bool _disposed = false;
  Timer? _autosaveTimer;
  Timer? _syncTimer;
  Timer? _retryTimer;

  Set<String> get selected => Set.unmodifiable(_selected);
  Map<String, String> get blanks => Map.unmodifiable(_blanks);
  Map<String, String> get parts => Map.unmodifiable(_parts);
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
  bool get assistanceAllowed => !(isRetest && phase != SolvePhase.submitted);

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
      default:
        return false;
    }
  }

  bool get _hasPartsText => _parts.values.any((v) => v.trim().isNotEmpty);

  bool get canSubmit =>
      phase == SolvePhase.answering &&
      !submitting &&
      sync != SaveStatus.conflict &&
      question != null &&
      _answerValid;

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  // ------------------------------------------------------------ 开始

  Future<void> start() async {
    phase = SolvePhase.loading;
    _notify();
    try {
      await _loadQuestion();
    } catch (error) {
      failure = error;
      phase = SolvePhase.failed;
      _checkAuth(error);
      _notify();
      return;
    }
    final local = await drafts.readDraft(args.questionId);
    if (local != null) _applyLocal(local);
    phase = SolvePhase.answering;
    _stopwatch.start();
    _notify();

    await _attachRemote();
    if (_dirtyRemote &&
        sync != SaveStatus.conflict &&
        sync != SaveStatus.offline) {
      sync = SaveStatus.dirty;
      _scheduleSync();
    }
    _notify();
  }

  Future<void> _loadQuestion() async {
    try {
      final loaded = await api.getQuestion(questionId: args.questionId);
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
    ink.loadContract(draft.strokes);
    _serverRevision = draft.baseRevision;
    _localAttemptId = draft.attemptId;
    // 没有对应作答的本机内容（离线时写的）一定还没同步过
    _dirtyRemote = draft.dirty || (draft.attemptId == null && draft.hasContent);
  }

  // ------------------------------------------------------------ 连上云端：会话与作答

  /// 保证云端有会话和一份未提交的作答。失败时（断网等）返回 false，并把状态设成离线。
  /// 已经提交之后只需要会话，不能再新建作答（再试一次由 [retry] 负责）。
  Future<bool> _attachRemote() async {
    if (session != null &&
        (phase == SolvePhase.submitted ||
            attempt?.status == AttemptStatus.draft)) {
      return true;
    }
    if (_attaching || phase == SolvePhase.failed) return false;
    _attaching = true;
    try {
      var resumed = false;
      if (session == null) {
        resumed = await _resumeActive();
      }
      session ??= await api.createSession(
        body: SessionCreate(
          questionId: args.questionId,
          origin: SessionOrigin.fromJson(args.origin),
          reviewItemId: args.reviewItemId,
          parentSessionId: args.parentSessionId,
        ),
        idempotencyKey: _keys.keyFor('session'),
      );
      _keys.done('session');
      if (attempt == null || attempt!.status != AttemptStatus.draft) {
        attempt = await api.createAttempt(
          body: AttemptCreate(sessionId: session!.id),
          idempotencyKey: _keys.keyFor('attempt'),
        );
        _keys.done('attempt');
      }
      await _reconcileDraft();
      if (resumed) await _restoreEvents();
      try {
        await drafts.writeActive(
          args.questionId,
          ActiveRef(sessionId: session!.id, attemptId: attempt!.id),
        );
      } catch (_) {
        // 进行中的会话指针写不进去：最坏是下次多开一个会话
      }
      if (sync == SaveStatus.offline) {
        sync = _dirtyRemote ? SaveStatus.dirty : SaveStatus.saved;
      }
      return true;
    } on ApiException catch (error) {
      _handleSyncError(error);
      return false;
    } finally {
      _attaching = false;
      _notify();
    }
  }

  /// 本机记着一个进行中的会话，并且云端还认：接着用。
  Future<bool> _resumeActive() async {
    final active = await drafts.readActive(args.questionId);
    if (active == null) return false;
    try {
      final existing = await api.getSession(sessionId: active.sessionId);
      final sameKind =
          existing.origin == SessionOrigin.fromJson(args.origin) &&
          existing.reviewItemId == args.reviewItemId;
      if (existing.activeAttemptId == null ||
          existing.state == SessionState.done ||
          !sameKind) {
        await drafts.clearActive(args.questionId);
        return false;
      }
      session = existing;
      attempt = await api.getAttempt(attemptId: existing.activeAttemptId!);
      return true;
    } on ApiException catch (error) {
      if (error.isNetwork ||
          error.statusCode == 401 ||
          error.statusCode >= 500) {
        rethrow;
      }
      await drafts.clearActive(args.questionId); // 404 等：云端已经没有这个会话，重新开
      return false;
    }
  }

  /// 本机内容与刚连上的作答对不对得上，决定是推送、采用云端还是保持。
  Future<void> _reconcileDraft() async {
    final current = attempt!;
    final hasLocalContent =
        _selected.isNotEmpty ||
        _blanks.values.any((v) => v.trim().isNotEmpty) ||
        _hasPartsText ||
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

  Future<void> _restoreEvents() async {
    try {
      final page = await api.listSessionEvents(
        sessionId: session!.id,
        afterSeq: 0,
        limit: 200,
      );
      events = page.items;
    } on ApiException {
      // 时间线恢复不了不影响作答
    }
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
    ink.loadContract(draft.strokes);
    _serverRevision = draft.revision;
    _dirtyRemote = false;
  }

  // ------------------------------------------------------------ 学生的输入

  void selectOption(String key) {
    if (phase != SolvePhase.answering) return;
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
    if (phase != SolvePhase.answering) return;
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
    if (phase != SolvePhase.answering) return;
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

  void _onChanged() {
    if (phase != SolvePhase.answering) return;
    _localVersion += 1;
    _dirtyRemote = true;
    if (sync != SaveStatus.conflict && sync != SaveStatus.offline) {
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
    sessionId: session?.id,
    attemptId: attempt?.id ?? _localAttemptId,
    baseRevision: _serverRevision,
    dirty: _dirtyRemote,
    selected: _selected.toList(),
    blanks: Map.of(_blanks),
    parts: Map.of(_parts),
    strokes: ink.hasInk ? ink.toContract() : null,
    savedAt: DateTime.now().toUtc(),
  );

  Future<void> _persistLocal() async {
    if (phase != SolvePhase.answering) return;
    try {
      await drafts.writeDraft(_snapshot());
      localSaveFailed = false;
    } catch (_) {
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
    if (_selected.isEmpty) return null;
    final options = question!.content.options
        .map((o) => o.key)
        .where(_selected.contains)
        .toList();
    return AnswerPayload(selectedOptions: options);
  }

  /// 有文字的小问，按题目里的顺序。
  List<AnswerPart> _partsInOrder({required bool trim}) => [
    for (final sub in question!.content.subquestions)
      if ((_parts[sub.key] ?? '').trim().isNotEmpty)
        AnswerPart(
          key: sub.key,
          text: trim ? _parts[sub.key]!.trim() : _parts[sub.key]!,
        ),
  ];

  StrokeDoc? _draftStrokes() => ink.hasInk ? ink.toContract() : null;

  bool _sameContent(Draft server) =>
      jsonEquals(_draftAnswer()?.toJson(), server.answer?.toJson()) &&
      jsonEquals(_draftStrokes()?.toJson(), server.strokes?.toJson());

  Future<bool> _syncDraft({bool force = false}) async {
    if (_syncing ||
        phase != SolvePhase.answering ||
        sync == SaveStatus.conflict) {
      return false;
    }
    if (!_dirtyRemote && !force) return true;
    if (!await _attachRemote()) return false;
    if (phase != SolvePhase.answering || sync == SaveStatus.conflict) {
      return false;
    }

    _syncing = true;
    sync = SaveStatus.saving;
    _notify();
    final version = _localVersion;
    final body = DraftSync(
      baseRevision: _serverRevision,
      answer: _draftAnswer(),
      strokes: _draftStrokes(),
    );
    try {
      final key =
          'draft-${attempt!.id}-$_serverRevision-'
          '${jsonEncode(body.toJson()).hashCode.toRadixString(36)}';
      final saved = await api.syncDraft(
        attemptId: attempt!.id,
        body: body,
        idempotencyKey: key,
      );
      _serverRevision = saved.revision;
      if (_localVersion == version) {
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
      _handleSyncError(error);
      return false;
    } finally {
      _syncing = false;
      _notify();
    }
  }

  void _handleSyncError(ApiException error) {
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
    }
    sync = SaveStatus.conflict;
  }

  /// 保留本地稿：以云端当前版本为基准重新同步，覆盖云端。
  Future<void> resolveConflictKeepLocal() async {
    final server = conflictServerDraft;
    if (server == null) return;
    _serverRevision = server.revision;
    conflictServerDraft = null;
    _dirtyRemote = true;
    sync = SaveStatus.dirty;
    _notify();
    await _syncDraft(force: true);
  }

  /// 使用云端稿：本地内容换成云端的。
  Future<void> resolveConflictUseServer() async {
    final server = conflictServerDraft;
    if (server == null) return;
    _applyServerDraft(server);
    conflictServerDraft = null;
    sync = SaveStatus.saved;
    _notify();
    await _persistLocal();
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
    final options = question!.content.options
        .map((o) => o.key)
        .where(_selected.contains)
        .toList();
    return AnswerPayload(selectedOptions: options);
  }

  Future<void> submit() async {
    if (!canSubmit) return;
    submitting = true;
    actionError = null;
    _notify();
    try {
      if (!await _attachRemote()) {
        actionError = ApiException.network('还没有连上服务');
        return;
      }
      // 最后同步一次，让云端也有这份作答的笔迹。同步失败不拦提交（答案在提交请求里）；
      // 有冲突则先让学生解决。
      await _syncDraft(force: true);
      if (sync == SaveStatus.conflict) return;
      // 解答题只有笔迹、没有文字时，笔迹只能随草稿同步到云端：没同步上去，服务端会以为什么都没写
      if (_mode == AnswerMode.written &&
          !_hasPartsText &&
          sync != SaveStatus.saved) {
        actionError = ApiException.network('笔迹还没有同步到云端，连上网络后再提交');
        return;
      }

      final result = await api.submitAttempt(
        attemptId: attempt!.id,
        body: SubmitRequest(
          answer: _submitAnswer(),
          elapsedMs: _stopwatch.elapsedMilliseconds,
        ),
        idempotencyKey: _keys.keyFor('submit'),
      );
      _keys.done('submit');
      _applyResult(result);
      try {
        await drafts.clearDraft(args.questionId);
      } catch (_) {
        // 清不掉也无妨：下次打开发现作答已提交，不会再用它
      }
      if (isRetest && args.reviewItemId != null) await _completeReview();
      if (_mode == AnswerMode.written) await loadSelfCheck();
    } on ApiException catch (error) {
      actionError = error;
      _checkAuth(error);
    } finally {
      submitting = false;
      _notify();
    }
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
    try {
      reviewCompletion = await api.completeReview(
        reviewId: args.reviewItemId!,
        body: ReviewComplete(attemptId: attempt!.id),
        idempotencyKey: _keys.keyFor('review'),
      );
      _keys.done('review');
      reviewError = null;
    } on ApiException catch (error) {
      // 例如这次作答没有确定的判定（待确认）：复测结果暂时记不了，不影响已经提交的作答
      reviewError = error;
    }
  }

  /// 答完之后再试一次：新建一份作答，清掉答案和笔迹。
  Future<void> retry() async {
    if (phase != SolvePhase.submitted || session == null || isFinished) return;
    actionError = null;
    submitting = true;
    _notify();
    try {
      attempt = await api.createAttempt(
        body: AttemptCreate(sessionId: session!.id),
        idempotencyKey: _keys.keyFor('retry'),
      );
      _keys.done('retry');
      _selected.clear();
      _blanks.clear();
      _parts.clear();
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
      await drafts.writeActive(
        args.questionId,
        ActiveRef(sessionId: session!.id, attemptId: attempt!.id),
      );
    } on ApiException catch (error) {
      actionError = error;
      _checkAuth(error);
    } finally {
      submitting = false;
      _notify();
    }
  }

  // ------------------------------------------------------------ 解答题的自查

  /// 取这份作答的自查要点和已保存的自评。要点只在提交之后才给，所以只在提交之后调用。
  /// 失败不影响已经提交的作答：[selfCheckError] 里有原因，可以再调用一次。
  Future<void> loadSelfCheck() async {
    if (_mode != AnswerMode.written ||
        phase != SolvePhase.submitted ||
        attempt == null ||
        selfCheckBusy) {
      return;
    }
    selfCheckBusy = true;
    selfCheckError = null;
    _notify();
    try {
      final loaded = await api.getSelfCheck(attemptId: attempt!.id);
      selfCheck = loaded;
      _marks
        ..clear()
        ..addEntries(loaded.marks.map((m) => MapEntry(m.pointKey, m.level)));
    } on ApiException catch (error) {
      selfCheckError = error;
      _checkAuth(error);
    } finally {
      selfCheckBusy = false;
      _notify();
    }
  }

  /// 给一个要点标"做到了 / 做到一部分 / 没做到"。还没有保存，点保存才会发给服务端。
  void markPoint(String pointKey, SelfCheckLevel level) {
    final points = selfCheck?.points;
    if (points == null || !points.any((p) => p.key == pointKey)) return;
    _marks[pointKey] = level;
    _notify();
  }

  /// 保存自评：每个要点都标完才发。幂等键随内容变化——同样的内容重试复用同一个键，改了内容就换新键。
  Future<void> saveSelfCheck() async {
    final current = selfCheck;
    if (current == null || !selfCheckComplete || selfCheckBusy) return;
    selfCheckBusy = true;
    selfCheckError = null;
    _notify();
    try {
      final body = SelfCheckSave(
        marks: [
          for (final point in current.points)
            SelfCheckMark(pointKey: point.key, level: _marks[point.key]!),
        ],
      );
      final key =
          'selfcheck-${attempt!.id}-'
          '${jsonEncode(body.toJson()).hashCode.toRadixString(36)}';
      selfCheck = await api.saveSelfCheck(
        attemptId: attempt!.id,
        body: body,
        idempotencyKey: key,
      );
    } on ApiException catch (error) {
      selfCheckError = error;
      _checkAuth(error);
    } finally {
      selfCheckBusy = false;
      _notify();
    }
  }

  // ------------------------------------------------------------ 辅导

  Future<TutorOutcome> tutor(
    TutorActionType action, {
    bool confirmEndIndependent = false,
  }) async {
    if (!assistanceAllowed) return TutorOutcome.notAllowed;
    if (tutorBusy) return TutorOutcome.busy;
    tutorBusy = true;
    actionError = null;
    _notify();
    try {
      if (!await _attachRemote()) {
        actionError = ApiException.network('还没有连上服务');
        return TutorOutcome.failed;
      }
      final name =
          'tutor-${action.value}${confirmEndIndependent ? '-confirmed' : ''}';
      final step = await api.tutorNext(
        sessionId: session!.id,
        body: TutorAction(
          action: action,
          confirmEndIndependent: confirmEndIndependent,
        ),
        idempotencyKey: _keys.keyFor(name),
      );
      _keys.done(name);
      session = step.session;
      events = [...events, ...step.events];
      return TutorOutcome.ok;
    } on ApiException catch (error) {
      if (error.code == 'independent_attempt_in_progress') {
        return TutorOutcome.needsConfirmation;
      }
      actionError = error;
      _checkAuth(error);
      return TutorOutcome.failed;
    } finally {
      tutorBusy = false;
      _notify();
    }
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
