import 'dart:convert';
import 'dart:io';

import 'package:test/test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

Map<String, dynamic> eventJson() {
  return {
    'id': '7d0f3a52-6f0c-4a55-9d3e-1b2a3c4d5e6f',
    'session_id': '0b9c7c0e-1f66-4f0a-8a55-9d3e1b2a3c4d',
    'seq_no': 1,
    'type': 'hint',
    'created_at': '2026-11-10T08:00:00Z',
    'state_after': 'HINTED',
    'payload': {
      'level': 1,
      'total_levels': 1,
      'style': 'layered',
      'text': '提示文字',
      'concept': null
    },
    'meta': {
      'schema_version': '1.0',
      'source': 'reviewed_content',
      'degraded': false,
      'provider': null,
      'model_id': null,
      'prompt_version': null,
      'question_id': '3f2b1c0a-9e8d-4c7b-a6f5-0e1d2c3b4a59',
      'question_version': 1,
      'trace_id': null,
      'request_id': 'req-test',
    },
  };
}

Map<String, dynamic> reference() => {
      'block_id': 'stem',
      'block_sha256': 'a' * 64,
      'start': 0,
      'end': 2,
      'block_text': '条件原文',
      'label': '题干',
    };

void main() {
  test('旧无引用事件兼容，合法坐标保持原值', () {
    final raw = eventJson();
    expect(TutorEvent.fromJson(raw).references, isNull);
    raw['references'] = [reference()];
    expect(TutorEvent.fromJson(raw).references!.single.end, 2);
  });

  test('范围小数不截断为整数', () {
    final raw = reference()..['start'] = 0.5;
    expect(() => ResolvedContentSpan.fromJson(raw), throwsA(isA<TypeError>()));
    expect(
        () => ContentSpanRef.fromJson({
              'block_id': 'stem',
              'block_sha256': 'a' * 64,
              'start': 0.5,
              'end': 2,
            }),
        throwsA(isA<TypeError>()));
  });

  test('带引用的损坏版本号不能截断后绑定到当前版本', () {
    final raw = eventJson()..['references'] = [reference()];
    (raw['meta'] as Map)['question_version'] = 1.5;
    final event = TutorEvent.fromJson(raw);
    expect(event.references!.single.start, -1);
    expect(event.payload, raw['payload']);
  });

  final invalid = <Object?>[
    null,
    {},
    'not refs',
    [true],
    [reference()..['start'] = 0.5],
    [reference()..['start'] = true],
    [reference()..['url'] = 'https://example.test'],
    [reference()..remove('block_text')],
    List.generate(9, (_) => reference()),
  ];
  for (var i = 0; i < invalid.length; i++) {
    test('损坏引用 $i 保留事件正文且显式标记不可用', () {
      final raw = eventJson()..['references'] = invalid[i];
      final event = TutorEvent.fromJson(raw);
      expect(event.payload, raw['payload']);
      expect(event.references, isNotEmpty);
      expect(event.references!.single.start, -1);
      final replay = TutorEvent.fromJson(event.toJson());
      expect(replay.references!.single.start, -1);
    });
  }
}
