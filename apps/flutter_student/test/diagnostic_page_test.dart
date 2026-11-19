import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/core/theme.dart';
import 'package:tutor_student/features/diagnostic/diagnostic_page.dart';
import 'package:tutor_student/features/diagnostic/diagnostic_store.dart';

import 'diagnostic_actions_test.dart' show DiagnosticTestAuth, DiagnosticWire;

Widget page(
  DiagnosticWire wire,
  MemoryStore disk,
  GoRouter router, {
  double scale = 1,
}) => ProviderScope(
  retry: (_, _) => null,
  overrides: [
    authProvider.overrideWith(DiagnosticTestAuth.new),
    keyValueStoreProvider.overrideWithValue(disk),
    apiTransportProvider.overrideWithValue(wire),
  ],
  child: MaterialApp.router(
    theme: AppTheme.light(),
    routerConfig: router,
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context)
          .copyWith(textScaler: TextScaler.linear(scale)),
      child: child!,
    ),
  ),
);

GoRouter router() => GoRouter(
  routes: [
    GoRoute(path: '/', builder: (_, _) => const DiagnosticPage()),
    GoRoute(
      path: '/questions/:id/solve',
      builder: (context, state) => Scaffold(
        body: Column(
          children: [
            Text('session=${state.uri.queryParameters['session']}'),
            TextButton(
              onPressed: () => context.pop(),
              child: const Text('返回摸底'),
            ),
          ],
        ),
      ),
    ),
  ],
);

void main() {
  testWidgets(
    'create shows fixed three questions and opens the existing solve route',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final wire = DiagnosticWire(),
          disk = MemoryStore(),
          navigation = router();
      addTearDown(navigation.dispose);
      await tester.pumpWidget(page(wire, disk, navigation));
      await tester.pumpAndSettle();
      expect(wire.posts, isEmpty);
      await tester.tap(find.byKey(const ValueKey('diagnostic.create')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('diagnostic.open.1')), findsOneWidget);
      expect(find.byKey(const ValueKey('diagnostic.open.3')), findsOneWidget);
      expect(find.textContaining('自编工程样题未经过学科审校'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('diagnostic.open.1')));
      await tester.pumpAndSettle();
      expect(
        find.text('session=${wire.fixtures.value('diagnostic_session')['id']}'),
        findsOneWidget,
      );
      expect(wire.posts, hasLength(2));
      await tester.tap(find.text('返回摸底'));
      await tester.pumpAndSettle();
      expect(find.text('继续作答'), findsOneWidget);
      expect(wire.posts, hasLength(2));
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'offline cached bound item stays openable and unbound items cannot start',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final wire = DiagnosticWire()..offline = true;
      final disk = MemoryStore(), navigation = router();
      addTearDown(navigation.dispose);
      final run = DiagnosticRun.fromJson(
        wire.fixtures.value('diagnostic_progress'),
      );
      await DiagnosticStore(
        disk,
        'alice',
      ).rememberCloud(DiagnosticWorkspace(revision: 2, run: run));
      await tester.pumpWidget(page(wire, disk, navigation));
      await tester.pumpAndSettle();
      expect(find.textContaining('当前显示本机记录'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const ValueKey('diagnostic.open.2')),
            )
            .onPressed,
        isNull,
      );
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const ValueKey('diagnostic.open.1')),
            )
            .onPressed,
        isNotNull,
      );
      await tester.tap(find.byKey(const ValueKey('diagnostic.open.1')));
      await tester.pumpAndSettle();
      expect(find.text('session=${run.items.first.sessionId}'), findsOneWidget);
      expect(wire.posts, isEmpty);
    },
  );

  testWidgets('pending command is visible after mount without automatic POST', (
    tester,
  ) async {
    final wire = DiagnosticWire(), disk = MemoryStore(), navigation = router();
    addTearDown(navigation.dispose);
    final journal = DiagnosticStore(disk, 'alice');
    await journal.rememberCloud(const DiagnosticWorkspace(revision: 0));
    await journal.prepareCreate(
      const DiagnosticCreate(
        subject: Subject.math,
        expectedRevision: 0,
        expectedProfileRevision: 1,
      ),
      'saved-create-intent',
    );
    await tester.pumpWidget(page(wire, disk, navigation));
    await tester.pumpAndSettle();
    expect(find.text('重试原操作'), findsOneWidget);
    expect(wire.posts, isEmpty);
    await tester.tap(find.byKey(const ValueKey('diagnostic.resume')));
    await tester.pumpAndSettle();
    expect(wire.posts.single.headers['Idempotency-Key'], 'saved-create-intent');
    expect((await journal.read()).pending, isNull);
  });

  testWidgets(
    'phone with enlarged text has no overflow or hidden start control',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final wire = DiagnosticWire(),
          disk = MemoryStore(),
          navigation = router();
      addTearDown(navigation.dispose);
      await tester.pumpWidget(page(wire, disk, navigation, scale: 1.5));
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const ValueKey('diagnostic.create')),
      );
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const ValueKey('diagnostic.create')),
            )
            .onPressed,
        isNotNull,
      );
      expect(tester.takeException(), isNull);
    },
  );
}
