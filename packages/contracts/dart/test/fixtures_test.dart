// 用服务端真实返回的样例（tools/export_dart_fixtures.py 导出）检查生成的模型：
// 解析后再序列化，除契约允许省略的 optional nullable null 外必须一致。
import 'dart:convert';
import 'dart:io';

import 'package:test/test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import 'round_trip.g.dart';

Map<String, dynamic> canonicalJson(String schema, Map<String, dynamic> json) {
  final metadata = roundTripMetadata[schema] as Map<String, dynamic>?;
  if (metadata == null) return json;
  final nullable = metadata['nullable'] as List;
  final objects = metadata['objects'] as Map;
  final arrays = metadata['arrays'] as Map;
  return {
    for (final entry in json.entries)
      if (!(entry.value == null && nullable.contains(entry.key)))
        entry.key: objects.containsKey(entry.key) && entry.value is Map
            ? canonicalJson(objects[entry.key] as String,
                Map<String, dynamic>.from(entry.value as Map))
            : arrays.containsKey(entry.key) && entry.value is List
                ? [
                    for (final value in entry.value as List)
                      if (value is Map)
                        canonicalJson(arrays[entry.key] as String,
                            Map<String, dynamic>.from(value))
                      else
                        value,
                  ]
                : entry.value,
  };
}

/// 深度比较。数字按值比较（1 与 1.0 相同）；两个都是 ISO-8601 时间的字符串按时刻比较
/// （服务端写 `...:00Z`，Dart 序列化成 `...:00.000Z`）。
bool deepEquals(Object? a, Object? b) {
  if (a is Map && b is Map) {
    if (a.length != b.length) return false;
    for (final key in a.keys) {
      if (!b.containsKey(key) || !deepEquals(a[key], b[key])) return false;
    }
    return true;
  }
  if (a is List && b is List) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (!deepEquals(a[i], b[i])) return false;
    }
    return true;
  }
  if (a is num && b is num) return a == b;
  if (a is String && b is String) {
    if (a == b) return true;
    final looksLikeTime = RegExp(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}');
    if (looksLikeTime.hasMatch(a) && looksLikeTime.hasMatch(b)) {
      final da = DateTime.tryParse(a);
      final db = DateTime.tryParse(b);
      return da != null && db != null && da.isAtSameMomentAs(db);
    }
    return false;
  }
  return a == b;
}

Iterable<Map<String, dynamic>> findEvents(Object? node) sync* {
  if (node is Map) {
    if (node.containsKey('seq_no') &&
        node.containsKey('payload') &&
        node.containsKey('meta')) {
      yield Map<String, dynamic>.from(node);
    }
    for (final value in node.values) {
      yield* findEvents(value);
    }
  } else if (node is List) {
    for (final value in node) {
      yield* findEvents(value);
    }
  }
}

void main() {
  test('拍题导出区分已保存文字、空列表、未提供范围和旧文件缺失', () {
    final fixture = jsonDecode(
        File('test/fixtures/student_learning_export.json')
            .readAsStringSync()) as Map;
    final json = Map<String, dynamic>.from(fixture['value'] as Map);
    final current = StudentLearningExport.fromJson(json);
    expect(current.storedScanRecords, isNotEmpty);
    expect(current.storedScanRecords!.first.scan.stemText, isNotEmpty);
    json['stored_scan_records'] = [];
    expect(StudentLearningExport.fromJson(json).storedScanRecords, isEmpty);
    json['stored_scan_records'] = null;
    expect(StudentLearningExport.fromJson(json).storedScanRecords, isNull);
    json.remove('stored_scan_records');
    final old = StudentLearningExport.fromJson(json);
    expect(old.storedScanRecords, isNull);
    expect(old.toJson().containsKey('stored_scan_records'), false);
  });
  test('旧学习导出缺少授权范围表示未知，新范围保留历史不完整标记', () {
    final fixture = jsonDecode(
        File('test/fixtures/student_learning_export.json')
            .readAsStringSync()) as Map;
    final json = Map<String, dynamic>.from(fixture['value'] as Map);
    final current = StudentLearningExport.fromJson(json);
    expect(current.parentAccessRecords?.historyComplete, false);
    expect(current.parentAccessRecords?.links, isNotEmpty);
    json.remove('parent_access_records');
    final old = StudentLearningExport.fromJson(json);
    expect(old.parentAccessRecords, isNull);
    expect(old.toJson().containsKey('parent_access_records'), false);
  });
  final files = Directory('test/fixtures')
      .listSync()
      .whereType<File>()
      .where((f) => f.path.endsWith('.json'))
      .toList()
    ..sort((a, b) => a.path.compareTo(b.path));

  test('样例已导出', () {
    expect(files.length, greaterThanOrEqualTo(35),
        reason: '先运行 uv run python tools/export_dart_fixtures.py');
  });

  for (final file in files) {
    final fixture = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
    final name = fixture['name'] as String;
    final schema = fixture['schema'] as String;
    final value = Map<String, dynamic>.from(fixture['value'] as Map);

    group(name, () {
      test('$schema 解析后再序列化，与服务端 JSON 一致', () {
        final trip = roundTrips[schema];
        expect(trip, isNotNull, reason: '$schema 没有往返函数');
        final out = trip!(value);
        expect(
            deepEquals(
                canonicalJson(schema, out), canonicalJson(schema, value)),
            isTrue,
            reason: '往返后不一致\n原始：${jsonEncode(value)}\n往返：${jsonEncode(out)}');
      });

      for (final json in findEvents(fixture['body'])) {
        test('事件 #${json['seq_no']} ${json['type']} 的 payload 能往返，枚举都认得', () {
          final event = TutorEvent.fromJson(json);
          expect(event.type, isNot(TutorEventType.$unknown));
          expect(event.stateAfter, isNot(SessionState.$unknown));
          expect(event.meta.source, isNot(TutorEventSource.$unknown));
          final payload = payloadRoundTrip(event);
          expect(payload, isNotNull);
          expect(deepEquals(payload, json['payload']), isTrue,
              reason:
                  '${jsonEncode(payload)} != ${jsonEncode(json['payload'])}');
        });
      }
    });
  }

  test('未知的枚举值落到 \$unknown，而不是抛异常', () {
    expect(SessionState.fromJson('SOMETHING_NEW'), SessionState.$unknown);
    expect(TutorEventType.fromJson('hologram'), TutorEventType.$unknown);
    expect(RegionCode.fromJson('CN-11'), RegionCode.$unknown);
  });

  test('null 规范化只应用于契约允许的可选字段', () {
    expect(canonicalJson('Attempt', {'submission_no': null}), isEmpty);
    for (final key in ['independent', 'id', 'unknown']) {
      expect(canonicalJson('Attempt', {key: null}), {key: null});
    }
    expect(
        canonicalJson('Attempt', {'submission_no': 2}), {'submission_no': 2});
    expect(
        canonicalJson('DraftCopy', {
          'attempt': {'submission_no': null}
        }),
        {'attempt': <String, dynamic>{}});
    expect(
        canonicalJson('Attempt', {
          'answer': {'unknown': null}
        }),
        {
          'answer': {'unknown': null}
        });
  });

  test('旧回执缺少新增字段仍能解析，且有效来源字段保留', () {
    final fixture = jsonDecode(
        File('test/fixtures/attempt_created.json').readAsStringSync()) as Map;
    final json = Map<String, dynamic>.from(fixture['value'] as Map);
    for (final key in [
      'submission_no',
      'copied_from_attempt_id',
      'copied_from_revision'
    ]) {
      json.remove(key);
    }
    expect(deepEquals(Attempt.fromJson(json).toJson(), json), isTrue);
    json.addAll({
      'submission_no': 2,
      'copied_from_attempt_id': 'source-id',
      'copied_from_revision': 0
    });
    expect(deepEquals(Attempt.fromJson(json).toJson(), json), isTrue);
  });
}
