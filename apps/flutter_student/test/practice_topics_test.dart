import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/features/practice/practice_page.dart';
import 'package:tutor_student/features/home/home_page.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

void main() {
  testWidgets('topic picker fits a phone with larger text', (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final h = AppHarness()..signInAs(role: 'student', userId: 'student');
    await tester.pumpWidget(h.page(const PracticePage(), textScale: 1.5));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('filter.knowledge')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  for (final cold in [false, true]) {
    testWidgets('first learning choice follows server history flag ($cold)', (
      tester,
    ) async {
      final h = AppHarness()..signInAs(role: 'student', userId: 'student');
      h.backend.on(
        'GET',
        '/tasks/today',
        (_) => okResponse(
          h.backend.fixtures.value('tasks_today')..['cold_start'] = cold,
        ),
      );
      await tester.pumpWidget(h.page(const HomePage()));
      await tester.pumpAndSettle();
      expect(find.text('按知识点选题'), cold ? findsOneWidget : findsNothing);
      expect(find.text('先练一道基础题'), cold ? findsOneWidget : findsNothing);
    });
  }

  testWidgets(
    'manual topic selection uses generated filter and clears on subject change',
    (tester) async {
      final h = AppHarness()..signInAs(role: 'student', userId: 'student');
      h.backend.onFixture('GET', '/questions/topics', 'question_topics');
      await tester.pumpWidget(h.page(const PracticePage()));
      await tester.pumpAndSettle();
      final topics =
          h.backend.fixtures.value('question_topics')['items'] as List;
      final topic = topics.first as Map;
      await tester.tap(find.byKey(const ValueKey('filter.knowledge')));
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining(topic['title'] as String).last);
      await tester.pumpAndSettle();
      final requests = h.backend.requestsTo('GET', r'/questions$');
      expect(requests.last.uri.queryParameters['knowledge_id'], topic['id']);
      await tester.tap(find.byKey(const ValueKey('filter.subject.physics')));
      await tester.pumpAndSettle();
      expect(
        h.backend
            .requestsTo('GET', r'/questions$')
            .last
            .uri
            .queryParameters
            .containsKey('knowledge_id'),
        isFalse,
      );
      expect(
        h.backend
            .requestsTo('GET', '/questions/topics')
            .last
            .uri
            .queryParameters['subject'],
        'physics',
      );
    },
  );

  testWidgets('topic failure is visible and retryable', (tester) async {
    final h = AppHarness()..signInAs(role: 'student', userId: 'student');
    h.backend.onFixture('GET', '/questions/topics', 'question_topics');
    h.backend.failNextOn(r'/questions/topics$', 503, 'service_unavailable');
    await tester.pumpWidget(h.page(const PracticePage()));
    await tester.pumpAndSettle();
    expect(find.text('重试'), findsOneWidget);
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('filter.knowledge')), findsOneWidget);
  });
}
