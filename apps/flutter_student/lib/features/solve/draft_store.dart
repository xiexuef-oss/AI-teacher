import 'dart:convert';

import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/storage.dart';

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
  final StrokeDoc? strokes;
  final DateTime savedAt;

  bool get hasContent =>
      selected.isNotEmpty ||
      blanks.values.any((v) => v.trim().isNotEmpty) ||
      (strokes?.pages.any((p) => p.strokes.isNotEmpty) ?? false);

  Map<String, dynamic> toJson() => {
    'v': formatVersion,
    'questionId': questionId,
    'sessionId': sessionId,
    'attemptId': attemptId,
    'baseRevision': baseRevision,
    'dirty': dirty,
    'answer': {'selected': selected, 'blanks': blanks},
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
class DraftStore {
  DraftStore(this._store, this.userId);

  final KeyValueStore _store;
  final String userId;

  String _draftKey(String questionId) => 'u/$userId/draft/$questionId';
  String _corruptKey(String questionId) =>
      'u/$userId/draft-corrupt/$questionId';
  String _activeKey(String questionId) => 'u/$userId/active/$questionId';
  String _questionKey(String questionId) => 'u/$userId/question/$questionId';

  Future<LocalDraft?> readDraft(String questionId) async {
    final raw = await _store.read(_draftKey(questionId));
    if (raw == null) return null;
    try {
      final json = jsonDecode(raw) as Map<String, dynamic>;
      if (json['v'] != LocalDraft.formatVersion) {
        throw const FormatException('不认识的草稿版本');
      }
      return LocalDraft.fromJson(json);
    } catch (_) {
      // 读不懂的草稿不能悄悄丢掉：原文另存一份，之后可以人工找回
      await _store.write(_corruptKey(questionId), raw);
      await _store.delete(_draftKey(questionId));
      return null;
    }
  }

  Future<void> writeDraft(LocalDraft draft) =>
      _store.write(_draftKey(draft.questionId), jsonEncode(draft.toJson()));

  Future<void> clearDraft(String questionId) =>
      _store.delete(_draftKey(questionId));

  Future<ActiveRef?> readActive(String questionId) async {
    final raw = await _store.read(_activeKey(questionId));
    if (raw == null) return null;
    try {
      return ActiveRef.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      await _store.delete(_activeKey(questionId));
      return null;
    }
  }

  Future<void> writeActive(String questionId, ActiveRef ref) =>
      _store.write(_activeKey(questionId), jsonEncode(ref.toJson()));

  Future<void> clearActive(String questionId) =>
      _store.delete(_activeKey(questionId));

  /// 断网时用缓存继续显示题目。
  Future<Question?> readQuestion(String questionId) async {
    final raw = await _store.read(_questionKey(questionId));
    if (raw == null) return null;
    try {
      return Question.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  Future<void> writeQuestion(Question question) =>
      _store.write(_questionKey(question.id), jsonEncode(question.toJson()));
}
