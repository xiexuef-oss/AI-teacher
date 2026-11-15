import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/solve/draft_store.dart';

void main() {
  late MemoryStore memory;
  late DraftStore store;

  LocalDraft sample() => LocalDraft(
    questionId: 'q1',
    sessionId: 's1',
    attemptId: 'a1',
    baseRevision: 3,
    dirty: true,
    selected: const ['A', 'C'],
    blanks: const {'b1': '5 m/s²'},
    strokes: StrokeDoc(
      version: 1,
      pages: [
        StrokePage(
          width: 1000,
          height: 1400,
          strokes: [
            const Stroke(
              color: '#1A1A1A',
              width: 2.5,
              points: [1, 2, 0, 0.5, 3, 4, 8, 0.6],
            ),
          ],
        ),
      ],
    ),
    savedAt: DateTime.utc(2026, 11, 10, 8),
  );

  setUp(() {
    memory = MemoryStore();
    store = DraftStore(memory, 'u1');
  });

  test('草稿写入后能原样读出，包括笔迹', () async {
    await store.writeDraft(sample());

    final read = (await store.readDraft('q1'))!;

    expect(read.sessionId, 's1');
    expect(read.attemptId, 'a1');
    expect(read.baseRevision, 3);
    expect(read.dirty, isTrue);
    expect(read.selected, ['A', 'C']);
    expect(read.blanks, {'b1': '5 m/s²'});
    expect(read.strokes!.pages.single.strokes.single.points, [
      1,
      2,
      0,
      0.5,
      3,
      4,
      8,
      0.6,
    ]);
    expect(read.savedAt, DateTime.utc(2026, 11, 10, 8));
  });

  test('解答题分小问的文字随草稿一起存、一起读', () async {
    final draft = LocalDraft(
      questionId: 'q1',
      parts: const {'1': 'a≤1', '2': '最小值 -1，最大值 3'},
      savedAt: DateTime.utc(2026, 11, 10, 8),
    );
    expect(draft.hasContent, isTrue);

    await store.writeDraft(draft);

    final read = (await store.readDraft('q1'))!;
    expect(read.parts, {'1': 'a≤1', '2': '最小值 -1，最大值 3'});
    expect(read.selected, isEmpty);
    expect(read.blanks, isEmpty);
  });

  test('实验题数据表里填的格子随草稿一起存、一起读（键是 表.行.列）', () async {
    final draft = LocalDraft(
      questionId: 'q1',
      cells: const {'t1.r1.v': '0.400', 't2.r1.val': '2.00'},
      parts: const {'1': 'T 等于 0.10 秒'},
      savedAt: DateTime.utc(2026, 11, 10, 8),
    );
    expect(draft.hasContent, isTrue);

    await store.writeDraft(draft);

    final read = (await store.readDraft('q1'))!;
    expect(read.cells, {'t1.r1.v': '0.400', 't2.r1.val': '2.00'});
    expect(read.parts, {'1': 'T 等于 0.10 秒'});
    expect(read.selected, isEmpty);
    expect(read.blanks, isEmpty);
  });

  test('只有空白文字不算有内容', () {
    final draft = LocalDraft(
      questionId: 'q1',
      parts: const {'1': '  \n '},
      savedAt: DateTime.utc(2026, 11, 10, 8),
    );
    expect(draft.hasContent, isFalse);
  });

  test('只有空白的格子也不算有内容', () {
    final draft = LocalDraft(
      questionId: 'q1',
      cells: const {'t1.r1.v': '  '},
      savedAt: DateTime.utc(2026, 11, 10, 8),
    );
    expect(draft.hasContent, isFalse);
  });

  test('只有格子、没有别的内容，也算有内容（不会被当成空草稿丢掉）', () {
    final draft = LocalDraft(
      questionId: 'q1',
      cells: const {'t1.r1.v': '0.4'},
      savedAt: DateTime.utc(2026, 11, 10, 8),
    );
    expect(draft.hasContent, isTrue);
  });

  test('解答题加入之后、实验题加入之前存下的草稿（有分小问、没有格子）仍然读得出来', () async {
    await memory.write(
      'u/u1/draft/q1',
      jsonEncode({
        'v': 1,
        'questionId': 'q1',
        'sessionId': null,
        'attemptId': null,
        'baseRevision': 0,
        'dirty': true,
        'answer': {
          'selected': <String>[],
          'blanks': <String, String>{},
          'parts': {'1': '写了一半'},
        },
        'strokes': null,
        'savedAt': '2026-11-10T08:00:00.000Z',
      }),
    );

    final read = (await store.readDraft('q1'))!;

    expect(read.parts, {'1': '写了一半'});
    expect(read.cells, isEmpty);
    expect(memory.data.keys, ['u/u1/draft/q1'], reason: '没有被当成坏草稿另存');
  });

  test('旧版本存下的草稿（没有分小问这一项）仍然读得出来', () async {
    await memory.write(
      'u/u1/draft/q1',
      jsonEncode({
        'v': 1,
        'questionId': 'q1',
        'sessionId': null,
        'attemptId': null,
        'baseRevision': 0,
        'dirty': true,
        'answer': {
          'selected': ['B'],
          'blanks': <String, String>{},
        },
        'strokes': null,
        'savedAt': '2026-11-10T08:00:00.000Z',
      }),
    );

    final read = (await store.readDraft('q1'))!;

    expect(read.selected, ['B']);
    expect(read.parts, isEmpty);
    expect(memory.data.keys, ['u/u1/draft/q1'], reason: '没有被当成坏草稿另存');
  });

  test('键里带用户 ID：不同用户的草稿互不可见', () async {
    await store.writeDraft(sample());

    expect(memory.data.keys.single, 'u/u1/draft/q1');
    expect(await DraftStore(memory, 'u2').readDraft('q1'), isNull);
  });

  test('读不到就是 null；清除后读不到', () async {
    expect(await store.readDraft('q1'), isNull);
    await store.writeDraft(sample());
    await store.clearDraft('q1');
    expect(await store.readDraft('q1'), isNull);
  });

  test('内容损坏时不崩溃，返回 null，并把原文另存一份以便找回', () async {
    memory.data['u/u1/draft/q1'] = '{"questionId": "q1", 这不是 JSON';

    expect(await store.readDraft('q1'), isNull);
    expect(memory.data['u/u1/draft-corrupt/q1'], contains('这不是 JSON'));
  });

  test('版本不认识的草稿也当作读不到，不硬解析', () async {
    memory.data['u/u1/draft/q1'] = jsonEncode({...sample().toJson(), 'v': 99});
    expect(await store.readDraft('q1'), isNull);
  });

  test('进行中的会话指针：写、读、清', () async {
    await store.writeActive(
      'q1',
      const ActiveRef(sessionId: 's1', attemptId: 'a1'),
    );
    final read = (await store.readActive('q1'))!;
    expect((read.sessionId, read.attemptId), ('s1', 'a1'));

    await store.clearActive('q1');
    expect(await store.readActive('q1'), isNull);
  });

  Map<String, dynamic> cachedQuestion({bool withDataTables = true}) => {
    'id': 'q1',
    'subject': 'math',
    'type': 'single_choice',
    'answer_mode': 'single_choice',
    'difficulty': 2,
    'title': '测试题',
    'source': {
      'source_type': 'self_authored',
      'source_category': 'foundation',
      'source_name': null,
      'source_year': null,
      'source_license': 'x',
      'source_url': null,
      'is_engineering_sample': true,
      'label': '自编',
    },
    'applicability': {
      'scope': 'general',
      'label': '全国通用基础题',
      'recommended_regions': <String>[],
      'origin_region_code': null,
      'exam_year_from': null,
      'exam_year_to': null,
      'disclaimer': 'x',
    },
    'knowledge': <Object>[],
    'variant_of': null,
    'version': 1,
    'grade': null,
    'content': {
      'stem': '题干',
      'options': <Object>[],
      'blanks': <Object>[],
      'subquestions': <Object>[],
      'attachments': <Object>[],
      if (withDataTables) 'data_tables': <Object>[],
      if (withDataTables) 'safety': null,
    },
    'assists': {
      'hint_levels': 0,
      'has_standard_solution': false,
      'has_fast_solution': false,
      'visual_available': false,
    },
    'judging_note': null,
  };

  test('题目缓存：断网时可以继续显示', () async {
    final question = Question.fromJson(cachedQuestion());

    await store.writeQuestion(question);

    expect((await store.readQuestion('q1'))!.title, '测试题');
    expect(await DraftStore(memory, 'u2').readQuestion('q1'), isNull);
  });

  test('实验题的数据表和安全提示也在题目缓存里，断网时照样显示', () async {
    final json = cachedQuestion();
    final content = json['content'] as Map<String, dynamic>;
    content['data_tables'] = [
      {
        'key': 't1',
        'title': '表 1',
        'columns': [
          {'key': 'x', 'label': '距离', 'unit': 'cm'},
        ],
        'rows': [
          {
            'key': 'r1',
            'label': 'AB',
            'cells': [
              {'col': 'x', 'text': null},
            ],
          },
        ],
      },
    ];
    content['safety'] = {
      'level': 'low',
      'notes': ['纸面练习'],
    };
    await store.writeQuestion(Question.fromJson(json));

    final read = (await store.readQuestion('q1'))!;

    expect(
      read.content.dataTables.single.rows.single.cells.single.text,
      isNull,
    );
    expect(read.content.dataTables.single.columns.single.unit, 'cm');
    expect(read.content.safety!.notes, ['纸面练习']);
  });

  test('升级前缓存的题目（没有数据表这一项）读不懂时按没缓存处理，不崩溃', () async {
    memory.data['u/u1/question/q1'] = jsonEncode(
      cachedQuestion(withDataTables: false),
    );

    expect(await store.readQuestion('q1'), isNull);
  });
}
