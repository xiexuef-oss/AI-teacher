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

  test('只有空白文字不算有内容', () {
    final draft = LocalDraft(
      questionId: 'q1',
      parts: const {'1': '  \n '},
      savedAt: DateTime.utc(2026, 11, 10, 8),
    );
    expect(draft.hasContent, isFalse);
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

  test('题目缓存：断网时可以继续显示', () async {
    final question = Question.fromJson({
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
      },
      'assists': {
        'hint_levels': 0,
        'has_standard_solution': false,
        'has_fast_solution': false,
        'visual_available': false,
      },
      'judging_note': null,
    });

    await store.writeQuestion(question);

    expect((await store.readQuestion('q1'))!.title, '测试题');
    expect(await DraftStore(memory, 'u2').readQuestion('q1'), isNull);
  });
}
