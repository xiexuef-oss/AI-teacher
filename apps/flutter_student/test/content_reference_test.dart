import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/features/solve/tutor_panel.dart';
import 'package:tutor_student/features/solve/content_reference.dart';
import 'package:tutor_student/core/math_text.dart';

Map<String, dynamic> reference(String text, int start, int end) => {
  'block_id': 'stem',
  'block_sha256': sha256.convert(utf8.encode(text)).toString(),
  'start': start,
  'end': end,
  'block_text': text,
  'label': '题面条件',
};

TutorEvent event(List<Map<String, dynamic>>? refs) => TutorEvent.fromJson({
  'id': 'event-1',
  'session_id': 'session-1',
  'seq_no': 1,
  'type': 'hint',
  'created_at': '2026-11-16T00:00:00Z',
  'state_after': 'HINTED',
  'payload': {
    'level': 1,
    'total_levels': 1,
    'style': 'layered',
    'text': '请检查已知条件。',
    'concept': null,
  },
  'meta': {
    'schema_version': '1.0',
    'source': 'reviewed_content',
    'degraded': false,
    'provider': null,
    'model_id': null,
    'prompt_version': null,
    'question_id': 'question-1',
    'question_version': 1,
    'trace_id': null,
    'request_id': 'request-1',
  },
  'references': ?refs,
});

void main() {
  ContentReferenceResult check(
    Object? refs, {
    String session = 'session-1',
    String question = 'question-1',
    int version = 1,
  }) => validateContentReferences(
    refs,
    eventSessionId: 'session-1',
    eventQuestionId: 'question-1',
    eventVersion: 1,
    sessionId: session,
    questionId: question,
    questionVersion: version,
  );
  test('raw UTF8 hash and codepoint slicing preserve emoji, combining characters and newline', () {
    const text = '已知😀e\u0301\n条件';
    final result = check([reference(text, 2, 6)]);
    expect(result.unavailable, false);
    expect(result.references.single.selection, '😀e\u0301\n');
    expect(
      check([
        {...reference(text, 2, 6), 'block_text': '已知😀é\n条件'},
      ]).unavailable,
      true,
    );
  });
  test(
    'raw fractional, bool, string and out of bounds offsets are unavailable',
    () {
      for (final start in [1.5, true, '1', null, -1, 4000]) {
        expect(
          check([
            {...reference('abcdef', 1, 3), 'start': start},
          ]).unavailable,
          true,
        );
      }
      for (final end in [1, 9, 0, false, 2.5]) {
        expect(
          check([
            {...reference('abcdef', 1, 3), 'end': end},
          ]).unavailable,
          true,
        );
      }
    },
  );
  test(
    'identity is checked against the active session and fixed question version',
    () {
      final refs = [reference('条件', 0, 1)];
      expect(check(refs, session: 'other').unavailable, true);
      expect(check(refs, question: 'other').unavailable, true);
      expect(check(refs, version: 2).unavailable, true);
      expect(check(refs).unavailable, false);
    },
  );
  test(
    'block grammar uses bounded ordinals and rejects keys, URLs and pointers',
    () {
      for (final id in [
        'stem',
        'subquestion:2:stem',
        'subquestion:2:option:3',
        'proof:given:1',
        'solution:standard:step:30',
        'rubric:point:1',
        'reference_cell:1:2:3',
        'reference_step:2:reason',
        'visual:static_fallback',
      ]) {
        expect(
          check([
            {...reference('条件', 0, 1), 'block_id': id},
          ]).unavailable,
          false,
        );
      }
      for (final id in [
        'https://a',
        '/content/stem',
        'option:A',
        'hint:01',
        'hint:0',
        'hint:1000',
        'stem\n',
        'reference_cell:table:row:col',
      ]) {
        expect(
          check([
            {...reference('条件', 0, 1), 'block_id': id},
          ]).unavailable,
          true,
        );
      }
    },
  );
  test(
    'caps, exact object shape, raw hash and duplicate references are checked',
    () {
      final ref = reference('条件', 0, 1);
      expect(check([ref, ref]).references.length, 1);
      expect(check(List.filled(9, ref)).unavailable, true);
      expect(
        check([
          {...ref, 'url': 'https://a'},
        ]).unavailable,
        true,
      );
      expect(
        check([
          {...ref, 'block_sha256': '0' * 64},
        ]).unavailable,
        true,
      );
      expect(check([reference('字' * 4001, 0, 1)]).unavailable, true);
      expect(
        check([
          {...ref, 'label': '字' * 121},
        ]).unavailable,
        true,
      );
      expect(check(null).unavailable, false);
      expect(check([]).unavailable, false);
    },
  );
  testWidgets(
    'a saved event offers local reference context without a network action',
    (tester) async {
      final saved = TutorEvent.fromJson(
        jsonDecode(jsonEncode(event([reference('已知😀条件，求解。', 2, 5)]).toJson()))
            as Map<String, dynamic>,
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TutorTimeline(
              events: [saved],
              onSuggestion: (_) => fail('reference click must be local'),
              sessionId: 'session-1',
              questionId: 'question-1',
              questionVersion: 1,
            ),
          ),
        ),
      );
      expect(find.textContaining('查看依据'), findsOneWidget);
      await tester.tap(find.textContaining('查看依据'));
      await tester.pumpAndSettle();
      final text = tester.widget<Text>(
        find.byKey(const ValueKey('reference.highlightedContext')),
      );
      expect(text.textSpan!.toPlainText(), '已知😀条件，求解。');
      final highlighted = (text.textSpan! as TextSpan).children!
          .whereType<TextSpan>()
          .where((s) => s.style?.backgroundColor != null)
          .single;
      expect(highlighted.text, '😀条件');
    },
  );
  testWidgets(
    'a formula selection retains the complete MathText and literal exact excerpt',
    (tester) async {
      const source = r'已知 $x^2+1=2$，求解。';
      final r = check([reference(source, 5, 8)]).references.single;
      await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: ContentReferenceContext(r))),
      );
      expect(tester.widget<MathText>(find.byType(MathText)).text, source);
      expect(find.textContaining('未高亮公式子结构'), findsOneWidget);
      expect(
        tester
            .widget<Text>(
              find.byKey(const ValueKey('reference.exactSelection')),
            )
            .data,
        r.selection,
      );
      expect(
        find.byKey(const ValueKey('reference.highlightedContext')),
        findsNothing,
      );
    },
  );
  testWidgets('ordinary emphasis keeps an adjacent complete formula intact', (
    tester,
  ) async {
    final r = check([reference(r'已知条件，$x>0$。', 2, 4)]).references.single;
    await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: ContentReferenceContext(r))),
    );
    expect(tester.widget<MathText>(find.byType(MathText)).text, r'$x>0$');
    expect(
      find.byKey(const ValueKey('reference.highlightedContext')),
      findsOneWidget,
    );
  });
  testWidgets('wrong identity and damaged hash never offer a false highlight', (
    tester,
  ) async {
    for (final version in [1, 2]) {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TutorTimeline(
              events: [
                event([
                  {
                    ...reference('条件', 0, 1),
                    if (version == 1) 'block_sha256': '0' * 64,
                  },
                ]),
              ],
              onSuggestion: (_) {},
              sessionId: 'session-1',
              questionId: 'question-1',
              questionVersion: version,
            ),
          ),
        ),
      );
      expect(find.text('引用不可用'), findsOneWidget);
      expect(find.textContaining('查看依据'), findsNothing);
      expect(find.text('请检查已知条件。'), findsOneWidget);
    }
  });
  testWidgets(
    'old events without references retain their original presentation',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TutorTimeline(events: [event(null)], onSuggestion: (_) {}),
          ),
        ),
      );
      expect(find.text('请检查已知条件。'), findsOneWidget);
      expect(find.text('引用不可用'), findsNothing);
      expect(find.textContaining('查看依据'), findsNothing);
    },
  );
  testWidgets(
    'malformed persisted DTO references retain the event with unavailable evidence',
    (tester) async {
      final valid = reference('条件', 0, 1);
      for (final raw in [
        null,
        {},
        [null],
        [
          {...valid, 'start': 0.5},
        ],
        [
          {...valid, 'end': true},
        ],
        [
          {...valid, 'extra': 'untrusted'},
        ],
        List.filled(9, valid),
      ]) {
        final json = event([valid]).toJson()..['references'] = raw;
        final restored = TutorEvent.fromJson(
          jsonDecode(jsonEncode(json)) as Map<String, dynamic>,
        );
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: TutorTimeline(
                events: [restored],
                onSuggestion: (_) {},
                sessionId: 'session-1',
                questionId: 'question-1',
                questionVersion: 1,
              ),
            ),
          ),
        );
        expect(find.text('引用不可用'), findsOneWidget);
        expect(find.text('请检查已知条件。'), findsOneWidget);
        expect(find.textContaining('查看依据'), findsNothing);
      }
    },
  );
}
