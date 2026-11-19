import 'dart:convert';
import 'dart:math';

import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/storage.dart';
import '../../core/local_serial.dart';
import 'resource_journal_store.dart';
import '../../core/idempotency.dart';
import 'write_journal.dart';
export 'write_journal.dart';

part 'draft_store_export.dart';

/// 证明题里的一步：这一步写了什么，以及依据。
class ProofStepDraft {
  const ProofStepDraft({this.text = '', this.reason = ''});

  final String text;
  final String reason;

  /// 什么都没写（空白卡片）。
  bool get isBlank => text.trim().isEmpty && reason.trim().isEmpty;

  ProofStepDraft copyWith({String? text, String? reason}) =>
      ProofStepDraft(text: text ?? this.text, reason: reason ?? this.reason);

  Map<String, dynamic> toJson() => {'text': text, 'reason': reason};

  factory ProofStepDraft.fromJson(Map<String, dynamic> json) => ProofStepDraft(
    text: json['text'] as String,
    reason: json['reason'] as String,
  );
}

/// 本机保存的一份草稿：答案、笔迹，以及它对应的会话/作答和云端版本号。
class LocalDraft {
  const LocalDraft({
    required this.questionId,
    this.sessionId,
    this.attemptId,
    this.baseRevision = 0,
    this.dirty = false,
    this.selected = const [],
    this.blanks = const {},
    this.parts = const {},
    this.cells = const {},
    this.steps = const [],
    this.strokes,
    required this.savedAt,
  });

  /// 存储格式的版本。读到不认识的版本时当作读不到，不硬解析。
  static const int formatVersion = 1;

  final String questionId;
  final String? sessionId;
  final String? attemptId;

  /// 最近一次同步成功后云端的版本号；下次同步要以它为基准。
  final int baseRevision;

  /// 本机有云端还没有的改动。
  final bool dirty;
  final List<String> selected;
  final Map<String, String> blanks;

  /// 解答题、实验题各小问的文字，键是小问的 key。
  final Map<String, String> parts;

  /// 实验题数据表里学生填的格子，键是 "表键.行键.列键"。
  final Map<String, String> cells;

  /// 证明题一步一步写的证明，顺序就是证明的顺序（空白卡片也留着，重新打开时界面和离开时一样）。
  final List<ProofStepDraft> steps;
  final StrokeDoc? strokes;
  final DateTime savedAt;

  factory LocalDraft.fromServer(String questionId, Draft draft) => LocalDraft(
    questionId: questionId,
    attemptId: draft.attemptId,
    baseRevision: draft.revision,
    savedAt: draft.updatedAt,
    selected: draft.answer?.selectedOptions ?? const [],
    blanks: {
      for (final b in draft.answer?.blanks ?? <AnswerBlank>[]) b.key: b.value,
    },
    parts: {
      for (final p in draft.answer?.parts ?? <AnswerPart>[]) p.key: p.text,
    },
    cells: {
      for (final c in draft.answer?.cells ?? <AnswerCell>[])
        '${c.table}.${c.row}.${c.col}': c.value,
    },
    steps: [
      for (final s in draft.answer?.steps ?? <AnswerStep>[])
        ProofStepDraft(text: s.text, reason: s.reason),
    ],
    strokes: draft.strokes,
  );

  Draft asServer() => Draft(
    attemptId: attemptId!,
    revision: baseRevision,
    updatedAt: savedAt,
    strokes: strokes,
    answer: AnswerPayload(
      selectedOptions: selected.isEmpty ? null : selected,
      blanks: blanks.isEmpty
          ? null
          : [
              for (final b in blanks.entries)
                AnswerBlank(key: b.key, value: b.value),
            ],
      parts: parts.isEmpty
          ? null
          : [
              for (final p in parts.entries)
                AnswerPart(key: p.key, text: p.value),
            ],
      cells: cells.isEmpty
          ? null
          : [
              for (final c in cells.entries)
                AnswerCell(
                  table: c.key.split('.')[0],
                  row: c.key.split('.')[1],
                  col: c.key.split('.')[2],
                  value: c.value,
                ),
            ],
      steps: steps.isEmpty
          ? null
          : [for (final s in steps) AnswerStep(text: s.text, reason: s.reason)],
    ),
  );

  bool get hasContent =>
      selected.isNotEmpty ||
      blanks.values.any((v) => v.trim().isNotEmpty) ||
      parts.values.any((v) => v.trim().isNotEmpty) ||
      cells.values.any((v) => v.trim().isNotEmpty) ||
      steps.any((s) => !s.isBlank) ||
      (strokes?.pages.any((p) => p.strokes.isNotEmpty) ?? false);

  Map<String, dynamic> toJson() => {
    'v': formatVersion,
    'questionId': questionId,
    'sessionId': sessionId,
    'attemptId': attemptId,
    'baseRevision': baseRevision,
    'dirty': dirty,
    'answer': {
      'selected': selected,
      'blanks': blanks,
      'parts': parts,
      'cells': cells,
      'steps': [for (final step in steps) step.toJson()],
    },
    'strokes': strokes?.toJson(),
    'savedAt': savedAt.toUtc().toIso8601String(),
  };

  factory LocalDraft.fromJson(Map<String, dynamic> json) {
    final answer = json['answer'] as Map<String, dynamic>;
    return LocalDraft(
      questionId: json['questionId'] as String,
      sessionId: json['sessionId'] as String?,
      attemptId: json['attemptId'] as String?,
      baseRevision: (json['baseRevision'] as num).toInt(),
      dirty: json['dirty'] as bool,
      selected: (answer['selected'] as List<dynamic>).cast<String>(),
      blanks: Map<String, String>.from(answer['blanks'] as Map),
      // 解答题加入之前存下的草稿没有这一项
      parts: answer['parts'] == null
          ? const {}
          : Map<String, String>.from(answer['parts'] as Map),
      // 实验题加入之前存下的草稿没有这一项
      cells: answer['cells'] == null
          ? const {}
          : Map<String, String>.from(answer['cells'] as Map),
      // 证明题加入之前存下的草稿没有这一项
      steps: answer['steps'] == null
          ? const []
          : [
              for (final step in answer['steps'] as List<dynamic>)
                ProofStepDraft.fromJson(Map<String, dynamic>.from(step as Map)),
            ],
      strokes: json['strokes'] == null
          ? null
          : StrokeDoc.fromJson(json['strokes'] as Map<String, dynamic>),
      savedAt: DateTime.parse(json['savedAt'] as String),
    );
  }
}

/// 本机记着的"进行中的会话"：重新打开同一道题时接着用，不重复开会话。
class ActiveRef {
  const ActiveRef({required this.sessionId, required this.attemptId});

  final String sessionId;
  final String attemptId;

  Map<String, dynamic> toJson() => {
    'sessionId': sessionId,
    'attemptId': attemptId,
  };

  factory ActiveRef.fromJson(Map<String, dynamic> json) => ActiveRef(
    sessionId: json['sessionId'] as String,
    attemptId: json['attemptId'] as String,
  );
}

/// 草稿、进行中的会话指针、题目缓存。所有键都带用户 ID，换了账号不会看到上一个人的内容。
class DraftRecovery {
  const DraftRecovery({
    required this.copies,
    required this.pending,
    required this.generation,
  });
  final List<LocalDraft> copies;
  final bool pending;
  final int generation;
}

class PendingDraftCopy {
  const PendingDraftCopy({
    required this.snapshot,
    required this.sourceAttemptId,
    required this.observedRevision,
    required this.idempotencyKey,
    required this.recoveryGeneration,
    this.activationEpoch,
  });
  final LocalDraft snapshot;
  final String sourceAttemptId;
  final int observedRevision;
  final String idempotencyKey;
  final int recoveryGeneration;
  final int? activationEpoch;
  Map<String, dynamic> toJson() => {
    'snapshot': snapshot.toJson(),
    'sourceAttemptId': sourceAttemptId,
    'observedRevision': observedRevision,
    'idempotencyKey': idempotencyKey,
    'recoveryGeneration': recoveryGeneration,
    'activationEpoch': activationEpoch,
  };
  factory PendingDraftCopy.fromJson(Map<String, dynamic> json) {
    final raw = Map<String, dynamic>.from(json['snapshot'] as Map);
    if (raw['v'] != LocalDraft.formatVersion) {
      throw const FormatException('Unknown pending snapshot');
    }
    return PendingDraftCopy(
      snapshot: LocalDraft.fromJson(raw),
      sourceAttemptId: json['sourceAttemptId'] as String,
      observedRevision: json['observedRevision'] as int,
      idempotencyKey: json['idempotencyKey'] as String,
      recoveryGeneration: json['recoveryGeneration'] as int,
      activationEpoch: json['activationEpoch'] as int?,
    );
  }
}

String _canonical(dynamic value) {
  if (value is Map) {
    final keys = value.keys.cast<String>().toList()..sort();
    return '{${keys.map((key) => '${jsonEncode(key)}:${_canonical(value[key])}').join(',')}}';
  }
  if (value is List) return '[${value.map(_canonical).join(',')}]';
  return jsonEncode(value);
}

class DraftWorkspaceContext {
  DraftWorkspaceContext({
    required this.workspaceId,
    required Question question,
    required Map<String, dynamic> sessionBody,
    this.trustedSessionId,
  }) : question = Question.fromJson(question.toJson()),
       sessionBody = Map<String, dynamic>.unmodifiable(
         jsonDecode(jsonEncode(sessionBody)) as Map<String, dynamic>,
       );
  final String workspaceId;
  final Question question;
  final Map<String, dynamic> sessionBody;
  final String? trustedSessionId;
  Map<String, dynamic> toJson() => {
    'v': 1,
    'workspaceId': workspaceId,
    'question': question.toJson(),
    'sessionBody': sessionBody,
    'trustedSessionId': trustedSessionId,
  };
  factory DraftWorkspaceContext.fromJson(Map<String, dynamic> json) {
    if (json['v'] != 1 ||
        (json['question'] as Map)['version'] is! int ||
        (json['question'] as Map)['version'] < 1) {
      throw const FormatException('Unknown workspace context');
    }
    return DraftWorkspaceContext(
      workspaceId: json['workspaceId'] as String,
      question: Question.fromJson(
        Map<String, dynamic>.from(json['question'] as Map),
      ),
      sessionBody: Map<String, dynamic>.from(json['sessionBody'] as Map),
      trustedSessionId: json['trustedSessionId'] as String?,
    );
  }
}

class DraftCreationCommand {
  DraftCreationCommand({
    required this.intentId,
    required this.generation,
    required this.phase,
    required this.sessionKey,
    required this.attemptKey,
    required Map<String, dynamic> sessionBody,
    Map<String, dynamic>? attemptBody,
    this.sessionId,
    this.attemptId,
    this.blockedReason,
    this.resumePhase,
    this.questionVersion,
    this.activationEpoch,
    Map<String, dynamic>? transferPolicy,
  }) : transferPolicy = transferPolicy == null
           ? null
           : Map<String, dynamic>.unmodifiable(journalClone(transferPolicy)),
       sessionBody = Map<String, dynamic>.unmodifiable(
         jsonDecode(jsonEncode(sessionBody)) as Map<String, dynamic>,
       ),
       attemptBody = attemptBody == null
           ? null
           : Map<String, dynamic>.unmodifiable(
               jsonDecode(jsonEncode(attemptBody)) as Map<String, dynamic>,
             );
  final String intentId, phase, sessionKey, attemptKey;
  final Map<String, dynamic>? transferPolicy;
  final int generation;
  final int? questionVersion;
  final int? activationEpoch;
  final Map<String, dynamic> sessionBody;
  final Map<String, dynamic>? attemptBody;
  final String? sessionId, attemptId, blockedReason, resumePhase;
  static const phases = [
    'session_prepared',
    'session_known',
    'attempt_prepared',
    'attempt_known',
    'attached',
    'blocked',
  ];
  SessionCreate get sessionRequest =>
      SessionCreate.fromJson(Map<String, dynamic>.from(sessionBody));
  AttemptCreate get attemptRequest => AttemptCreate.fromJson(
    Map<String, dynamic>.from(
      attemptBody ?? (throw StateError('Attempt not prepared')),
    ),
  );
  Map<String, dynamic> toJson() => {
    'v': 1,
    'transferPolicy': transferPolicy,
    'intentId': intentId,
    'generation': generation,
    'phase': phase,
    'sessionKey': sessionKey,
    'attemptKey': attemptKey,
    'sessionBody': sessionBody,
    'attemptBody': attemptBody,
    'sessionId': sessionId,
    'attemptId': attemptId,
    'questionVersion': questionVersion,
    'activationEpoch': activationEpoch,
    'blockedReason': blockedReason,
    'resumePhase': resumePhase,
  };
  factory DraftCreationCommand.fromJson(Map<String, dynamic> json) {
    if (json['v'] != 1 || !phases.contains(json['phase'])) {
      throw const FormatException('Unknown creation command');
    }
    return DraftCreationCommand(
      transferPolicy: json['transferPolicy'] == null
          ? null
          : Map<String, dynamic>.from(json['transferPolicy'] as Map),
      intentId: json['intentId'] as String,
      generation: json['generation'] as int,
      phase: json['phase'] as String,
      sessionKey: json['sessionKey'] as String,
      attemptKey: json['attemptKey'] as String,
      sessionBody: Map<String, dynamic>.from(json['sessionBody'] as Map),
      attemptBody: json['attemptBody'] == null
          ? null
          : Map<String, dynamic>.from(json['attemptBody'] as Map),
      sessionId: json['sessionId'] as String?,
      attemptId: json['attemptId'] as String?,
      questionVersion: json['questionVersion'] as int?,
      activationEpoch: json['activationEpoch'] as int?,
      blockedReason: json['blockedReason'] as String?,
      resumePhase: json['resumePhase'] as String?,
    );
  }
}

class DraftStore {
  DraftStore(this._store, this.userId, {String? scopeId})
    : _scopeId = scopeId; // ignore: prefer_initializing_formals
  final String? _scopeId;
  DraftStore forAttempt(String attemptId) =>
      DraftStore(_store, userId, scopeId: 'attempt/$attemptId');
  DraftStore forLocal(String localId) =>
      DraftStore(_store, userId, scopeId: 'local/$localId');
  String _bundleKey(String id) => 'u/$userId/draft-bundle/$id';
  Future<Map<String, dynamic>> _bundle(
    String id, {
    bool requireExisting = false,
  }) async {
    final raw = await _store.read(_bundleKey(id));
    if (raw == null) {
      if (requireExisting) {
        throw const FormatException('Draft changed during export');
      }
      return {
        'v': 1,
        'drafts': <String, dynamic>{},
        'pending': <String, dynamic>{},
        'references': <String, dynamic>{},
      };
    }
    final json = jsonDecode(raw) as Map<String, dynamic>;
    if (json['v'] != 1 ||
        json['drafts'] is! Map ||
        json['pending'] is! Map ||
        json['references'] is! Map) {
      throw const FormatException('Unknown draft bundle preserved');
    }
    if (json.containsKey('active') && json['active'] != null) {
      ActiveRef.fromJson(Map<String, dynamic>.from(json['active'] as Map));
    }
    for (final value in (json['promotions'] as Map? ?? {}).values) {
      final record = Map<String, dynamic>.from(value as Map);
      final source = Map<String, dynamic>.from(record['source'] as Map);
      if (record['v'] != 1 ||
          source['v'] != LocalDraft.formatVersion ||
          LocalDraft.fromJson(source).questionId != id ||
          record['targetAttemptId'] is! String) {
        throw const FormatException('Unknown promotion preserved');
      }
    }
    for (final entry in (json['workspaceContexts'] as Map? ?? {}).entries) {
      final context = DraftWorkspaceContext.fromJson(
        Map<String, dynamic>.from(entry.value as Map),
      );
      if (entry.key != 'local/${context.workspaceId}' &&
          entry.key != 'attempt/${context.workspaceId}') {
        throw const FormatException('Context scope mismatch');
      }
      _verifyOrigin(context, id);
      if (context.question.id != id) {
        throw const FormatException('Context question mismatch');
      }
    }
    for (final entry in (json['creationIntents'] as Map? ?? {}).entries) {
      final record = entry.value as Map;
      final contextRaw = (json['workspaceContexts'] as Map? ?? {})[entry.key];
      if (contextRaw == null) {
        throw const FormatException('Command has no origin');
      }
      final context = DraftWorkspaceContext.fromJson(
        Map<String, dynamic>.from(contextRaw as Map),
      );
      final history = record['history'] as Map;
      if (!history.containsKey(record['current'])) {
        throw const FormatException('Missing command history');
      }
      for (final item in history.entries) {
        final value = item.value as Map;
        if (value['intentId'] != item.key) {
          throw const FormatException('Intent history key mismatch');
        }
        _validateCommand(
          DraftCreationCommand.fromJson(Map<String, dynamic>.from(value)),
          context,
        );
      }
    }
    if (json.containsKey('activeEpoch') &&
        (json['activeEpoch'] is! int || json['activeEpoch'] < 0)) {
      throw const FormatException('Invalid active epoch');
    }
    // Validate before any write, preserving unknown nested records too.
    for (final entry in (json['drafts'] as Map).entries) {
      final draft = Map<String, dynamic>.from(entry.value as Map);
      final scope = entry.key as String;
      if (scope.startsWith('attempt/')
          ? scope != 'attempt/${draft['attemptId']}'
          : !scope.startsWith('local/') || draft['attemptId'] != null) {
        throw const FormatException('Draft slot mismatch');
      }
      if (draft['v'] != LocalDraft.formatVersion ||
          LocalDraft.fromJson(draft).questionId != id) {
        throw const FormatException('Unknown draft preserved');
      }
    }
    for (final value in (json['pending'] as Map).values) {
      final pending = PendingDraftCopy.fromJson(
        Map<String, dynamic>.from(value as Map),
      );
      if (pending.snapshot.questionId != id) {
        throw const FormatException('Invalid pending');
      }
    }
    _validateWrites(json, id);
    return json;
  }

  int _activeEpoch(Map<String, dynamic> bundle) =>
      bundle['activeEpoch'] as int? ?? 0;
  Future<int> readActiveEpoch(String id) async =>
      _activeEpoch(await _bundle(id));
  void _advanceActiveEpoch(Map<String, dynamic> bundle) {
    bundle['activeEpoch'] = _activeEpoch(bundle) + 1;
  }

  String get _workspace =>
      _scopeId ?? (throw StateError('Creation requires scoped workspace'));
  void _verifyOrigin(DraftWorkspaceContext context, String id) {
    final body = context.sessionBody;
    if (body['question_id'] != id ||
        body['expected_question_version'] is! int ||
        body['expected_question_version'] < 1 ||
        body['expected_question_version'] != context.question.version ||
        body['origin'] is! String ||
        body.keys.any(
          (key) => ![
            'question_id',
            'origin',
            'review_item_id',
            'parent_session_id',
            'expected_question_version',
          ].contains(key),
        ) ||
        (body['review_item_id'] != null && body['review_item_id'] is! String) ||
        (body['parent_session_id'] != null &&
            body['parent_session_id'] is! String)) {
      throw const FormatException('Invalid origin request');
    }
    SessionCreate.fromJson(Map<String, dynamic>.from(body));
  }

  DraftWorkspaceContext? _context(Map<String, dynamic> bundle) {
    final raw = (bundle['workspaceContexts'] as Map? ?? {})[_workspace];
    return raw == null
        ? null
        : DraftWorkspaceContext.fromJson(Map<String, dynamic>.from(raw as Map));
  }

  DraftCreationCommand? _command(Map<String, dynamic> bundle) {
    final workspace =
        (bundle['creationIntents'] as Map? ?? {})[_workspace] as Map?;
    if (workspace == null) return null;
    final raw = (workspace['history'] as Map)[workspace['current']];
    if (raw == null) {
      throw const FormatException('Missing current creation command');
    }
    return DraftCreationCommand.fromJson(Map<String, dynamic>.from(raw as Map));
  }

  void _putCommand(Map<String, dynamic> bundle, DraftCreationCommand command) {
    final workspaces =
        (bundle['creationIntents'] ??= <String, dynamic>{}) as Map;
    final record =
        (workspaces[_workspace] ??= {
              'current': command.intentId,
              'history': <String, dynamic>{},
            })
            as Map;
    record['current'] = command.intentId;
    final history = record['history'] as Map;
    history[command.intentId] = {
      ...?history[command.intentId] as Map<String, dynamic>?,
      ...command.toJson(),
      if (command.activationEpoch == null &&
          (history[command.intentId] as Map?)?['activationEpoch'] != null)
        'activationEpoch':
            (history[command.intentId] as Map)['activationEpoch'],
    };
  }

  Future<DraftWorkspaceContext?> readWorkspaceContext(String id) async =>
      _context(await _bundle(id));
  Future<DraftCreationCommand?> readCreation(String id) async =>
      _command(await _bundle(id));
  Future<void> saveWorkspaceContext(String id, DraftWorkspaceContext context) =>
      _serial(id, () async {
        _checkLease(id);
        final bundle = await _bundle(id);
        _verifyOrigin(context, id);
        final previous = _context(bundle);
        if (previous != null) {
          if (_canonical(previous.toJson()) != _canonical(context.toJson())) {
            throw StateError('Workspace origin is immutable');
          }
          return;
        }
        if (context.question.id != id ||
            context.question.version < 1 ||
            context.sessionBody['question_id'] != id ||
            context.sessionBody['expected_question_version'] !=
                context.question.version ||
            _workspace.split('/').last != context.workspaceId) {
          throw StateError('Invalid workspace origin');
        }
        final draft = await readDraft(id);
        if (draft?.hasContent == true &&
            (draft?.sessionId == null ||
                context.trustedSessionId != draft?.sessionId)) {
          throw StateError('Old draft has no verified question version');
        }
        ((bundle['workspaceContexts'] ??= <String, dynamic>{})
            as Map)[_workspace] = context
            .toJson();
        await _store.write(_bundleKey(id), jsonEncode(bundle));
      });
  void _validateCommand(
    DraftCreationCommand command,
    DraftWorkspaceContext context,
  ) {
    _verifyOrigin(context, context.question.id);
    final transfer = command.transferPolicy;
    if (transfer != null &&
        (transfer.length != 2 ||
            transfer['kind'] != 'continuation' ||
            transfer['continuationId'] is! String)) {
      throw StateError('Invalid continuation transfer policy');
    }
    if (command.sessionBody['expected_question_version'] is! int) {
      throw StateError('Invalid expected version');
    }
    final phase = command.phase == 'blocked'
        ? command.resumePhase
        : command.phase;
    if (!DraftCreationCommand.phases.contains(command.phase) ||
        command.intentId.isEmpty ||
        command.generation < 1 ||
        command.sessionKey.isEmpty ||
        command.attemptKey.isEmpty ||
        command.sessionKey == command.attemptKey ||
        _canonical(command.sessionBody) != _canonical(context.sessionBody) ||
        phase == null ||
        phase == 'blocked' ||
        !DraftCreationCommand.phases.contains(phase)) {
      throw StateError('Invalid creation command');
    }
    if (phase == 'session_prepared' &&
        (command.sessionId != null ||
            command.attemptId != null ||
            command.attemptBody != null ||
            command.questionVersion != null)) {
      throw StateError('Prepared session cannot contain results');
    }
    if (phase == 'session_known' &&
        (command.attemptId != null || command.attemptBody != null)) {
      throw StateError('Session result cannot contain attempt request');
    }
    if (phase == 'attempt_prepared' && command.attemptId != null) {
      throw StateError('Prepared attempt cannot contain result');
    }
    if (phase != 'session_prepared' &&
        (command.sessionId == null ||
            command.questionVersion != context.question.version)) {
      throw StateError('Unverified session result');
    }
    if (['attempt_prepared', 'attempt_known', 'attached'].contains(phase) &&
        (command.attemptBody == null ||
            command.attemptBody!['session_id'] != command.sessionId ||
            command.attemptBody!.length != 1)) {
      throw StateError('Invalid attempt request');
    }
    if (['attempt_known', 'attached'].contains(phase) &&
        command.attemptId == null) {
      throw StateError('Missing attempt result');
    }
    if (command.phase == 'blocked' &&
        (command.blockedReason == null || command.blockedReason!.isEmpty)) {
      throw StateError('Missing blocked reason');
    }
  }

  Future<void> prepareCreation(
    String id,
    DraftCreationCommand command,
  ) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final context =
        _context(bundle) ??
        (throw StateError('Verified workspace context required'));
    _validateCommand(command, context);
    final transfer = command.transferPolicy;
    if (transfer != null) {
      final raw =
          (bundle['continuations'] as Map? ?? {})[transfer['continuationId']]
              as Map?;
      if (raw == null ||
          raw['consumedBy'] != null ||
          raw['sessionId'] != command.sessionId ||
          _workspace != 'attempt/${raw['sourceAttemptId']}' ||
          context.trustedSessionId != raw['sessionId']) {
        throw StateError('Continuation cannot transfer to this creation');
      }
    }
    final previous = _command(bundle);
    if (previous?.intentId == command.intentId) {
      if (_canonical(previous!.transferPolicy) !=
              _canonical(command.transferPolicy) ||
          previous.sessionKey != command.sessionKey ||
          previous.attemptKey != command.attemptKey ||
          _canonical(previous.sessionBody) != _canonical(command.sessionBody)) {
        throw StateError('Intent body changed');
      }
      return;
    }
    if (command.generation != 1 ||
        (previous != null && previous.phase != 'attached')) {
      throw StateError('Creation is already pending');
    }
    if (command.phase != 'session_prepared' &&
        !(command.phase == 'attempt_prepared' &&
            command.sessionId == context.trustedSessionId)) {
      throw StateError('Invalid initial creation phase');
    }
    final history =
        ((bundle['creationIntents'] as Map? ?? {})[_workspace]
                as Map?)?['history']
            as Map? ??
        {};
    for (final raw in history.values) {
      final old = DraftCreationCommand.fromJson(
        Map<String, dynamic>.from(raw as Map),
      );
      if ([old.sessionKey, old.attemptKey].contains(command.sessionKey) ||
          [old.sessionKey, old.attemptKey].contains(command.attemptKey)) {
        throw StateError('Completed keys cannot be reused');
      }
    }
    _putCommand(
      bundle,
      DraftCreationCommand.fromJson({
        ...command.toJson(),
        'activationEpoch': _activeEpoch(bundle),
      }),
    );
    await _store.write(_bundleKey(id), jsonEncode(bundle));
  });
  Future<void> advanceCreation(
    String id,
    DraftCreationCommand command, {
    required int expectedGeneration,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final previous =
        _command(bundle) ?? (throw StateError('No prepared creation'));
    final context = _context(bundle) ?? (throw StateError('Missing origin'));
    _validateCommand(command, context);
    if (previous.intentId != command.intentId ||
        previous.generation != expectedGeneration ||
        command.generation != expectedGeneration + 1 ||
        previous.sessionKey != command.sessionKey ||
        previous.attemptKey != command.attemptKey ||
        _canonical(previous.transferPolicy) !=
            _canonical(command.transferPolicy) ||
        (command.activationEpoch != null &&
            command.activationEpoch != previous.activationEpoch) ||
        _canonical(previous.sessionBody) != _canonical(command.sessionBody) ||
        (previous.attemptBody != null &&
            _canonical(previous.attemptBody) !=
                _canonical(command.attemptBody)) ||
        (previous.sessionId != null &&
            previous.sessionId != command.sessionId) ||
        (previous.attemptId != null &&
            previous.attemptId != command.attemptId)) {
      throw StateError('Creation changed or stale');
    }
    final from = previous.phase == 'blocked'
        ? previous.resumePhase
        : previous.phase;
    final to = command.phase;
    final valid = to == 'blocked'
        ? command.resumePhase == from
        : previous.phase == 'blocked'
        ? to == from
        : (from == 'session_prepared' && to == 'session_known') ||
              (from == 'session_known' && to == 'attempt_prepared') ||
              (from == 'attempt_prepared' && to == 'attempt_known');
    if (!valid || from == 'attached') {
      throw StateError('Invalid creation transition');
    }
    _putCommand(bundle, command);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
  });

  /// Enumerates retained local workspaces for explicit, read-only recovery UI.
  /// Bundle validation fails closed; no missing question version is inferred.
  Future<List<String>> listLocalWorkspaceIds(String id) async {
    final bundle = await _bundle(id);
    final ids = <String>{
      if (bundle['localId'] is String) bundle['localId'] as String,
    };
    for (final scope in {
      ...(bundle['drafts'] as Map).keys,
      ...(bundle['workspaceContexts'] as Map? ?? {}).keys,
    }) {
      if (scope is String && scope.startsWith('local/')) {
        ids.add(scope.substring('local/'.length));
      }
    }
    return List<String>.unmodifiable(ids);
  }

  Future<String> readOrCreateLocalId(String id) => _serial(id, () async {
    final bundle = await _bundle(id);
    final previous = bundle['localId'] as String?;
    if (previous != null) return previous;
    final localId = List.generate(
      16,
      (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
    ).join();
    bundle['localId'] = localId;
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return localId;
  });

  Future<void> _stageLocalPromotion(
    Map<String, dynamic> bundle,
    LocalDraft target,
  ) async {
    final id = target.questionId;
    final source = await readDraft(id);
    if (source == null) throw StateError('Local source is no longer available');
    String content(LocalDraft draft) {
      final json = draft.toJson();
      return jsonEncode({'answer': json['answer'], 'strokes': json['strokes']});
    }

    if (content(source) != content(target)) {
      throw StateError('Local draft changed during attachment');
    }
    final promotions = (bundle['promotions'] ??= <String, dynamic>{}) as Map;
    if (promotions.containsKey(_scopeId)) {
      throw StateError('Local source already transferred');
    }
    final drafts = bundle['drafts'] as Map;
    drafts.putIfAbsent('attempt/${target.attemptId}', target.toJson);
    promotions[_scopeId] = {
      'v': 1,
      'source': source.toJson(),
      'targetAttemptId': target.attemptId,
    };
    drafts.remove(_scopeId);
    final cleared = (bundle['cleared'] ??= <String>[]) as List;
    if (!cleared.contains(_scopeId)) cleared.add(_scopeId);
    if ('local/${bundle['localId']}' == _scopeId) {
      bundle.remove('localId');
      bundle['legacyLocalConsumed'] = true;
    }
    bundle['active'] = ActiveRef(
      sessionId: target.sessionId!,
      attemptId: target.attemptId!,
    ).toJson();
  }

  Future<String> newWorkspace(String id) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    // Bind any legacy default view to its old workspace before changing the
    // default. The original legacy bytes remain untouched and recoverable.
    final previousId = bundle['localId'] as String?;
    if (previousId != null) {
      final previous = await forLocal(previousId).readDraft(id);
      if (previous != null) {
        (bundle['drafts'] as Map).putIfAbsent(
          'local/$previousId',
          previous.toJson,
        );
      }
    }
    final localId = List.generate(
      16,
      (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
    ).join();
    bundle['localId'] = localId;
    // An explicit new workspace is empty even while legacy source bytes exist.
    // A first writeDraft removes this tombstone as for any cleared scope.
    ((bundle['cleared'] ??= <String>[]) as List).add('local/$localId');
    bundle['active'] = null;
    _advanceActiveEpoch(bundle);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    if (_scopeId != null) (_leases[_store] ??= {})[_leaseKey(id)] = Object();
    return localId;
  });

  /// One bundle write transfers ownership; legacy source bytes stay recoverable.
  Future<bool> promoteToAttempt(
    LocalDraft target, {
    int? expectedActiveEpoch,
  }) => _serial(target.questionId, () async {
    final id = target.questionId;
    _checkLease(id);
    if (!(_scopeId?.startsWith('local/') ?? false) ||
        target.attemptId == null ||
        target.sessionId == null) {
      throw StateError('Invalid promotion');
    }
    final bundle = await _bundle(id);
    if (expectedActiveEpoch != null &&
        expectedActiveEpoch != _activeEpoch(bundle)) {
      (bundle['drafts'] as Map).putIfAbsent(
        'attempt/${target.attemptId}',
        target.toJson,
      );
      (bundle['references'] as Map)[target.attemptId] = ActiveRef(
        sessionId: target.sessionId!,
        attemptId: target.attemptId!,
      ).toJson();
      await _store.write(_bundleKey(id), jsonEncode(bundle));
      return false;
    }
    await _stageLocalPromotion(bundle, target);
    _advanceActiveEpoch(bundle);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    (_leases[_store] ??= {})[_leaseKey(id)] = Object();
    return true;
  });
  Future<bool> attachCreation(
    LocalDraft target, {
    required String intentId,
    required int expectedGeneration,
  }) => _serial(target.questionId, () async {
    final id = target.questionId;
    _checkLease(id);
    final bundle = await _bundle(id);
    final command = _command(bundle) ?? (throw StateError('Missing creation'));
    final context = _context(bundle) ?? (throw StateError('Missing origin'));
    if (command.intentId != intentId ||
        command.generation != expectedGeneration ||
        command.phase != 'attempt_known' ||
        command.sessionId != target.sessionId ||
        command.attemptId != target.attemptId ||
        command.questionVersion != context.question.version) {
      throw StateError('Stale creation attachment');
    }
    final targetScope = 'attempt/${target.attemptId}';
    final contexts = bundle['workspaceContexts'] as Map;
    final targetContext = DraftWorkspaceContext(
      workspaceId: target.attemptId!,
      question: context.question,
      sessionBody: context.sessionBody,
      trustedSessionId: target.sessionId,
    );
    final previousContext = contexts[targetScope];
    if (previousContext != null &&
        _canonical(previousContext) != _canonical(targetContext.toJson())) {
      throw StateError('Target origin differs');
    }
    contexts.putIfAbsent(targetScope, targetContext.toJson);
    final intents = bundle['creationIntents'] as Map;
    if (!intents.containsKey(targetScope)) {
      final archived = jsonDecode(jsonEncode(intents[_workspace])) as Map;
      // The result exists in the target workspace; selecting it explicitly must
      // resume that attempt rather than replay the source activation command.
      (archived['history'] as Map)[command.intentId] = {
        ...command.toJson(),
        'phase': 'attached',
        'generation': command.generation + 1,
      };
      intents[targetScope] = archived;
    }
    if (command.activationEpoch == null ||
        command.activationEpoch != _activeEpoch(bundle)) {
      (bundle['drafts'] as Map).putIfAbsent(
        'attempt/${target.attemptId}',
        target.toJson,
      );
      (bundle['references'] as Map)[target.attemptId] = ActiveRef(
        sessionId: target.sessionId!,
        attemptId: target.attemptId!,
      ).toJson();
      await _store.write(_bundleKey(id), jsonEncode(bundle));
      return false;
    }
    final transfer = command.transferPolicy;
    if (transfer != null) {
      final raw =
          (bundle['continuations'] as Map? ?? {})[transfer['continuationId']]
              as Map?;
      if (raw == null ||
          raw['consumedBy'] != null ||
          raw['sessionId'] != target.sessionId ||
          raw['sourceAttemptId'] == target.attemptId ||
          _workspace != 'attempt/${raw['sourceAttemptId']}') {
        throw StateError('Continuation no longer available');
      }
      target = LocalDraft.fromJson({
        ...Map<String, dynamic>.from(raw['draft'] as Map),
        'sessionId': target.sessionId,
        'attemptId': target.attemptId,
        'baseRevision': target.baseRevision,
        'dirty': true,
      });
      final existing = (bundle['drafts'] as Map)[targetScope] as Map?;
      if (existing != null &&
          draftContentHash(
                LocalDraft.fromJson(Map<String, dynamic>.from(existing)),
              ) !=
              draftContentHash(target)) {
        throw StateError('Target attempt already contains another draft');
      }
      (bundle['drafts'] as Map)[targetScope] = target.toJson();
      ((bundle['editState'] ??= <String, dynamic>{}) as Map)[targetScope] = {
        'draftGeneration': raw['editGeneration'],
        'knownRevision': target.baseRevision,
      };
      raw['consumedBy'] = ActiveRef(
        sessionId: target.sessionId!,
        attemptId: target.attemptId!,
      ).toJson();
    }
    if (_workspace.startsWith('local/')) {
      await _stageLocalPromotion(bundle, target);
    } else {
      (bundle['drafts'] as Map).putIfAbsent(
        'attempt/${target.attemptId}',
        target.toJson,
      );
      bundle['active'] = ActiveRef(
        sessionId: target.sessionId!,
        attemptId: target.attemptId!,
      ).toJson();
    }
    _advanceActiveEpoch(bundle);
    final attached = DraftCreationCommand.fromJson({
      ...command.toJson(),
      'phase': 'attached',
      'generation': command.generation + 1,
    });
    _putCommand(bundle, attached);
    _bindUnboundSubmission(bundle, id, target, command.activationEpoch!);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    (_leases[_store] ??= {})[_leaseKey(id)] = Object();
    return true;
  });

  void _checkDraft(LocalDraft draft) {
    if (_scopeId != null &&
        (_scopeId.startsWith('attempt/')
            ? _scopeId != 'attempt/${draft.attemptId}'
            : draft.attemptId != null)) {
      throw StateError('Draft attempt does not match immutable scope');
    }
  }

  Future<List<ActiveRef>> readCopyReferences(String id) async {
    final bundle = await _bundle(id);
    return [
      for (final value in (bundle['references'] as Map).values)
        ActiveRef.fromJson(Map<String, dynamic>.from(value as Map)),
    ];
  }

  Future<PendingDraftCopy?> readPendingCopy(String id) async {
    final bundle = await _bundle(id);
    final value = (bundle['pending'] as Map)[_scopeId ?? 'legacy'];
    return value == null
        ? null
        : PendingDraftCopy.fromJson(Map<String, dynamic>.from(value as Map));
  }

  Future<void> savePendingCopy(String id, PendingDraftCopy pending) => _serial(
    id,
    () async {
      _checkDraft(pending.snapshot);
      _checkLease(id);
      if (pending.snapshot.questionId != id ||
          pending.sourceAttemptId != pending.snapshot.attemptId) {
        throw StateError('Invalid copy scope');
      }
      final recovery = await readRecovery(id);
      if (recovery == null ||
          recovery.generation != pending.recoveryGeneration ||
          !recovery.pending) {
        throw StateError('Recovery generation changed');
      }
      final bundle = await _bundle(id);
      final entries = bundle['pending'] as Map;
      final old = entries[_scopeId ?? 'legacy'];
      final newPayload = pending.toJson()..remove('activationEpoch');
      final oldPayload = old == null
          ? null
          : (Map<String, dynamic>.from(old as Map)
              ..remove('activationEpoch')
              ..remove('completedAttemptId'));
      if (oldPayload != null &&
          _canonical(oldPayload) != _canonical(newPayload)) {
        throw StateError('A pending copy already exists');
      }
      entries[_scopeId ?? 'legacy'] =
          old ?? {...pending.toJson(), 'activationEpoch': _activeEpoch(bundle)};
      await _store.write(_bundleKey(id), jsonEncode(bundle));
    },
  );
  Future<bool> completePendingCopy(
    String id, {
    required String idempotencyKey,
    required LocalDraft copy,
  }) => _serial(id, () async {
    if (copy.questionId != id ||
        copy.attemptId == null ||
        copy.sessionId == null) {
      throw StateError('Invalid copy response');
    }
    final bundle = await _bundle(id);
    final entries = bundle['pending'] as Map;
    final raw = entries[_scopeId ?? 'legacy'];
    final pending = raw == null
        ? null
        : PendingDraftCopy.fromJson(Map<String, dynamic>.from(raw as Map));
    final recovery = await readRecovery(id);
    final currentLease = (_leases[_store] ?? {})[_leaseKey(id)];
    final verified =
        (currentLease == null || identical(currentLease, _lease)) &&
        pending != null &&
        pending.idempotencyKey == idempotencyKey &&
        pending.sourceAttemptId == pending.snapshot.attemptId &&
        (_scopeId == null ||
            _scopeId == 'attempt/${pending.sourceAttemptId}') &&
        recovery?.pending == true &&
        recovery?.generation == pending.recoveryGeneration;
    final matches =
        verified &&
        pending.activationEpoch != null &&
        pending.activationEpoch == _activeEpoch(bundle);
    (bundle['references'] as Map)[copy.attemptId] = {
      'sessionId': copy.sessionId,
      'attemptId': copy.attemptId,
    };
    if (verified &&
        (copy.sessionId != pending.snapshot.sessionId ||
            copy.attemptId == pending.sourceAttemptId ||
            ((raw as Map)['completedAttemptId'] != null &&
                raw['completedAttemptId'] != copy.attemptId))) {
      throw StateError('Copy session mismatch');
    }
    if (verified) {
      (bundle['drafts'] as Map).putIfAbsent(
        'attempt/${copy.attemptId}',
        copy.toJson,
      );
      entries[_scopeId ?? 'legacy'] = {
        ...raw as Map,
        'completedAttemptId': copy.attemptId,
      };
    }
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return matches;
  });

  Future<void> acknowledgePendingCopy(
    String id, {
    required String idempotencyKey,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final entries = bundle['pending'] as Map;
    final raw = entries[_scopeId ?? 'legacy'] as Map?;
    if (raw == null) return;
    final active = await readActive(id);
    if (raw['idempotencyKey'] != idempotencyKey ||
        raw['completedAttemptId'] == null ||
        raw['completedAttemptId'] != active?.attemptId) {
      throw StateError('Copy activation is not durable');
    }
    entries.remove(_scopeId ?? 'legacy');
    await _store.write(_bundleKey(id), jsonEncode(bundle));
  });

  /// Explicit selection acknowledges a verified result without inventing an
  /// activation epoch for old commands. Recovery copies remain archived.
  Future<void> acknowledgeCopySelection(
    String id, {
    required String idempotencyKey,
    required ActiveRef selectedRef,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final entries = bundle['pending'] as Map;
    final raw = entries[_scopeId ?? 'legacy'] as Map?;
    if (raw == null) throw StateError('Missing pending copy');
    final pending = PendingDraftCopy.fromJson(Map<String, dynamic>.from(raw));
    final active = await readActive(id);
    final recovery = await readRecovery(id);
    if (pending.idempotencyKey != idempotencyKey ||
        pending.sourceAttemptId != pending.snapshot.attemptId ||
        (_scopeId != null &&
            _scopeId != 'attempt/${pending.sourceAttemptId}') ||
        pending.snapshot.sessionId != selectedRef.sessionId ||
        pending.sourceAttemptId == selectedRef.attemptId ||
        raw['completedAttemptId'] != selectedRef.attemptId ||
        active?.attemptId != selectedRef.attemptId ||
        active?.sessionId != selectedRef.sessionId ||
        recovery?.pending != true ||
        recovery?.generation != pending.recoveryGeneration) {
      throw StateError('Copy selection is not durable or no longer matches');
    }
    entries.remove(_scopeId ?? 'legacy');
    await _store.write(_bundleKey(id), jsonEncode(bundle));
  });

  final Object _lease = Object();
  static final Expando<Map<String, Object>> _leases = Expando();
  String _leaseKey(String id) => '$userId/$id/$_scopeId';
  Future<void> claimScope(String id) => _serial(id, () async {
    if (_scopeId != null) (_leases[_store] ??= {})[_leaseKey(id)] = _lease;
  });
  void _checkLease(String id) {
    if (_scopeId == null) return;
    final leases = _leases[_store] ??= {};
    final current = leases.putIfAbsent(_leaseKey(id), () => _lease);
    if (!identical(current, _lease)) {
      throw StateError('This editor scope has been replaced');
    }
  }

  final KeyValueStore _store;
  final String userId;
  bool sharesStorage(KeyValueStore candidate) => identical(_store, candidate);

  /// Read-only projections, never migrations or runnable recovery.
  Future<List<Map<String, dynamic>>> readExportQuestionCache({
    int limit = 1000,
  }) =>
      LocalSerial.run(_store, userId, () => _exportQuestionCache(this, limit));

  /// Read-only projections, never migrations or runnable recovery.
  Future<List<Map<String, dynamic>>> readExportWriteJournals({
    int limit = 1000,
  }) => LocalSerial.run(
    _store,
    userId,
    () => _exportPracticeJournals(this, limit),
  );

  /// Content only: never export raw bundles, credentials or replay commands.
  /// The shared owner queue prevents this isolate's edits during the read.
  Future<List<LocalDraft>> readExportDrafts() =>
      LocalSerial.run(_store, userId, () async {
        if (userId.isEmpty || userId.contains('/')) {
          throw const FormatException('Invalid export owner');
        }
        final drafts = <LocalDraft>[];
        void addDraft(dynamic value, String questionId) {
          drafts.add(_checkedExportDraft(value as Map, questionId));
        }

        void collect(dynamic value, String questionId) {
          if (value is Map) {
            if (value.containsKey('questionId') &&
                value.containsKey('answer') &&
                value.containsKey('savedAt')) {
              addDraft(value, questionId);
            } else {
              for (final item in value.values) {
                collect(item, questionId);
              }
            }
          } else if (value is List) {
            for (final item in value) {
              collect(item, questionId);
            }
          }
        }

        for (final family in [
          'draft',
          'draft-bundle',
          'draft-recovery',
          'draft-corrupt',
        ]) {
          final prefix = 'u/$userId/$family/';
          for (final key in await _store.keys(prefix)) {
            if (!key.startsWith(prefix) || family == 'draft-corrupt') {
              throw const FormatException('Unreadable draft preserved');
            }
            final questionId = key.substring(prefix.length).split('/').first;
            if (family == 'draft-bundle') {
              collect(await _bundle(questionId), questionId);
              continue;
            }
            final raw = await _store.read(key);
            if (raw == null) {
              throw const FormatException('Draft changed during export');
            }
            final value = jsonDecode(raw) as Map<String, dynamic>;
            if (family == 'draft') {
              addDraft(value, questionId);
            } else {
              if (value['v'] != 1 || value['copies'] is! List) {
                throw const FormatException('Unsupported recovery preserved');
              }
              for (final copy in value['copies'] as List) {
                addDraft(copy, questionId);
              }
            }
          }
        }
        return drafts;
      });
  Future<T> _serial<T>(String questionId, Future<T> Function() action) =>
      LocalSerial.run(_store, userId, action);

  /// Read inside ResourceJournalStore's shared owner queue. No nested queue.
  Future<ResourceSourceGuard> readResourceOrigin(
    String questionId, {
    int viewGeneration = 0,
  }) async {
    _checkLease(questionId);
    final bundle = await _bundle(questionId);
    final context =
        _context(bundle) ??
        (throw StateError('Verified resource origin required'));
    if (!_workspace.startsWith('attempt/') ||
        context.trustedSessionId == null) {
      throw StateError('Resource action requires a real session/attempt');
    }
    return ResourceSourceGuard({
      'owner': userId,
      'questionId': questionId,
      'questionVersion': context.question.version,
      'workspaceId': _workspace,
      'origin': context.sessionBody['origin'],
      'reviewId': context.sessionBody['review_item_id'],
      'sessionId': context.trustedSessionId,
      'attemptId': _workspace.substring('attempt/'.length),
      'editGeneration': _edit(bundle)['draftGeneration'],
      'activeEpoch': _activeEpoch(bundle),
      'viewGeneration': viewGeneration,
    });
  }

  Future<ConfirmedSubmissionEvidence> readConfirmedSubmission(
    String questionId, {
    required String firstAttemptId,
    required String submitIntentId,
  }) async {
    final proofStore = forAttempt(firstAttemptId);
    final bundle = await _bundle(questionId);
    final command = proofStore._write(
      bundle,
      'submit',
      intentId: submitIntentId,
    );
    if (command?.phase != 'acked' || command?.result == null) {
      throw StateError(
        'Recover and acknowledge the original submission receipt first',
      );
    }
    final result = SubmitResult.fromJson(command!.result!);
    final context =
        proofStore._context(bundle) ??
        (throw StateError('Submission origin context missing'));
    if (result.attempt.id != firstAttemptId ||
        result.attempt.submissionNo != 1 ||
        result.attempt.status != AttemptStatus.submitted ||
        result.evaluation.state != EvaluationState.verified ||
        result.session.questionId != questionId ||
        result.session.origin.toJson() != context.sessionBody['origin'] ||
        result.session.reviewItemId != context.sessionBody['review_item_id']) {
      throw StateError('Confirmed first verified submission required');
    }
    return ConfirmedSubmissionEvidence({
      'kind': 'submit_receipt',
      'owner': userId,
      'questionId': questionId,
      'questionVersion': command.questionVersion,
      'sessionId': command.sessionId,
      'reviewId': result.session.reviewItemId,
      'firstAttemptId': firstAttemptId,
      'submitIntentId': command.intentId,
      'submitKey': command.idempotencyKey,
      'resultHash': journalHash(command.result),
      'submissionNo': 1,
      'evaluationState': result.evaluation.state.toJson(),
    });
  }

  Future<WriteCommand?> findConfirmedFirstSubmission(
    String questionId,
    String sessionId,
  ) async {
    final bundle = await _bundle(questionId);
    WriteCommand? first;
    for (final scope in (bundle['writeJournal'] as Map? ?? {}).entries) {
      final lane = (scope.value as Map)['submit'] as Map?;
      if (lane == null) continue;
      for (final raw in (lane['history'] as Map).values) {
        final command = WriteCommand.fromJson(
          Map<String, dynamic>.from(raw as Map),
        );
        if (command.sessionId != sessionId) continue;
        if (!['acked', 'rejected'].contains(command.phase)) {
          throw StateError(
            'Recover unknown submission before locating its confirmed first result',
          );
        }
        if (command.phase != 'acked' || command.result == null) continue;
        final result = SubmitResult.fromJson(command.result!);
        if (result.attempt.submissionNo != 1 ||
            result.attempt.status != AttemptStatus.submitted ||
            result.evaluation.state != EvaluationState.verified) {
          continue;
        }
        if (first != null && first.attemptId != command.attemptId) {
          throw StateError('Conflicting first submission evidence');
        }
        first = command;
      }
    }
    return first;
  }

  Future<bool> hasUnresolvedSubmission(
    String questionId,
    String sessionId,
  ) async {
    final bundle = await _bundle(questionId);
    for (final scope in (bundle['writeJournal'] as Map? ?? {}).entries) {
      final record = (scope.value as Map)['submit'] as Map?;
      if (record == null || record['current'] == null) continue;
      final raw = (record['history'] as Map)[record['current']];
      final command = WriteCommand.fromJson(
        Map<String, dynamic>.from(raw as Map),
      );
      if (command.sessionId == sessionId &&
          !['acked', 'rejected'].contains(command.phase)) {
        return true;
      }
    }
    for (final raw in (bundle['unboundSubmissions'] as Map? ?? {}).values) {
      if (SubmissionCapture.fromJson(Map<String, dynamic>.from(raw as Map))
              .phase ==
          'local_prepared') {
        return true;
      }
    }
    return false;
  }

  String _recoveryKey(String id) =>
      'u/$userId/draft-recovery/$id${_scopeId == null ? '' : '/$_scopeId'}';

  Future<DraftRecovery?> readRecovery(String id) async {
    if (_scopeId == null) {
      final active = await readActive(id);
      if (active != null &&
          await _store.read(
                'u/$userId/draft-recovery/$id/attempt/${active.attemptId}',
              ) !=
              null) {
        return forAttempt(active.attemptId).readRecovery(id);
      }
    }
    final scopedRaw = await _store.read(_recoveryKey(id));
    final raw =
        scopedRaw ??
        (_scopeId == null
            ? null
            : await _store.read('u/$userId/draft-recovery/$id'));
    if (raw == null) return null;
    // Unknown/corrupt records are preserved in place and block replacement.
    final json = jsonDecode(raw) as Map<String, dynamic>;
    if (json['v'] != 1) throw const FormatException('无法读取本机副本，已保留原记录');
    final values = json['copies'] as List;
    if (values.any(
      (value) => (value as Map)['v'] != LocalDraft.formatVersion,
    )) {
      throw const FormatException('不认识的副本版本');
    }
    final copies = [
      for (final value in values)
        LocalDraft.fromJson(Map<String, dynamic>.from(value as Map)),
    ];
    if (copies.length < 2 || copies.any((copy) => copy.questionId != id)) {
      throw const FormatException('本机副本题目不匹配');
    }
    if (_scopeId != null &&
        scopedRaw == null &&
        copies.any((copy) => _scopeId != 'attempt/${copy.attemptId}')) {
      return null;
    }
    return DraftRecovery(
      copies: copies,
      pending: json['pending'] as bool,
      generation: json['generation'] as int? ?? copies.length ~/ 2,
    );
  }

  Future<DraftRecovery> archivePair(
    String id,
    LocalDraft local,
    LocalDraft server, {
    required bool pending,
    int? expectedGeneration,
  }) => _serial(id, () async {
    _checkLease(id);
    if (await readPendingCopy(id) != null) {
      throw StateError('Pending copy must be replayed first');
    }
    _checkDraft(local);
    _checkDraft(server);
    if (local.questionId != id || server.questionId != id) {
      throw StateError('Invalid recovery scope');
    }
    final previous = await readRecovery(id);
    if ((!pending && (previous?.pending ?? false)) ||
        (expectedGeneration != null &&
            expectedGeneration != previous?.generation)) {
      throw StateError('本机冲突记录已更新，请重新打开题目');
    }
    final copies = [...?previous?.copies, local, server];
    final generation = (previous?.generation ?? 0) + 1;
    await _store.write(
      _recoveryKey(id),
      jsonEncode({
        'v': 1,
        'pending': pending,
        'generation': generation,
        'copies': [
          for (final copy in previous?.copies ?? <LocalDraft>[]) copy.toJson(),
          local.toJson(),
          server.toJson(),
        ],
      }),
    );
    return DraftRecovery(
      copies: copies,
      pending: pending,
      generation: generation,
    );
  });

  Future<void> resolveRecovery(String id, {required int expectedGeneration}) =>
      _serial(id, () async {
        _checkLease(id);
        if (await readPendingCopy(id) != null) {
          throw StateError('Pending copy must be replayed first');
        }
        final previous = await readRecovery(id);
        if (previous == null || previous.generation != expectedGeneration) {
          throw StateError('本机冲突记录已更新，请重新打开题目');
        }
        await _store.write(
          _recoveryKey(id),
          jsonEncode({
            'v': 1,
            'pending': false,
            'generation': previous.generation,
            'copies': [for (final copy in previous.copies) copy.toJson()],
          }),
        );
      });

  String _draftKey(String questionId) => 'u/$userId/draft/$questionId';
  String _corruptKey(String questionId) =>
      'u/$userId/draft-corrupt/$questionId';
  String _activeKey(String questionId) => 'u/$userId/active/$questionId';
  String _questionKey(String questionId) =>
      'u/$userId/question/$questionId${_scopeId == null ? '' : '/$_scopeId'}';

  Future<LocalDraft?> readDraft(String questionId) async {
    if (_scopeId == null) {
      final active = await readActive(questionId);
      if (active != null) {
        final bundle = await _bundle(questionId);
        if ((bundle['drafts'] as Map).containsKey(
          'attempt/${active.attemptId}',
        )) {
          return forAttempt(active.attemptId).readDraft(questionId);
        }
      }
    }
    if (_scopeId != null) {
      final bundle = await _bundle(questionId);
      final drafts = bundle['drafts'] as Map;
      if ((bundle['cleared'] as List? ?? []).contains(_scopeId)) return null;
      final value = drafts[_scopeId];
      if (value != null) {
        return LocalDraft.fromJson(Map<String, dynamic>.from(value as Map));
      }
      final legacy = await _store.read(_draftKey(questionId));
      if (legacy == null) return null;
      final json = jsonDecode(legacy) as Map<String, dynamic>;
      if (json['v'] != LocalDraft.formatVersion) {
        throw const FormatException('Unknown legacy draft preserved');
      }
      final draft = LocalDraft.fromJson(json);
      if (draft.questionId != questionId) {
        throw const FormatException('Invalid legacy scope');
      }
      if (draft.attemptId == null && bundle['legacyLocalConsumed'] == true) {
        return null;
      }
      if (_scopeId == 'attempt/${draft.attemptId}' ||
          (_scopeId == 'local/${bundle['localId']}' &&
              draft.attemptId == null)) {
        return draft;
      }
      return null;
    }
    final raw = await _store.read(_draftKey(questionId));
    if (raw == null) return null;
    final bundle = await _bundle(questionId);
    try {
      final json = jsonDecode(raw) as Map<String, dynamic>;
      if (json['v'] != LocalDraft.formatVersion) {
        throw const FormatException('不认识的草稿版本');
      }
      final draft = LocalDraft.fromJson(json);
      if (draft.attemptId == null && bundle['legacyLocalConsumed'] == true) {
        return null;
      }
      if ((bundle['cleared'] as List? ?? []).contains(
        'attempt/${draft.attemptId}',
      )) {
        return null;
      }
      return draft;
    } catch (_) {
      // 读不懂的草稿不能悄悄丢掉：原文另存一份，之后可以人工找回
      await _store.write(_corruptKey(questionId), raw);
      await _store.delete(_draftKey(questionId));
      return null;
    }
  }

  Map<String, dynamic> _edit(Map<String, dynamic> bundle) {
    final edit =
        ((bundle['editState'] ??= <String, dynamic>{}) as Map).putIfAbsent(
          _workspace,
          () => <String, dynamic>{},
        ) as Map<String, dynamic>;
    // Promotion can establish a draft before any journal edit is recorded.
    // Missing counters consistently denote its initial persisted generation.
    for (final key in ['draftGeneration', 'marksGeneration', 'knownRevision']) {
      edit.putIfAbsent(key, () => 0);
    }
    return edit;
  }

  Map<String, dynamic> _lane(Map<String, dynamic> bundle, String lane) {
    if (!['draft_sync', 'submit', 'self_check'].contains(lane)) {
      throw StateError('Unknown write lane');
    }
    final scopes = (bundle['writeJournal'] ??= <String, dynamic>{}) as Map;
    final lanes =
        scopes.putIfAbsent(_workspace, () => <String, dynamic>{}) as Map;
    return lanes.putIfAbsent(
      lane,
      () => <String, dynamic>{'history': <String, dynamic>{}},
    ) as Map<String, dynamic>;
  }

  WriteCommand? _write(
    Map<String, dynamic> bundle,
    String lane, {
    String? intentId,
  }) {
    final record = _lane(bundle, lane);
    final raw = (record['history'] as Map)[intentId ?? record['current']];
    return raw == null
        ? null
        : WriteCommand.fromJson(Map<String, dynamic>.from(raw as Map));
  }

  void _putWrite(Map<String, dynamic> bundle, WriteCommand command) {
    final record = _lane(bundle, command.lane);
    record['current'] = command.intentId;
    (record['history'] as Map)[command.intentId] = command.toJson();
  }

  WriteCommand _casWrite(
    Map<String, dynamic> bundle,
    String lane,
    String intentId,
    int generation,
  ) {
    final command =
        _write(bundle, lane) ?? (throw StateError('Missing write command'));
    if (command.intentId != intentId || command.generation != generation) {
      throw StateError('Stale write command');
    }
    return command;
  }

  void _validateWrites(Map<String, dynamic> bundle, String id) {
    for (final entry in (bundle['unboundSubmissions'] as Map? ?? {}).entries) {
      final capture = SubmissionCapture.fromJson(
        Map<String, dynamic>.from(entry.value as Map),
      );
      final raw = capture.toJson();
      final contextRaw = (bundle['workspaceContexts'] as Map? ?? {})[entry.key];
      if (contextRaw == null ||
          raw['owner'] != userId ||
          raw['questionId'] != id ||
          raw['workspaceId'] != entry.key ||
          !(entry.key as String).startsWith('local/') ||
          capture.sourceSnapshot.questionId != id ||
          capture.sourceSnapshot.attemptId != null ||
          capture.sourceSnapshot.sessionId != null ||
          DraftWorkspaceContext.fromJson(
                Map<String, dynamic>.from(contextRaw as Map),
              ).question.version !=
              capture.questionVersion) {
        throw const FormatException('Unbound capture origin mismatch');
      }
    }
    for (final receiptEntry
        in (bundle['writeReceipts'] as Map? ?? {}).entries) {
      final raw = Map<String, dynamic>.from(receiptEntry.value as Map);
      final checksum = raw.remove('checksum');
      if (checksum != journalHash(raw) ||
          raw['v'] != 1 ||
          raw['owner'] != userId ||
          raw['questionId'] != id ||
          raw['intentId'] != receiptEntry.key) {
        throw const FormatException('Invalid write receipt preserved');
      }
    }
    for (final value in (bundle['editState'] as Map? ?? {}).values) {
      final edit = value as Map;
      for (final key in [
        'draftGeneration',
        'marksGeneration',
        'knownRevision',
      ]) {
        if (edit[key] != null && (edit[key] is! int || edit[key] < 0)) {
          throw const FormatException('Invalid edit generation');
        }
      }
      for (final key in ['marks', 'confirmedMarks']) {
        for (final mark in (edit[key] as Map? ?? {}).values) {
          if (!['done', 'partial', 'missed'].contains(mark)) {
            throw const FormatException('Invalid local self check marks');
          }
        }
      }
    }
    for (final entry in (bundle['continuations'] as Map? ?? {}).entries) {
      final value = entry.value as Map;
      final draft = LocalDraft.fromJson(
        Map<String, dynamic>.from(value['draft'] as Map),
      );
      if (value['v'] != 1 ||
          value['id'] != entry.key ||
          draft.questionId != id ||
          draft.sessionId != value['sessionId'] ||
          draft.attemptId != value['sourceAttemptId'] ||
          value['editGeneration'] is! int ||
          value['editGeneration'] < 0) {
        throw const FormatException('Invalid continuation preserved');
      }
    }
    for (final scope in (bundle['writeJournal'] as Map? ?? {}).entries) {
      for (final lane in (scope.value as Map).entries) {
        final record = lane.value as Map;
        if (record['current'] == null && (record['history'] as Map).isEmpty) {
          continue;
        }
        if (!(record['history'] as Map).containsKey(record['current'])) {
          throw const FormatException('Missing write history');
        }
        for (final entry in (record['history'] as Map).entries) {
          final command = WriteCommand.fromJson(
            Map<String, dynamic>.from(entry.value as Map),
          );
          final contextRaw =
              (bundle['workspaceContexts'] as Map? ?? {})[scope.key];
          if (contextRaw == null) {
            throw const FormatException('Write origin missing');
          }
          final context = DraftWorkspaceContext.fromJson(
            Map<String, dynamic>.from(contextRaw as Map),
          );
          final path = command.lane == 'submit'
              ? '/attempts/${command.attemptId}/submit'
              : command.lane == 'draft_sync'
              ? '/attempts/${command.attemptId}/draft'
              : '/attempts/${command.attemptId}/self-check';
          if (command.owner != userId ||
              command.questionId != id ||
              command.workspaceId != scope.key ||
              command.lane != lane.key ||
              command.intentId != entry.key ||
              scope.key != 'attempt/${command.attemptId}' ||
              command.sourceSnapshot.questionId != id ||
              command.sourceSnapshot.attemptId != command.attemptId ||
              command.sourceSnapshot.sessionId != command.sessionId ||
              command.questionVersion != context.question.version ||
              context.trustedSessionId != command.sessionId ||
              command.path != path ||
              command.method != (command.lane == 'submit' ? 'POST' : 'PUT')) {
            throw const FormatException('Write resource mismatch preserved');
          }
        }
      }
    }
  }

  Future<WriteCommand?> readWrite(String id, String lane) async =>
      _write(await _bundle(id), lane);
  Future<WriteEditState> readEditState(String id) async =>
      WriteEditState(_edit(await _bundle(id)));
  Future<WriteEditState> saveLocalMarks(
    String id,
    Map<String, SelfCheckLevel> marks, {
    bool confirmed = false,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final edit = _edit(bundle);
    final values = {
      for (final entry in marks.entries) entry.key: entry.value.toJson(),
    };
    if (_canonical(edit['marks'] ?? {}) != _canonical(values)) {
      edit['marksGeneration'] = (edit['marksGeneration'] as int? ?? 0) + 1;
    }
    edit['marks'] = values;
    if (confirmed) edit['confirmedMarks'] = values;
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return WriteEditState(edit);
  });
  void _compactWrite(Map<String, dynamic> bundle, String lane) {
    final previous = _write(bundle, lane);
    if (previous == null) return;
    if (!['acked', 'rejected'].contains(previous.phase)) {
      throw StateError('A write is still pending');
    }
    if (lane == 'submit') return;
    final receipt = {
      'v': 1,
      'owner': userId,
      'questionId': previous.questionId,
      'sessionId': previous.sessionId,
      'attemptId': previous.attemptId,
      'lane': lane,
      'intentId': previous.intentId,
      'idempotencyKey': previous.idempotencyKey,
      'sourceHash': previous.toJson()['sourceHash'],
      'phase': previous.phase,
      'revision': previous.result?['revision'],
      if (lane == 'self_check') 'marks': previous.body?['marks'],
    };
    final receipts = (bundle['writeReceipts'] ??= <String, dynamic>{}) as Map;
    receipt['checksum'] = journalHash(receipt);
    receipts[previous.intentId] = receipt;
    (_lane(bundle, lane)['history'] as Map).remove(previous.intentId);
  }

  WriteCommand _prepareWrite(
    Map<String, dynamic> bundle,
    String id,
    String lane,
    LocalDraft source,
    Map<String, dynamic>? body, {
    Map<String, dynamic>? answer,
    int? elapsedMs,
    String? syncIntentId,
    bool captureSource = false,
    String? dependencyFor,
    String? capturedIntentId,
    String? capturedKey,
  }) {
    _checkDraft(source);
    final context =
        _context(bundle) ?? (throw StateError('Verified origin required'));
    if (source.questionId != id ||
        source.attemptId == null ||
        source.sessionId != context.trustedSessionId) {
      throw StateError('Wrong write source');
    }
    final previousSubmit = _write(bundle, 'submit');
    if (lane == 'draft_sync' &&
        previousSubmit != null &&
        !['acked', 'rejected'].contains(previousSubmit.phase) &&
        !(previousSubmit.phase == 'waiting_dependency' &&
            previousSubmit.intentId == dependencyFor)) {
      throw StateError(
        'Recover original submission before syncing newer edits',
      );
    }
    final current = (bundle['drafts'] as Map)[_workspace];
    if (!captureSource &&
        lane != 'self_check' &&
        (current == null ||
            draftContentHash(
                  LocalDraft.fromJson(
                    Map<String, dynamic>.from(current as Map),
                  ),
                ) !=
                draftContentHash(source))) {
      throw StateError('Persist source before preparing write');
    }
    _compactWrite(bundle, lane);
    final edit = _edit(bundle);
    final intent = capturedIntentId ?? newIdempotencyKey('write-intent');
    final snapshot = source.toJson();
    if (lane == 'self_check') snapshot['strokes'] = null;
    final command = WriteCommand.create({
      'v': 1,
      'owner': userId,
      'questionId': id,
      'questionVersion': context.question.version,
      'workspaceId': _workspace,
      'sessionId': source.sessionId,
      'attemptId': source.attemptId,
      'lane': lane,
      'intentId': intent,
      'idempotencyKey': capturedKey ?? newIdempotencyKey(lane),
      'method': lane == 'submit' ? 'POST' : 'PUT',
      'path': lane == 'submit'
          ? '/attempts/${source.attemptId}/submit'
          : lane == 'draft_sync'
          ? '/attempts/${source.attemptId}/draft'
          : '/attempts/${source.attemptId}/self-check',
      'phase': lane == 'submit' ? 'awaiting_sync' : 'prepared',
      'generation': 1,
      'editGeneration':
          edit[lane == 'self_check' ? 'marksGeneration' : 'draftGeneration']
              as int? ??
          0,
      'activationEpoch': _activeEpoch(bundle),
      'sourceSnapshot': snapshot,
      'sourceHash': draftContentHash(source),
      'body': body,
      'result': null,
      'answer': ?answer,
      'elapsedMs': ?elapsedMs,
      'syncIntentId': ?syncIntentId,
    });
    _putWrite(bundle, command);
    return command;
  }

  Future<WriteCommand> prepareWrite(
    String id, {
    required String lane,
    required Map<String, dynamic> body,
    required LocalDraft sourceSnapshot,
  }) => _serial(id, () async {
    _checkLease(id);
    if (lane == 'submit') throw StateError('Submission needs sync dependency');
    final bundle = await _bundle(id);
    if (lane == 'draft_sync') DraftSync.fromJson(body);
    if (lane == 'self_check') {
      final marks = SelfCheckSave.fromJson(body).marks;
      if (_canonical({
            for (final mark in marks) mark.pointKey: mark.level.toJson(),
          }) !=
          _canonical(_edit(bundle)['marks'] ?? {})) {
        throw StateError('Persist marks before preparation');
      }
    }
    final command = _prepareWrite(bundle, id, lane, sourceSnapshot, body);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return command;
  });
  Map<String, dynamic> _syncReceipt(
    Map<String, dynamic> bundle,
    String intent,
  ) {
    final command = _write(bundle, 'draft_sync', intentId: intent);
    if (command != null) {
      if (command.phase != 'acked') {
        throw StateError('Sync is not acknowledged');
      }
      return {
        'sourceHash': command.toJson()['sourceHash'],
        'revision': command.result!['revision'],
        'attemptId': command.attemptId,
        'phase': command.phase,
      };
    }
    final raw = (bundle['writeReceipts'] as Map? ?? {})[intent] as Map?;
    if (raw == null || raw['phase'] != 'acked' || raw['lane'] != 'draft_sync') {
      throw StateError('Missing successful sync dependency');
    }
    final receipt = Map<String, dynamic>.from(raw)..remove('checksum');
    if (journalHash(receipt) != raw['checksum'] || raw['owner'] != userId) {
      throw const FormatException('Invalid receipt');
    }
    return receipt;
  }

  Future<SubmissionCapture?> readUnboundSubmission(String id) async {
    final bundle = await _bundle(id);
    final raw =
        (bundle['unboundSubmissions'] as Map? ?? {})[_workspace] as Map?;
    if (raw == null) return null;
    final capture = SubmissionCapture.fromJson(Map<String, dynamic>.from(raw));
    return capture.phase == 'local_prepared' ? capture : null;
  }

  Future<SubmissionCapture> prepareUnboundSubmission(
    String id, {
    required LocalDraft sourceSnapshot,
    required Map<String, dynamic> answer,
    required int elapsedMs,
    required Map<String, dynamic> bodyTemplate,
  }) => _serial(id, () async {
    _checkLease(id);
    if (!_workspace.startsWith('local/') ||
        sourceSnapshot.questionId != id ||
        sourceSnapshot.sessionId != null ||
        sourceSnapshot.attemptId != null ||
        elapsedMs < 0) {
      throw StateError('Invalid unbound source');
    }
    AnswerPayload.fromJson(answer);
    final template = DraftSync.fromJson(bodyTemplate);
    if (_canonical(template.strokes?.toJson()) !=
        _canonical(sourceSnapshot.strokes?.toJson())) {
      throw StateError('Capture ink mismatch');
    }
    final bundle = await _bundle(id);
    final context =
        _context(bundle) ??
        (throw StateError('Verified unbound origin required'));
    final captures =
        (bundle['unboundSubmissions'] ??= <String, dynamic>{}) as Map;
    if (captures.containsKey(_workspace)) {
      throw StateError('Unbound submission already captured');
    }
    final capture = SubmissionCapture.create({
      'v': 1,
      'owner': userId,
      'questionId': id,
      'questionVersion': context.question.version,
      'workspaceId': _workspace,
      'intentId': newIdempotencyKey('submit-capture'),
      'idempotencyKey': newIdempotencyKey('submit'),
      'phase': 'local_prepared',
      'sourceSnapshot': sourceSnapshot.toJson(),
      'answer': answer,
      'elapsedMs': elapsedMs,
      'bodyTemplate': bodyTemplate,
      'activationEpoch': _activeEpoch(bundle),
      'editGeneration': _edit(bundle)['draftGeneration'] as int? ?? 0,
    });
    captures[_workspace] = capture.toJson();
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return capture;
  });
  void _bindUnboundSubmission(
    Map<String, dynamic> bundle,
    String id,
    LocalDraft target,
    int creationEpoch,
  ) {
    final captures = bundle['unboundSubmissions'] as Map?;
    final raw = captures?[_workspace] as Map?;
    if (raw == null) return;
    final capture = SubmissionCapture.fromJson(Map<String, dynamic>.from(raw));
    if (capture.phase != 'local_prepared') return;
    if (capture.activationEpoch != creationEpoch) {
      throw StateError('Unbound selection changed');
    }
    final targetStore = forAttempt(target.attemptId!);
    final targetContext =
        targetStore._context(bundle) ??
        (throw StateError('Target origin missing'));
    if (targetContext.question.version != capture.questionVersion ||
        targetContext.trustedSessionId != target.sessionId) {
      throw StateError('Target capture version mismatch');
    }
    final boundSource = LocalDraft.fromJson({
      ...capture.sourceSnapshot.toJson(),
      'attemptId': target.attemptId,
      'sessionId': target.sessionId,
      'baseRevision': target.baseRevision,
    });
    final body = {
      ...capture.bodyTemplate,
      'base_revision': target.baseRevision,
    };
    final sync = targetStore._prepareWrite(
      bundle,
      id,
      'draft_sync',
      boundSource,
      body,
      captureSource: true,
    );
    targetStore._prepareWrite(
      bundle,
      id,
      'submit',
      boundSource,
      null,
      answer: capture.answer,
      elapsedMs: capture.elapsedMs,
      syncIntentId: sync.intentId,
      captureSource: true,
      capturedIntentId: capture.intentId,
      capturedKey: capture.idempotencyKey,
    );
    captures![_workspace] = SubmissionCapture.create({
      ...capture.toJson(),
      'phase': 'bound',
      'boundTo': ActiveRef(
        sessionId: target.sessionId!,
        attemptId: target.attemptId!,
      ).toJson(),
    }).toJson();
  }

  /// Captures the click-time A without replacing a newer persisted editor B.
  /// Both dependency and submit intent become durable in one bundle write.
  Future<({WriteCommand sync, WriteCommand submit})> prepareSubmissionCapture(
    String id, {
    required LocalDraft sourceSnapshot,
    required Map<String, dynamic> answer,
    required int elapsedMs,
    required Map<String, dynamic> body,
  }) => _serial(id, () async {
    _checkLease(id);
    if (elapsedMs < 0) throw StateError('Invalid elapsed');
    AnswerPayload.fromJson(answer);
    final request = DraftSync.fromJson(body);
    if (_canonical(request.strokes?.toJson()) !=
        _canonical(sourceSnapshot.strokes?.toJson())) {
      throw StateError('Sync ink differs from captured source');
    }
    final bundle = await _bundle(id);
    if ((bundle['drafts'] as Map)[_workspace] == null) {
      final edit = _edit(bundle);
      edit['draftGeneration'] = (edit['draftGeneration'] as int? ?? 0) + 1;
      edit['knownRevision'] = max(
        edit['knownRevision'] as int? ?? 0,
        sourceSnapshot.baseRevision,
      );
      (bundle['drafts'] as Map)[_workspace] = sourceSnapshot.toJson();
      (bundle['cleared'] as List?)?.remove(_workspace);
    }
    final pendingSync = _write(bundle, 'draft_sync');
    if (pendingSync != null &&
        !['acked', 'rejected'].contains(pendingSync.phase)) {
      final capture = _prepareWrite(
        bundle,
        id,
        'submit',
        sourceSnapshot,
        null,
        answer: answer,
        elapsedMs: elapsedMs,
        captureSource: true,
      );
      final waiting = WriteCommand.create({
        ...capture.toJson(),
        'phase': 'waiting_dependency',
        'waitingSyncIntentId': pendingSync.intentId,
        'pendingSyncBody': body,
      });
      _putWrite(bundle, waiting);
      await _store.write(_bundleKey(id), jsonEncode(bundle));
      return (sync: pendingSync, submit: waiting);
    }
    final sync = _prepareWrite(
      bundle,
      id,
      'draft_sync',
      sourceSnapshot,
      body,
      captureSource: true,
    );
    final submit = _prepareWrite(
      bundle,
      id,
      'submit',
      sourceSnapshot,
      null,
      answer: answer,
      elapsedMs: elapsedMs,
      syncIntentId: sync.intentId,
      captureSource: true,
    );
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return (sync: sync, submit: submit);
  });

  Future<({WriteCommand sync, WriteCommand submit})> prepareSubmitDependency(
    String id, {
    required String intentId,
    required int expectedGeneration,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final capture = _casWrite(bundle, 'submit', intentId, expectedGeneration);
    if (capture.phase != 'waiting_dependency') {
      throw StateError('No waiting dependency');
    }
    final dependency = _write(
      bundle,
      'draft_sync',
      intentId: capture.waitingSyncIntentId!,
    );
    if (dependency?.phase == 'result_known') {
      final edit = _edit(bundle);
      final revision = max(
        edit['knownRevision'] as int? ?? 0,
        dependency!.result!['revision'] as int,
      );
      edit['knownRevision'] = revision;
      final current = (bundle['drafts'] as Map)[_workspace] as Map?;
      if (current != null) {
        (bundle['drafts'] as Map)[_workspace] = {
          ...current,
          'baseRevision': revision,
          'dirty': true,
        };
      }
      _ackWrite(bundle, dependency);
    }
    final receipt = _syncReceipt(bundle, capture.waitingSyncIntentId!);
    if (receipt['attemptId'] != capture.attemptId) {
      throw StateError('Wrong waiting dependency resource');
    }
    final raw = capture.toJson();
    final revision = max(
      _edit(bundle)['knownRevision'] as int? ?? 0,
      receipt['revision'] as int,
    );
    final body = {
      ...Map<String, dynamic>.from(raw['pendingSyncBody'] as Map),
      'base_revision': revision,
    };
    final prepared = _prepareWrite(
      bundle,
      id,
      'draft_sync',
      capture.sourceSnapshot,
      body,
      captureSource: true,
      dependencyFor: capture.intentId,
    );
    final sync = WriteCommand.create({
      ...prepared.toJson(),
      'activationEpoch': capture.activationEpoch,
      'editGeneration': capture.editGeneration,
    });
    _putWrite(bundle, sync);
    final submit = WriteCommand.create({
      ...raw,
      'phase': 'awaiting_sync',
      'syncIntentId': sync.intentId,
      'generation': capture.generation + 1,
    });
    _putWrite(bundle, submit);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return (sync: sync, submit: submit);
  });

  Future<WriteCommand> prepareSubmit(
    String id, {
    required LocalDraft sourceSnapshot,
    required Map<String, dynamic> answer,
    required int elapsedMs,
    required String syncIntentId,
  }) => _serial(id, () async {
    _checkLease(id);
    if (elapsedMs < 0) throw StateError('Invalid elapsed');
    AnswerPayload.fromJson(answer);
    final bundle = await _bundle(id);
    final sync = _write(bundle, 'draft_sync', intentId: syncIntentId);
    final receipt = sync == null
        ? _syncReceipt(bundle, syncIntentId)
        : {
            'sourceHash': sync.toJson()['sourceHash'],
            'attemptId': sync.attemptId,
          };
    if (receipt['sourceHash'] != draftContentHash(sourceSnapshot) ||
        receipt['attemptId'] != sourceSnapshot.attemptId) {
      throw StateError('Wrong submission sync dependency');
    }
    final command = _prepareWrite(
      bundle,
      id,
      'submit',
      sourceSnapshot,
      null,
      answer: answer,
      elapsedMs: elapsedMs,
      syncIntentId: syncIntentId,
    );
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return command;
  });
  Future<WriteCommand> finalizeSubmit(
    String id, {
    required String intentId,
    required int expectedGeneration,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final command = _casWrite(bundle, 'submit', intentId, expectedGeneration);
    if (command.phase != 'awaiting_sync') {
      throw StateError('Submission already frozen');
    }
    final receipt = _syncReceipt(bundle, command.syncIntentId!);
    if (receipt['sourceHash'] != command.toJson()['sourceHash'] ||
        receipt['attemptId'] != command.attemptId) {
      throw StateError('Sync source mismatch');
    }
    final body = SubmitRequest(
      answer: AnswerPayload.fromJson(command.answer!),
      elapsedMs: command.elapsedMs!,
      expectedDraftRevision: receipt['revision'] as int,
    ).toJson();
    final next = WriteCommand.create({
      ...command.toJson(),
      'body': body,
      'phase': 'prepared',
      'generation': command.generation + 1,
    });
    _putWrite(bundle, next);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return next;
  });
  Future<WriteCommand> recordWriteResult(
    String id, {
    required String lane,
    required String intentId,
    required int expectedGeneration,
    required Map<String, dynamic> result,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final command = _casWrite(bundle, lane, intentId, expectedGeneration);
    if (command.phase != 'prepared') throw StateError('Write is not prepared');
    if (lane == 'draft_sync') {
      final draft = Draft.fromJson(result);
      if (draft.attemptId != command.attemptId || draft.revision < 0) {
        throw StateError('Wrong sync result');
      }
    } else if (lane == 'submit') {
      final submitted = SubmitResult.fromJson(result);
      if (submitted.attempt.id != command.attemptId ||
          submitted.attempt.sessionId != command.sessionId ||
          submitted.session.id != command.sessionId ||
          submitted.session.questionId != id ||
          submitted.session.questionVersion != command.questionVersion ||
          submitted.attempt.status != AttemptStatus.submitted) {
        throw StateError('Wrong submission result');
      }
    } else {
      final check = SelfCheck.fromJson(result);
      if (check.attemptId != command.attemptId ||
          _canonical({
                for (final mark in check.marks)
                  mark.pointKey: mark.level.toJson(),
              }) !=
              _canonical({
                for (final mark in SelfCheckSave.fromJson(command.body!).marks)
                  mark.pointKey: mark.level.toJson(),
              })) {
        throw StateError('Wrong self check result');
      }
    }
    final next = WriteCommand.create({
      ...command.toJson(),
      'result': result,
      'phase': 'result_known',
      'generation': command.generation + 1,
    });
    _putWrite(bundle, next);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return next;
  });
  void _ackWrite(Map<String, dynamic> bundle, WriteCommand command) =>
      _putWrite(
        bundle,
        WriteCommand.create({
          ...command.toJson(),
          'phase': 'acked',
          'generation': command.generation + 1,
        }),
      );
  Future<DraftWriteAck> ackDraftSync(
    String id, {
    required String intentId,
    required int expectedGeneration,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final command = _casWrite(
      bundle,
      'draft_sync',
      intentId,
      expectedGeneration,
    );
    if (command.phase != 'result_known') {
      throw StateError('Missing sync result');
    }
    final edit = _edit(bundle);
    final revision = command.result!['revision'] as int;
    final known = max(edit['knownRevision'] as int? ?? 0, revision);
    edit['knownRevision'] = known;
    final raw = (bundle['drafts'] as Map)[_workspace] as Map?;
    LocalDraft? currentDraft = raw == null
        ? null
        : LocalDraft.fromJson(Map<String, dynamic>.from(raw));
    final current =
        currentDraft != null &&
        (edit['draftGeneration'] as int? ?? 0) == command.editGeneration &&
        draftContentHash(currentDraft) == command.toJson()['sourceHash'] &&
        revision == known;
    if (currentDraft != null) {
      currentDraft = LocalDraft.fromJson({
        ...currentDraft.toJson(),
        'baseRevision': known,
        'dirty': !current,
      });
      (bundle['drafts'] as Map)[_workspace] = currentDraft.toJson();
    }
    _ackWrite(bundle, command);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return DraftWriteAck(
      current: current,
      revision: known,
      draft: currentDraft,
    );
  });
  Future<WriteEditState> ackSelfCheck(
    String id, {
    required String intentId,
    required int expectedGeneration,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final command = _casWrite(
      bundle,
      'self_check',
      intentId,
      expectedGeneration,
    );
    if (command.phase != 'result_known') {
      throw StateError('Missing self check result');
    }
    final edit = _edit(bundle);
    final marks = SelfCheck.fromJson(command.result!).marks;
    edit['confirmedMarks'] = {
      for (final mark in marks) mark.pointKey: mark.level.toJson(),
    };
    _ackWrite(bundle, command);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return WriteEditState(edit);
  });
  Future<DraftContinuation?> ackSubmit(
    String id, {
    required String intentId,
    required int expectedGeneration,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final command = _casWrite(bundle, 'submit', intentId, expectedGeneration);
    if (command.phase != 'result_known') {
      throw StateError('Missing submit result');
    }
    final raw = (bundle['drafts'] as Map)[_workspace] as Map?;
    final current = raw == null
        ? null
        : LocalDraft.fromJson(Map<String, dynamic>.from(raw));
    final edit = _edit(bundle);
    DraftContinuation? continuation;
    if (current != null &&
        ((edit['draftGeneration'] as int? ?? 0) != command.editGeneration ||
            draftContentHash(current) != command.toJson()['sourceHash'])) {
      final value = {
        'v': 1,
        'id': intentId,
        'sessionId': command.sessionId,
        'sourceAttemptId': command.attemptId,
        'editGeneration': edit['draftGeneration'] as int? ?? 0,
        'draft': {...current.toJson(), 'dirty': true},
      };
      ((bundle['continuations'] ??= <String, dynamic>{}) as Map)[intentId] =
          value;
      continuation = DraftContinuation(value);
    }
    (bundle['drafts'] as Map).remove(_workspace);
    final cleared = (bundle['cleared'] ??= <String>[]) as List;
    if (!cleared.contains(_workspace)) cleared.add(_workspace);
    _ackWrite(bundle, command);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return continuation;
  });
  Future<List<DraftContinuation>> readContinuations(String id) async {
    final bundle = await _bundle(id);
    return [
      for (final value in (bundle['continuations'] as Map? ?? {}).values)
        if ((value as Map)['consumedBy'] == null)
          DraftContinuation(Map<String, dynamic>.from(value)),
    ];
  }

  Future<WriteCommand> resumeWrite(
    String id, {
    required String lane,
    required String intentId,
    required int expectedGeneration,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final command = _casWrite(bundle, lane, intentId, expectedGeneration);
    if (command.phase != 'blocked') throw StateError('Write is not blocked');
    final raw = command.toJson();
    final next = WriteCommand.create({
      ...raw,
      'phase': raw['resumePhase'],
      'blockedReason': null,
      'generation': command.generation + 1,
    });
    _putWrite(bundle, next);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return next;
  });

  Future<WriteCommand> blockWrite(
    String id, {
    required String lane,
    required String intentId,
    required int expectedGeneration,
    required String reason,
    bool rejected = false,
  }) => _serial(id, () async {
    _checkLease(id);
    final bundle = await _bundle(id);
    final command = _casWrite(bundle, lane, intentId, expectedGeneration);
    if (![
      'prepared',
      'awaiting_sync',
      'waiting_dependency',
    ].contains(command.phase)) {
      throw StateError('Cannot block completed write');
    }
    final next = WriteCommand.create({
      ...command.toJson(),
      'phase': rejected ? 'rejected' : 'blocked',
      'blockedReason': reason,
      'resumePhase': command.phase,
      'generation': command.generation + 1,
    });
    _putWrite(bundle, next);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
    return next;
  });

  Future<void> writeDraft(LocalDraft draft) =>
      _serial(draft.questionId, () async {
        _checkDraft(draft);
        _checkLease(draft.questionId);
        if (_scopeId == null) {
          final previous = await _store.read(_draftKey(draft.questionId));
          if (previous != null) {
            final raw = jsonDecode(previous) as Map<String, dynamic>;
            if (raw['v'] != LocalDraft.formatVersion ||
                LocalDraft.fromJson(raw).questionId != draft.questionId) {
              throw const FormatException('Legacy raw preserved');
            }
          }
          await _store.write(
            _draftKey(draft.questionId),
            jsonEncode(draft.toJson()),
          );
          return;
        }
        // Reading validates any legacy raw record before replacing its view.
        await readDraft(draft.questionId);
        final bundle = await _bundle(draft.questionId);
        if ((bundle['promotions'] as Map? ?? {}).containsKey(_scopeId)) {
          throw StateError('Local source already transferred');
        }
        final previous = (bundle['drafts'] as Map)[_scopeId] as Map?;
        final edit = _edit(bundle);
        if (previous == null ||
            draftContentHash(
                  LocalDraft.fromJson(Map<String, dynamic>.from(previous)),
                ) !=
                draftContentHash(draft)) {
          edit['draftGeneration'] = (edit['draftGeneration'] as int? ?? 0) + 1;
        }
        edit['knownRevision'] = max(
          edit['knownRevision'] as int? ?? 0,
          draft.baseRevision,
        );
        (bundle['drafts'] as Map)[_scopeId] = draft.toJson();
        (bundle['cleared'] as List?)?.remove(_scopeId);
        await _store.write(_bundleKey(draft.questionId), jsonEncode(bundle));
      });
  Future<void> clearDraft(String id) => _serial(id, () async {
    _checkLease(id);
    if (_scopeId == null) return _store.delete(_draftKey(id));
    final bundle = await _bundle(id);
    (bundle['drafts'] as Map).remove(_scopeId);
    final cleared = (bundle['cleared'] ??= <String>[]) as List;
    if (!cleared.contains(_scopeId)) cleared.add(_scopeId);
    await _store.write(_bundleKey(id), jsonEncode(bundle));
  });

  Future<ActiveRef?> readActive(String questionId) async {
    final bundle = await _bundle(questionId);
    if (bundle.containsKey('active')) {
      final value = bundle['active'];
      return value == null
          ? null
          : ActiveRef.fromJson(Map<String, dynamic>.from(value as Map));
    }
    final raw = await _store.read(_activeKey(questionId));
    if (raw == null) return null;
    try {
      return ActiveRef.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      await _store.delete(_activeKey(questionId));
      return null;
    }
  }

  Future<bool> writeActive(
    String questionId,
    ActiveRef ref, {
    int? expectedEpoch,
  }) => _serial(questionId, () async {
    _checkLease(questionId);
    final bundle = await _bundle(questionId);
    if (expectedEpoch != null && expectedEpoch != _activeEpoch(bundle)) {
      return false;
    }
    bundle['active'] = ref.toJson();
    _advanceActiveEpoch(bundle);
    await _store.write(_bundleKey(questionId), jsonEncode(bundle));
    return true;
  });
  Future<void> clearActive(String questionId) => _serial(questionId, () async {
    _checkLease(questionId);
    final bundle = await _bundle(questionId);
    bundle['active'] = null;
    _advanceActiveEpoch(bundle);
    await _store.write(_bundleKey(questionId), jsonEncode(bundle));
  });

  /// 断网时用缓存继续显示题目。
  Future<Question?> readQuestion(String questionId) async {
    if (_scopeId != null) {
      final context = _context(await _bundle(questionId));
      if (context != null) return context.question;
    }
    var raw = await _store.read(_questionKey(questionId));
    if (raw == null && (_scopeId?.startsWith('local/') ?? false)) {
      final draft = await readDraft(questionId);
      if (draft?.sessionId == null) {
        raw = await _store.read('u/$userId/question/$questionId');
      }
    }
    if (raw == null) return null;
    try {
      return Question.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  Future<void> writeQuestion(Question question) =>
      _serial(question.id, () async {
        if (_scopeId != null) {
          _checkLease(question.id);
          final context = _context(await _bundle(question.id));
          if (context != null && context.question.version != question.version) {
            throw StateError('Workspace question version is pinned');
          }
        }
        await _store.write(
          _questionKey(question.id),
          jsonEncode(question.toJson()),
        );
      });
}
