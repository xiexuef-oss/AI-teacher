import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/solve/draft_store.dart';

LocalDraft sample({String answer = 'A', String? attempt = 'a1'}) => LocalDraft(
  questionId: 'q1',
  sessionId: attempt == null ? null : 's1',
  attemptId: attempt,
  baseRevision: 0,
  dirty: true,
  selected: [answer],
  blanks: const {'b1': '4'},
  parts: const {'p1': '我的解答'},
  cells: const {'c1': '5'},
  steps: const [ProofStepDraft(text: '我的证明', reason: '依据')],
  strokes: const StrokeDoc(
    version: 1,
    pages: [
      StrokePage(
        width: 100,
        height: 100,
        strokes: [
          Stroke(color: '#1A1A1A', width: 2, points: [1, 2, 0, 0.5]),
        ],
      ),
    ],
  ),
  savedAt: DateTime.utc(2026, 11, 17),
);

void main() {
  test(
    'exports all owned draft variants without credentials or writes',
    () async {
      final memory = MemoryStore({
        'auth.token': 'SECRET-TOKEN',
        'auth.other.token': 'OTHER-TOKEN',
      });
      final store = DraftStore(memory, 'student-1');
      await store.writeDraft(sample());
      final attempt = store.forAttempt('a1');
      await attempt.writeDraft(sample(answer: 'B'));
      await store
          .forLocal('workspace')
          .writeDraft(sample(answer: 'C', attempt: null));
      await attempt.archivePair(
        'q1',
        sample(answer: 'D'),
        sample(answer: 'E'),
        pending: true,
      );
      await DraftStore(
        memory,
        'student-10',
      ).writeDraft(sample(answer: 'OTHER-OWNER'));
      final key = 'u/student-1/draft-bundle/q1';
      final bundle = jsonDecode(memory.data[key]!) as Map<String, dynamic>;
      bundle['idempotencyKey'] = 'SECRET-REPLAY-KEY';
      (bundle['drafts']['attempt/a1'] as Map)['token'] = 'SECRET-NESTED-TOKEN';
      memory.data[key] = jsonEncode(bundle);
      final before = Map<String, String>.of(memory.data);
      memory.failWrites = true;

      final drafts = await store.readExportDrafts();
      expect(drafts.map((d) => d.selected.single).toSet(), {
        'A',
        'B',
        'C',
        'D',
        'E',
      });
      expect(drafts.every((d) => d.steps.single.text == '我的证明'), isTrue);
      expect(
        drafts.every((d) => d.cells['c1'] == '5' && d.strokes != null),
        isTrue,
      );
      final json = jsonEncode(drafts.map((d) => d.toJson()).toList());
      expect(json, isNot(contains('SECRET')));
      expect(json, isNot(contains('OTHER-OWNER')));
      expect(memory.data, before);
    },
  );

  for (final family in [
    'draft',
    'draft-bundle',
    'draft-recovery',
    'draft-corrupt',
  ]) {
    test(
      'unsupported $family fails without changing any source bytes',
      () async {
        final memory = MemoryStore({
          'u/student/draft/q1': jsonEncode(sample().toJson()),
        });
        memory.data['u/student/$family/q1'] = jsonEncode({'v': 99});
        final before = Map<String, String>.of(memory.data);
        await expectLater(
          DraftStore(memory, 'student').readExportDrafts(),
          throwsFormatException,
        );
        expect(memory.data, before);
      },
    );
  }

  test('rejects a foreign question stored under an owned draft key', () async {
    final memory = MemoryStore({
      'u/student/draft/q2': jsonEncode(sample().toJson()),
    });
    final before = Map<String, String>.of(memory.data);
    await expectLater(
      DraftStore(memory, 'student').readExportDrafts(),
      throwsFormatException,
    );
    expect(memory.data, before);
  });
}
