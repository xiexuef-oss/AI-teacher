import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_student/features/practice/practice_page.dart';

import 'support/app_harness.dart';

void main() {
  testWidgets(
    'question title and cloud drafts expose independent button semantics',
    (tester) async {
      final semantics = tester.ensureSemantics();
      final h = AppHarness();
      h.signInAs(role: 'student');
      final first =
          (h.backend.fixtures.value('questions_page')['items'] as List).first
              as Map;
      final title = first['title'] as String;
      final id = first['id'] as String;
      final router = GoRouter(
        initialLocation: '/practice',
        routes: [
          GoRoute(path: '/practice', builder: (_, _) => const PracticePage()),
          GoRoute(
            path: '/questions/:id/solve',
            builder: (_, _) => const Scaffold(body: Text('opened question')),
          ),
          GoRoute(
            path: '/questions/:id/drafts',
            builder: (_, _) =>
                const Scaffold(body: Text('opened cloud drafts')),
          ),
        ],
      );
      addTearDown(router.dispose);
      useSize(tester, tabletLandscape);
      await tester.pumpWidget(
        ProviderScope(
          overrides: h.overrides,
          child: MaterialApp.router(routerConfig: router),
        ),
      );
      await tester.pumpAndSettle();
      final card = find.byKey(ValueKey('question.$id'));
      final titleNode = find.descendant(
        of: card,
        matching: find.bySemanticsLabel(RegExp('^${RegExp.escape(title)}\$')),
      );
      expect(titleNode, findsOneWidget);
      expect(
        tester.getSemantics(titleNode),
        matchesSemantics(
          label: title,
          isButton: true,
          hasTapAction: true,
          hasFocusAction: true,
          isFocusable: true,
          hasEnabledState: true,
          isEnabled: true,
        ),
      );
      final cloud = find.descendant(
        of: card,
        matching: find.widgetWithText(TextButton, '云端草稿'),
      );
      expect(
        tester.getSemantics(cloud),
        matchesSemantics(
          label: '云端草稿 · $title',
          isButton: true,
          hasTapAction: true,
          hasFocusAction: true,
          isFocusable: true,
          hasEnabledState: true,
          isEnabled: true,
        ),
      );
      final titleText = find.descendant(of: card, matching: find.text(title));
      final titleFocus = Focus.of(tester.element(titleText));
      titleFocus.requestFocus();
      await tester.pump();
      expect(titleFocus.hasPrimaryFocus, isTrue);
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(find.text('opened question'), findsOneWidget);
      router.pop();
      await tester.pumpAndSettle();
      final cloudFocus = Focus.of(
        tester.element(find.descendant(of: card, matching: find.text('云端草稿'))),
      );
      cloudFocus.requestFocus();
      await tester.pump();
      expect(cloudFocus.hasPrimaryFocus, isTrue);
      await tester.tap(cloud);
      await tester.pumpAndSettle();
      expect(find.text('opened cloud drafts'), findsOneWidget);
      expect(find.text('opened question'), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
      semantics.dispose();
    },
  );
}
