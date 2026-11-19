import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_student/features/solve/cloud_drafts_page.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

void main() {
  testWidgets(
    'listing is metadata only and explicit selection carries exact IDs',
    (tester) async {
      final h = AppHarness();
      h.signInAs(role: 'student');
      h.backend.on(
        'GET',
        '/questions/question-id/drafts',
        (r) => okResponse({
          'items': [
            for (final id in ['copy-A', 'copy-B'])
              {
                'session_id': 'session-id',
                'attempt_id': id,
                'question_version': 2,
                'attempt_no': id == 'copy-A' ? 1 : 2,
                'draft_revision': 3,
                'copied_from_attempt_id': null,
                'copied_from_revision': null,
                'origin': 'practice',
                'review_item_id': null,
                'session_state': id == 'copy-A'
                    ? 'DONE'
                    : 'INDEPENDENT_ATTEMPT',
                'updated_at': '2026-11-10T08:00:00Z',
              },
          ],
          'next_cursor': null,
        }),
      );
      final router = GoRouter(
        initialLocation: '/drafts',
        routes: [
          GoRoute(
            path: '/drafts',
            builder: (_, _) => const CloudDraftsPage(questionId: 'question-id'),
          ),
          GoRoute(
            path: '/questions/:id/solve',
            builder: (_, s) => Scaffold(body: Text(s.uri.toString())),
          ),
        ],
      );
      addTearDown(router.dispose);
      await tester.pumpWidget(
        ProviderScope(
          overrides: h.overrides,
          child: MaterialApp.router(routerConfig: router),
        ),
      );
      await tester.pumpAndSettle();
      expect(h.store.data.keys.where((k) => k.contains('/draft/')), isEmpty);
      expect(
        tester.widget<ListTile>(find.byType(ListTile).first).enabled,
        isFalse,
      );
      await tester.tap(find.text('草稿 2 · 题目版本 2'));
      await tester.pumpAndSettle();
      expect(find.textContaining('attempt=copy-B'), findsOneWidget);
      expect(h.backend.requests.where((r) => r.method != 'GET'), isEmpty);
    },
  );
}
