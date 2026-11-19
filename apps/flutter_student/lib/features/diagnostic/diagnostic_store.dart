import 'dart:convert';

import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/local_serial.dart';
import '../../core/storage.dart';
import '../solve/write_journal.dart'
    show journalClone, journalHash, journalCanonical;

enum DiagnosticAction { create, open, abandon }

class DiagnosticCommand {
  DiagnosticCommand._(Map value) : _value = journalClone(value);
  final Map<String, dynamic> _value;
  String get key => _value['key'] as String;
  DiagnosticAction get action =>
      DiagnosticAction.values.byName(_value['action'] as String);
  String get phase => _value['phase'] as String;
  String? get runId => _value['runId'] as String?;
  int? get position => _value['position'] as int?;
  String? get questionId => _value['questionId'] as String?;
  int? get questionVersion => _value['questionVersion'] as int?;
  Map<String, dynamic> get body => journalClone(_value['body'] as Map);
  Map<String, dynamic>? get result =>
      _value['result'] == null ? null : journalClone(_value['result'] as Map);
  String? get code => _value['code'] as String?;
}

class DiagnosticBundle {
  DiagnosticBundle._(Map value) : _value = journalClone(value);
  final Map<String, dynamic> _value;
  DiagnosticWorkspace? get cloud => _value['cloud'] == null
      ? null
      : DiagnosticWorkspace.fromJson(journalClone(_value['cloud'] as Map));
  List<DiagnosticCommand> get commands => [
    for (final value in _value['commands'] as List)
      DiagnosticCommand._(value as Map),
  ];
  DiagnosticCommand? get pending {
    for (final command in commands) {
      if (command.phase == 'prepared' || command.phase == 'result_known') {
        return command;
      }
    }
    return null;
  }
}

/// One owner bundle; network calls never enter the local write queue.
class DiagnosticStore {
  DiagnosticStore(this.store, this.owner) {
    if (owner.isEmpty || owner.contains('/') || owner.contains('\\')) {
      throw ArgumentError('Invalid owner');
    }
  }
  final KeyValueStore store;
  final String owner;
  String get storageKey => 'u/$owner/diagnostic_bundle';

  Map<String, dynamic> _empty() => {
    'v': 1,
    'owner': owner,
    'cloud': null,
    'commands': <dynamic>[],
  };

  void _workspace(Map<String, dynamic> value) {
    if (value['revision'] is! int || value['revision'] < 0) {
      throw const FormatException('Unknown diagnostic revision');
    }
    final workspace = DiagnosticWorkspace.fromJson(value);
    final run = workspace.run;
    if (run == null) return;
    final summary = run.summary;
    final counts = [
      summary.submitted,
      summary.independentCorrect,
      summary.independentIncorrect,
      summary.assisted,
      summary.unconfirmed,
    ];
    if (!['active', 'completed', 'abandoned'].contains(run.status) ||
        run.items.length != 3 ||
        !run.items.map((item) => item.position).toSet().containsAll({
          1,
          2,
          3,
        }) ||
        run.items.map((item) => item.question.id).toSet().length != 3 ||
        counts.any((n) => n < 0 || n > 3) ||
        counts.skip(1).fold(0, (int a, int b) => a + b) != summary.submitted) {
      throw const FormatException('Unknown diagnostic plan');
    }
  }

  void _command(Map<String, dynamic> value) {
    final command = DiagnosticCommand._(value);
    if (!RegExp(r'^[A-Za-z0-9._:-]{8,128}$').hasMatch(command.key) ||
        ![
          'prepared',
          'result_known',
          'acked',
          'rejected',
          'stopped',
        ].contains(command.phase) ||
        command.body['expected_revision'] is! int ||
        command.body['expected_revision'] < 0) {
      throw const FormatException('Unknown diagnostic command');
    }
    final normalized = command.action == DiagnosticAction.create
        ? DiagnosticCreate.fromJson(command.body).toJson()
        : DiagnosticRevision.fromJson(command.body).toJson();
    if (journalCanonical(command.body) != journalCanonical(normalized)) {
      throw const FormatException('Changed diagnostic request');
    }
    if (command.action != DiagnosticAction.create &&
        (command.runId == null || command.runId!.isEmpty)) {
      throw const FormatException('Missing diagnostic target');
    }
    if (command.action == DiagnosticAction.open &&
        (command.position == null ||
            command.position! < 1 ||
            command.position! > 3 ||
            command.questionId == null ||
            command.questionVersion == null ||
            command.questionVersion! < 1)) {
      throw const FormatException('Missing question source');
    }
    if (command.result != null) _result(command, command.result!);
    if (['result_known', 'acked'].contains(command.phase) &&
        command.result == null) {
      throw const FormatException('Missing diagnostic receipt');
    }
  }

  void _result(DiagnosticCommand command, Map<String, dynamic> result) {
    if (command.action == DiagnosticAction.open) {
      final session = StudySession.fromJson(result);
      if (session.questionId != command.questionId ||
          session.questionVersion != command.questionVersion ||
          session.origin != SessionOrigin.practice) {
        throw const FormatException('Wrong diagnostic session');
      }
    } else {
      _workspace(result);
      final value = DiagnosticWorkspace.fromJson(result);
      if (value.revision != command.body['expected_revision'] + 1 ||
          value.run == null) {
        throw const FormatException('Wrong diagnostic receipt revision');
      }
      if (command.action == DiagnosticAction.create &&
          (value.run!.subject.toJson() != command.body['subject'] ||
              value.run!.scope.profileRevision !=
                  command.body['expected_profile_revision'])) {
        throw const FormatException('Wrong diagnostic creation receipt');
      }
      if (command.action == DiagnosticAction.abandon &&
          (value.run!.id != command.runId ||
              value.run!.status != 'abandoned')) {
        throw const FormatException('Wrong diagnostic abandonment receipt');
      }
    }
  }

  Future<Map<String, dynamic>> _read() async {
    final raw = await store.read(storageKey);
    if (raw == null) return _empty();
    if (raw.length > 2 * 1024 * 1024) {
      throw const FormatException('Diagnostic history too large');
    }
    final value = journalClone(jsonDecode(raw) as Map);
    final checksum = value.remove('checksum');
    if (checksum != journalHash(value) ||
        value['v'] != 1 ||
        value['owner'] != owner ||
        value['commands'] is! List) {
      throw const FormatException('Damaged diagnostic history preserved');
    }
    if (value['cloud'] != null) _workspace(journalClone(value['cloud'] as Map));
    final keys = <String>{};
    var pending = 0;
    for (final raw in value['commands'] as List) {
      final item = journalClone(raw as Map);
      _command(item);
      if (!keys.add(item['key'] as String)) {
        throw const FormatException('Duplicate diagnostic key');
      }
      if (['prepared', 'result_known'].contains(item['phase'])) pending++;
    }
    if (pending > 1) {
      throw const FormatException('Conflicting diagnostic commands');
    }
    return value;
  }

  Future<void> _write(Map<String, dynamic> value) async {
    final encoded = jsonEncode({...value, 'checksum': journalHash(value)});
    // ponytail: keep bounded history intact; archive only after export and retention are defined.
    if (encoded.length > 2 * 1024 * 1024 ||
        (value['commands'] as List).length > 200) {
      throw StateError('摸底本机记录已满，现有记录已保留');
    }
    await store.write(storageKey, encoded);
  }

  Future<DiagnosticBundle> read() => LocalSerial.run(
    store,
    storageKey,
    () async => DiagnosticBundle._(await _read()),
  );
  Future<DiagnosticWorkspace?> cloud() async => (await read()).cloud;

  Future<Map<String, dynamic>> exportSnapshot() =>
      LocalSerial.run(store, storageKey, () async {
        final bundle = DiagnosticBundle._(await _read());
        return {
          'format_version': 1,
          'scope': 'local_diagnostic_records',
          'owner_id': owner,
          'workspace': bundle.cloud?.toJson(),
          'commands': [
            for (final command in bundle.commands)
              {
                'key': command.key,
                'action': command.action.name,
                'phase': command.phase,
                'run_id': command.runId,
                'position': command.position,
                'question_id': command.questionId,
                'question_version': command.questionVersion,
                'body': command.body,
                'result': command.result == null
                    ? null
                    : command.action == DiagnosticAction.open
                    ? StudySession.fromJson(command.result!).toJson()
                    : DiagnosticWorkspace.fromJson(command.result!).toJson(),
                'code': command.code,
              },
          ],
        };
      });

  Future<void> rememberCloud(DiagnosticWorkspace workspace) =>
      LocalSerial.run(store, storageKey, () async {
        final next = workspace.toJson();
        _workspace(next);
        final value = await _read();
        final previous = DiagnosticBundle._(value).cloud;
        if (previous != null) {
          if (workspace.revision < previous.revision) return;
          if (workspace.revision == previous.revision && previous.run != null) {
            if (workspace.run?.id != previous.run!.id) {
              throw StateError('同版本摸底来源不同，保留本机记录');
            }
            for (final item in previous.run!.items) {
              final current = workspace.run!.items.singleWhere(
                (n) => n.position == item.position,
              );
              if (current.question.id != item.question.id ||
                  current.questionVersion != item.questionVersion ||
                  (item.sessionId != null &&
                      item.sessionId != current.sessionId)) {
                throw StateError('同版本摸底题目不同，保留本机记录');
              }
              if (item.submission != null &&
                  current.submission?.attemptId != item.submission!.attemptId) {
                return;
              }
            }
          }
        }
        value['cloud'] = next;
        await _write(value);
      });

  Future<DiagnosticCommand> prepareCreate(DiagnosticCreate body, String key) =>
      _prepare(DiagnosticAction.create, body.toJson(), key);
  Future<DiagnosticCommand> prepareOpen(
    String runId,
    int position,
    DiagnosticRevision body,
    String key,
  ) => _prepare(
    DiagnosticAction.open,
    body.toJson(),
    key,
    runId: runId,
    position: position,
  );
  Future<DiagnosticCommand> prepareAbandon(
    String runId,
    DiagnosticRevision body,
    String key,
  ) => _prepare(DiagnosticAction.abandon, body.toJson(), key, runId: runId);

  Future<DiagnosticCommand> _prepare(
    DiagnosticAction action,
    Map<String, dynamic> body,
    String key, {
    String? runId,
    int? position,
  }) => LocalSerial.run(store, storageKey, () async {
    final value = await _read();
    final bundle = DiagnosticBundle._(value);
    final cloud = bundle.cloud;
    if (bundle.pending != null ||
        cloud == null ||
        cloud.revision != body['expected_revision'] ||
        bundle.commands.any((c) => c.key == key)) {
      throw StateError('请先恢复未完成操作并刷新摸底进度');
    }
    if (action == DiagnosticAction.create && cloud.run?.status == 'active') {
      throw StateError('请先继续或明确结束当前摸底');
    }
    if (action != DiagnosticAction.create &&
        (cloud.run?.id != runId || cloud.run?.status == 'abandoned')) {
      throw StateError('当前摸底来源已变化');
    }
    DiagnosticItem? item;
    if (action == DiagnosticAction.open) {
      item = cloud.run!.items.singleWhere((item) => item.position == position);
    }
    final command = {
      'key': key,
      'action': action.name,
      'phase': 'prepared',
      'body': journalClone(body),
      'runId': runId,
      'position': position,
      'questionId': item?.question.id,
      'questionVersion': item?.questionVersion,
      'result': null,
      'code': null,
    };
    _command(command);
    (value['commands'] as List).add(command);
    await _write(value);
    return DiagnosticCommand._(command);
  });

  Future<void> recordResult(String key, Map<String, dynamic> result) =>
      _change(key, (command) {
        final saved = DiagnosticCommand._(command);
        _result(saved, result);
        if (saved.result != null &&
            journalCanonical(saved.result) != journalCanonical(result)) {
          throw StateError('原操作已有不同回执，保留双方来源');
        }
        command['result'] = journalClone(result);
        // Explicitly stopped/rejected history never becomes an active command again.
        if (saved.phase == 'prepared') command['phase'] = 'result_known';
      });

  Future<void> acknowledge(String key) => _change(key, (command) {
    if (command['phase'] != 'result_known') throw StateError('没有可确认的摸底回执');
    command['phase'] = 'acked';
  });

  Future<void> stop(String key) => _change(key, (command) {
    if (command['phase'] != 'prepared') throw StateError('当前操作不能停止重试');
    command['phase'] = 'stopped';
  });

  Future<void> reject(String key, String code) => _change(key, (command) {
    if (command['phase'] != 'prepared') throw StateError('摸底操作状态已变化');
    command['phase'] = 'rejected';
    command['code'] = code;
  });

  Future<void> _change(
    String key,
    void Function(Map<String, dynamic>) change,
  ) => LocalSerial.run(store, storageKey, () async {
    final value = await _read();
    final command = (value['commands'] as List)
        .cast<Map<String, dynamic>>()
        .singleWhere((c) => c['key'] == key);
    change(command);
    _command(command);
    await _write(value);
  });
}
