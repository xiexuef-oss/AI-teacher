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

  test(
    'attempt scopes isolate drafts and reject mismatched late writes',
    () async {
      final first = store.forAttempt('a1');
      final second = store.forAttempt('a2');
      await first.writeDraft(sample());
      expect(await second.readDraft('q1'), isNull);
      await expectLater(second.writeDraft(sample()), throwsStateError);
      expect((await first.readDraft('q1'))!.selected, ['A', 'C']);
    },
  );

  test('pending single-record completion retries failed disk writes and keeps newer editor', () async {
    final scoped = store.forAttempt('a1');
    await scoped.claimScope('q1');
    await scoped.archivePair('q1', sample(), sample(), pending: true);
    final pending = PendingDraftCopy(
      snapshot: sample(),
      sourceAttemptId: 'a1',
      observedRevision: 3,
      idempotencyKey: 'fixed',
      recoveryGeneration: 1,
    );
    await scoped.savePendingCopy('q1', pending);
    final copied = LocalDraft.fromJson({
      ...sample().toJson(),
      'attemptId': 'a2',
    });
    memory.failWrites = true;
    await expectLater(
      scoped.completePendingCopy('q1', idempotencyKey: 'fixed', copy: copied),
      throwsStateError,
    );
    memory.failWrites = false;
    expect((await scoped.readPendingCopy('q1'))!.idempotencyKey, 'fixed');
    final newer = store.forAttempt('a1');
    await newer.claimScope('q1');
    await expectLater(scoped.writeDraft(sample()), throwsStateError);
    expect(
      await scoped.completePendingCopy(
        'q1',
        idempotencyKey: 'fixed',
        copy: copied,
      ),
      isFalse,
    );
    expect(await scoped.readPendingCopy('q1'), isNotNull);
    expect(
      await newer.completePendingCopy(
        'q1',
        idempotencyKey: 'fixed',
        copy: copied,
      ),
      isTrue,
    );
    expect(await newer.readPendingCopy('q1'), isNotNull);
    final editor = store.forAttempt('a2');
    await editor.claimScope('q1');
    final editedJson = copied.toJson();
    (editedJson['answer'] as Map)['selected'] = ['B'];
    await editor.writeDraft(LocalDraft.fromJson(editedJson));
    await newer.completePendingCopy(
      'q1',
      idempotencyKey: 'fixed',
      copy: copied,
    );
    expect((await editor.readDraft('q1'))!.selected, ['B']);
    await expectLater(
      newer.resolveRecovery('q1', expectedGeneration: 1),
      throwsStateError,
    );
    await expectLater(
      newer.acknowledgePendingCopy('q1', idempotencyKey: 'fixed'),
      throwsStateError,
    );
    await newer.writeActive(
      'q1',
      const ActiveRef(sessionId: 's1', attemptId: 'a2'),
    );
    await newer.acknowledgePendingCopy('q1', idempotencyKey: 'fixed');
    expect(await newer.readPendingCopy('q1'), isNull);
    expect((await store.forAttempt('a2').readDraft('q1'))!.attemptId, 'a2');
    expect((await newer.readCopyReferences('q1')).single.attemptId, 'a2');
  });
  test(
    'local id persists, scopes and unknown raw bundle remain isolated',
    () async {
      final id = await store.readOrCreateLocalId('q1');
      expect(await DraftStore(memory, 'u1').readOrCreateLocalId('q1'), id);
      memory.data['u/u1/draft-bundle/q1'] = '{"v":999}';
      await expectLater(
        store.forAttempt('a1').writeDraft(sample()),
        throwsFormatException,
      );
      expect(memory.data['u/u1/draft-bundle/q1'], '{"v":999}');
    },
  );

  test('clear scoped migrated draft cannot resurrect legacy source', () async {
    await store.writeDraft(sample());
    final scoped = store.forAttempt('a1');
    await scoped.claimScope('q1');
    expect(await scoped.readDraft('q1'), isNotNull);
    await scoped.clearDraft('q1');
    expect(await scoped.readDraft('q1'), isNull);
    expect(memory.data['u/u1/draft/q1'], isNotNull);
  });

  test('promotion atomically consumes default local and preserves legacy active tombstone', () async {
    final localId = await store.readOrCreateLocalId('q1');
    final local = store.forLocal(localId);
    final original = LocalDraft.fromJson({
      ...sample().toJson(),
      'sessionId': null,
      'attemptId': null,
    });
    await store.writeDraft(original);
    await local.writeDraft(original);
    memory.failWrites = true;
    await expectLater(local.promoteToAttempt(sample()), throwsStateError);
    memory.failWrites = false;
    expect((await local.readDraft('q1'))!.selected, original.selected);
    expect(await store.readActive('q1'), isNull);
    await local.promoteToAttempt(sample());
    expect((await store.readActive('q1'))!.attemptId, 'a1');
    expect(await local.readDraft('q1'), isNull);
    await expectLater(local.writeDraft(original), throwsStateError);
    await store.forAttempt('a1').clearDraft('q1');
    await store.clearActive('q1');
    memory.data['u/u1/active/q1'] = jsonEncode(
      const ActiveRef(sessionId: 'old', attemptId: 'old').toJson(),
    );
    expect(await store.readActive('q1'), isNull);
    final nextId = await store.readOrCreateLocalId('q1');
    expect(nextId, isNot(localId));
    expect(await store.forLocal(nextId).readDraft('q1'), isNull);
  });

  test('promotion preserves newer target and archives complete source without consuming other local', () async {
    final defaultId = await store.readOrCreateLocalId('q1');
    final independent = store.forLocal('independent');
    final original = LocalDraft.fromJson({
      ...sample().toJson(),
      'sessionId': null,
      'attemptId': null,
    });
    await independent.writeDraft(original);
    final newerJson = sample().toJson();
    (newerJson['answer'] as Map)['selected'] = ['B'];
    await store.forAttempt('a1').writeDraft(LocalDraft.fromJson(newerJson));
    await independent.promoteToAttempt(sample());
    expect((await store.forAttempt('a1').readDraft('q1'))!.selected, ['B']);
    expect(await store.readOrCreateLocalId('q1'), defaultId);
    final bundle = jsonDecode(memory.data['u/u1/draft-bundle/q1']!) as Map;
    expect(
      bundle['promotions']['local/independent']['source'],
      original.toJson(),
    );
    final revived = store.forLocal('independent');
    await revived.claimScope('q1');
    await expectLater(revived.writeDraft(original), throwsStateError);
  });
  test('promotion refuses stale snapshot and preserves independently edited local bytes', () async {
    final id = await store.readOrCreateLocalId('q1');
    final local = store.forLocal(id);
    final original = LocalDraft.fromJson({
      ...sample().toJson(),
      'sessionId': null,
      'attemptId': null,
    });
    final changed = original.toJson();
    (changed['answer'] as Map)['steps'] = [
      {'text': '新的证明', 'reason': '独立编辑'},
    ];
    await local.writeDraft(LocalDraft.fromJson(changed));
    final before = memory.data['u/u1/draft-bundle/q1'];
    await expectLater(local.promoteToAttempt(sample()), throwsStateError);
    expect(memory.data['u/u1/draft-bundle/q1'], before);
    expect(await store.readActive('q1'), isNull);
  });

  setUp(() {
    memory = MemoryStore();
    store = DraftStore(memory, 'u1');
  });

  test('冲突双方及待解决状态重启可读，账号隔离', () async {
    final complete = sample().toJson();
    final answer = complete['answer'] as Map<String, dynamic>;
    answer['parts'] = {'p1': '实验说明'};
    answer['cells'] = {'table.row.col': '1.25'};
    answer['steps'] = [
      {'text': '证明文字', 'reason': '依据'},
      {'text': '', 'reason': ''},
    ];
    final original = LocalDraft.fromJson(complete);
    await store.archivePair('q1', original, original, pending: true);
    final reopened = DraftStore(memory, 'u1');
    final recovery = await reopened.readRecovery('q1');
    expect(recovery!.pending, isTrue);
    expect(recovery.copies.map((d) => d.toJson()), [
      original.toJson(),
      original.toJson(),
    ]);
    expect(await DraftStore(memory, 'other').readRecovery('q1'), isNull);
    await reopened.resolveRecovery(
      'q1',
      expectedGeneration: recovery.generation,
    );
    expect((await reopened.readRecovery('q1'))!.pending, isFalse);
    expect((await reopened.readRecovery('q1'))!.copies, hasLength(2));
  });

  test('异常恢复记录原文保留且不能被新留档覆盖', () async {
    for (final raw in [
      'broken-json',
      '{"v":99}',
      '{"v":1,"pending":true,"copies":[{"v":99}]}',
    ]) {
      memory.data['u/u1/draft-recovery/q1'] = raw;
      await expectLater(store.readRecovery('q1'), throwsA(anything));
      await expectLater(
        store.archivePair('q1', sample(), sample(), pending: true),
        throwsA(anything),
      );
      expect(memory.data['u/u1/draft-recovery/q1'], raw);
    }
  });

  test('同题两实例的旧选择不能清除较新的待解决冲突', () async {
    final other = DraftStore(memory, 'u1');
    final old = await store.archivePair(
      'q1',
      sample(),
      sample(),
      pending: true,
    );
    final newer = await other.archivePair(
      'q1',
      sample(),
      sample(),
      pending: true,
    );
    await expectLater(
      store.resolveRecovery('q1', expectedGeneration: old.generation),
      throwsStateError,
    );
    await expectLater(
      store.archivePair('q1', sample(), sample(), pending: false),
      throwsStateError,
    );
    final retained = await other.readRecovery('q1');
    expect(retained!.pending, isTrue);
    expect(retained.generation, newer.generation);
    expect(retained.copies, hasLength(4));
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

  test('证明题一步一步写的步骤随草稿一起存、一起读：顺序不变，空白卡片也留着', () async {
    final draft = LocalDraft(
      questionId: 'q1',
      steps: const [
        ProofStepDraft(text: '任取 x1<x2', reason: '单调性的定义'),
        ProofStepDraft(),
        ProofStepDraft(text: '所以 f(x1)<f(x2)'),
      ],
      savedAt: DateTime.utc(2026, 11, 10, 8),
    );
    expect(draft.hasContent, isTrue);

    await store.writeDraft(draft);

    final read = (await store.readDraft('q1'))!;
    expect(read.steps.map((s) => (s.text, s.reason)), [
      ('任取 x1<x2', '单调性的定义'),
      ('', ''),
      ('所以 f(x1)<f(x2)', ''),
    ]);
    expect(read.selected, isEmpty);
    expect(read.parts, isEmpty);
    expect(read.cells, isEmpty);
  });

  test('只有空白卡片不算有内容；只有依据、没有别的内容也算（不会被当成空草稿丢掉）', () {
    LocalDraft draft(List<ProofStepDraft> steps) => LocalDraft(
      questionId: 'q1',
      steps: steps,
      savedAt: DateTime.utc(2026, 11, 10, 8),
    );

    expect(
      draft(const [ProofStepDraft(), ProofStepDraft(text: '  \n')]).hasContent,
      isFalse,
    );
    expect(draft(const [ProofStepDraft(reason: '已知')]).hasContent, isTrue);
    expect(draft(const [ProofStepDraft(text: '甲')]).hasContent, isTrue);
  });

  test('一张卡片是不是空白：文字和依据都没有才算', () {
    expect(const ProofStepDraft().isBlank, isTrue);
    expect(const ProofStepDraft(text: ' ', reason: '\t').isBlank, isTrue);
    expect(const ProofStepDraft(text: '甲').isBlank, isFalse);
    expect(const ProofStepDraft(reason: '乙').isBlank, isFalse);
    expect(const ProofStepDraft(text: '甲').copyWith(reason: '乙').text, '甲');
  });

  test('证明题加入之前存下的草稿（有格子、没有步骤）仍然读得出来', () async {
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
          'parts': <String, String>{},
          'cells': {'t1.r1.v': '0.4'},
        },
        'strokes': null,
        'savedAt': '2026-11-10T08:00:00.000Z',
      }),
    );

    final read = (await store.readDraft('q1'))!;

    expect(read.cells, {'t1.r1.v': '0.4'});
    expect(read.steps, isEmpty);
    expect(memory.data.keys, ['u/u1/draft/q1'], reason: '没有被当成坏草稿另存');
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

  test(
    'scoped cache never reads unverified base or another attempt snapshot',
    () async {
      final question = Question.fromJson(cachedQuestion());
      await store.writeQuestion(question);
      expect(await store.forAttempt('a1').readQuestion(question.id), isNull);
      await store.forAttempt('a1').writeQuestion(question);
      expect(
        (await store.forAttempt('a1').readQuestion(question.id))!.version,
        question.version,
      );
      expect(await store.forAttempt('a2').readQuestion(question.id), isNull);
    },
  );
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

  test('证明题的已知和求证也在题目缓存里，断网时照样显示', () async {
    final json = cachedQuestion();
    (json['content'] as Map<String, dynamic>)['proof'] = {
      'givens': ['\$a>0\$', '\$b>0\$'],
      'claim': '\$ab>0\$',
    };
    await store.writeQuestion(Question.fromJson(json));

    final read = (await store.readQuestion('q1'))!;

    expect(read.content.proof!.givens, ['\$a>0\$', '\$b>0\$']);
    expect(read.content.proof!.claim, '\$ab>0\$');
  });

  test('证明题加入之前缓存的题目（有数据表、没有 proof 这一项）仍然读得出来，已知和求证是空', () async {
    memory.data['u/u1/question/q1'] = jsonEncode(cachedQuestion());

    final read = (await store.readQuestion('q1'))!;

    expect(read.title, '测试题');
    expect(read.content.proof, isNull);
  });

  test('升级前缓存的题目（没有数据表这一项）读不懂时按没缓存处理，不崩溃', () async {
    memory.data['u/u1/question/q1'] = jsonEncode(
      cachedQuestion(withDataTables: false),
    );

    expect(await store.readQuestion('q1'), isNull);
  });
}
