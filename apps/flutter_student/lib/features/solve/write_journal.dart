import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import 'draft_store.dart';

String journalCanonical(dynamic value) {
  if (value is Map) {
    final keys = value.keys.cast<String>().toList()..sort();
    return '{${keys.map((k) => '${jsonEncode(k)}:${journalCanonical(value[k])}').join(',')}}';
  }
  if (value is List) return '[${value.map(journalCanonical).join(',')}]';
  return jsonEncode(value);
}

String journalHash(dynamic value) =>
    sha256.convert(utf8.encode(journalCanonical(value))).toString();
Map<String, dynamic> journalClone(Map value) =>
    jsonDecode(jsonEncode(value)) as Map<String, dynamic>;
String draftContentHash(LocalDraft draft) => journalHash({
  'answer': draft.toJson()['answer'],
  'strokes': draft.toJson()['strokes'],
});

/// Immutable wire request and source capture. Getters return detached values.
class WriteCommand {
  WriteCommand._(this._json);
  final Map<String, dynamic> _json;
  factory WriteCommand.create(Map<String, dynamic> value) {
    final json = journalClone(value)..remove('checksum');
    json['checksum'] = journalHash(json);
    return WriteCommand.fromJson(json);
  }
  factory WriteCommand.fromJson(Map<String, dynamic> value) {
    final json = journalClone(value);
    final checksum = json.remove('checksum');
    if (checksum != journalHash(json) ||
        json['v'] != 1 ||
        !['draft_sync', 'submit', 'self_check'].contains(json['lane']) ||
        ![
          'waiting_dependency',
          'awaiting_sync',
          'prepared',
          'result_known',
          'acked',
          'blocked',
          'rejected',
        ].contains(json['phase']) ||
        [
          'generation',
          'editGeneration',
          'activationEpoch',
          'questionVersion',
        ].any((k) => json[k] is! int || json[k] < 0)) {
      throw const FormatException('Unknown or damaged write command preserved');
    }
    json['checksum'] = checksum;
    return WriteCommand._(json);
  }
  Map<String, dynamic> toJson() => journalClone(_json);
  String get lane => _json['lane'] as String;
  String get phase => _json['phase'] as String;
  String get intentId => _json['intentId'] as String;
  String get idempotencyKey => _json['idempotencyKey'] as String;
  String get method => _json['method'] as String;
  String get path => _json['path'] as String;
  String get owner => _json['owner'] as String;
  String get questionId => _json['questionId'] as String;
  String get sessionId => _json['sessionId'] as String;
  String get attemptId => _json['attemptId'] as String;
  String get workspaceId => _json['workspaceId'] as String;
  int get generation => _json['generation'] as int;
  int get editGeneration => _json['editGeneration'] as int;
  int get activationEpoch => _json['activationEpoch'] as int;
  int get questionVersion => _json['questionVersion'] as int;
  int? get elapsedMs => _json['elapsedMs'] as int?;
  String? get syncIntentId => _json['syncIntentId'] as String?;
  String? get waitingSyncIntentId => _json['waitingSyncIntentId'] as String?;
  String? get blockedReason => _json['blockedReason'] as String?;
  LocalDraft get sourceSnapshot =>
      LocalDraft.fromJson(journalClone(_json['sourceSnapshot'] as Map));
  Map<String, dynamic>? get body =>
      _json['body'] == null ? null : journalClone(_json['body'] as Map);
  Map<String, dynamic>? get result =>
      _json['result'] == null ? null : journalClone(_json['result'] as Map);
  Map<String, dynamic>? get answer =>
      _json['answer'] == null ? null : journalClone(_json['answer'] as Map);
}

class WriteEditState {
  WriteEditState(Map<String, dynamic> json) : _json = journalClone(json);
  final Map<String, dynamic> _json;
  int get draftGeneration => _json['draftGeneration'] as int? ?? 0;
  int get marksGeneration => _json['marksGeneration'] as int? ?? 0;
  int get knownRevision => _json['knownRevision'] as int? ?? 0;
  Map<String, SelfCheckLevel> _marks(String key) => Map.unmodifiable({
    for (final entry in (_json[key] as Map? ?? {}).entries)
      entry.key as String: SelfCheckLevel.fromJson(entry.value),
  });
  Map<String, SelfCheckLevel> get marks => _marks('marks');
  Map<String, SelfCheckLevel> get confirmedMarks => _marks('confirmedMarks');
}

class DraftWriteAck {
  const DraftWriteAck({
    required this.current,
    required this.revision,
    required this.draft,
  });
  final bool current;
  final int revision;
  final LocalDraft? draft;
}

class DraftContinuation {
  DraftContinuation(Map<String, dynamic> json) : _json = journalClone(json);
  final Map<String, dynamic> _json;
  String get id => _json['id'] as String;
  String get sessionId => _json['sessionId'] as String;
  String get sourceAttemptId => _json['sourceAttemptId'] as String;
  int get editGeneration => _json['editGeneration'] as int;
  LocalDraft get draft =>
      LocalDraft.fromJson(journalClone(_json['draft'] as Map));
}

/// Click-time submit intent before a real Session/Attempt has been created.
/// It has no runnable request path/body until the 302 attachment commits.
class SubmissionCapture {
  SubmissionCapture._(this._json);
  final Map<String, dynamic> _json;
  factory SubmissionCapture.create(Map<String, dynamic> value) {
    final raw = journalClone(value)..remove('checksum');
    raw['checksum'] = journalHash(raw);
    return SubmissionCapture.fromJson(raw);
  }
  factory SubmissionCapture.fromJson(Map<String, dynamic> value) {
    final raw = journalClone(value);
    final checksum = raw.remove('checksum');
    if (checksum != journalHash(raw) ||
        raw['v'] != 1 ||
        !['local_prepared', 'bound'].contains(raw['phase']) ||
        [
          'elapsedMs',
          'activationEpoch',
          'questionVersion',
          'editGeneration',
        ].any((key) => raw[key] is! int || raw[key] < 0)) {
      throw const FormatException('Invalid unbound submission preserved');
    }
    raw['checksum'] = checksum;
    return SubmissionCapture._(raw);
  }
  Map<String, dynamic> toJson() => journalClone(_json);
  String get intentId => _json['intentId'] as String;
  String get idempotencyKey => _json['idempotencyKey'] as String;
  String get phase => _json['phase'] as String;
  int get elapsedMs => _json['elapsedMs'] as int;
  int get activationEpoch => _json['activationEpoch'] as int;
  int get editGeneration => _json['editGeneration'] as int;
  int get questionVersion => _json['questionVersion'] as int;
  LocalDraft get sourceSnapshot =>
      LocalDraft.fromJson(journalClone(_json['sourceSnapshot'] as Map));
  Map<String, dynamic> get answer => journalClone(_json['answer'] as Map);
  Map<String, dynamic> get bodyTemplate =>
      journalClone(_json['bodyTemplate'] as Map);
}
