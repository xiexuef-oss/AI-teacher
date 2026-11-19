import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/core/theme.dart';
import 'package:tutor_student/features/diagnostic/diagnostic_history_page.dart';

import 'diagnostic_actions_test.dart' show DiagnosticTestAuth;
import 'support/fake_backend.dart';

class _Auth extends DiagnosticTestAuth {
  void parent() => state = const AsyncData(
    AuthSession(
      userId: 'parent',
      token: 'parent-token',
      role: LocalRole.parent,
    ),
  );
}

GoRouter navigation() => GoRouter(
  routes: [
    GoRoute(path: '/', builder: (_, _) => const DiagnosticHistoryScreen()),
    GoRoute(
      path: '/diagnostic/history',
      builder: (_, state) =>
          DiagnosticHistoryScreen(cursor: state.uri.queryParameters['cursor']),
    ),
    GoRoute(
      path: '/questions/:id/solve',
      builder: (_, state) => Scaffold(
        body: Text('session=${state.uri.queryParameters['session']}'),
      ),
    ),
  ],
);

Widget _historyApp(FakeBackend backend, GoRouter router, {_Auth? auth}) =>
    ProviderScope(
      retry: (_, _) => null,
      overrides: [
        authProvider.overrideWith(() => auth ?? _Auth()),
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        apiTransportProvider.overrideWithValue(backend),
      ],
      child: MaterialApp.router(theme: AppTheme.light(), routerConfig: router),
    );

void main() {
  testWidgets('history pages use generated cursor and never issue a write', (
    tester,
  ) async {
    final backend = FakeBackend(), router = navigation();
    addTearDown(router.dispose);
    final original = backend.fixtures.value('diagnostic_history');
    final id = (original['items'] as List).first['id'] as String;
    backend.on(
      'GET',
      '/diagnostics/history',
      (request) => okResponse(
        request.uri.queryParameters['cursor'] == null
            ? {...original, 'next_cursor': id}
            : {'items': [], 'next_cursor': null},
      ),
    );
    await tester.pumpWidget(_historyApp(backend, router));
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byKey(const ValueKey('diagnostic.history.next')),
    );
    await tester.tap(find.byKey(const ValueKey('diagnostic.history.next')));
    await tester.pumpAndSettle();
    expect(find.text('这一页没有摸底记录'), findsOneWidget);
    final requests = backend.requests
        .where((r) => r.uri.path.endsWith('/diagnostics/history'))
        .toList();
    expect(requests.last.uri.queryParameters['cursor'], id);
    expect(requests.last.uri.queryParameters['limit'], '20');
    expect(backend.requests.where((r) => r.method != 'GET'), isEmpty);
  });

  testWidgets(
    'historical bound session opens by its fixed ID without creation',
    (tester) async {
      final backend = FakeBackend(), router = navigation();
      addTearDown(router.dispose);
      final history = backend.fixtures.value('diagnostic_history');
      backend.on('GET', '/diagnostics/history', (_) => okResponse(history));
      await tester.pumpWidget(_historyApp(backend, router));
      await tester.pumpAndSettle();
      final run = (history['items'] as List).first as Map;
      await tester.tap(find.byKey(ValueKey('diagnostic.history.${run['id']}')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('继续已有作答'));
      await tester.tap(find.text('继续已有作答'));
      await tester.pumpAndSettle();
      final session = (run['items'] as List).first['session_id'];
      expect(find.text('session=$session'), findsOneWidget);
      expect(backend.requests.where((r) => r.method != 'GET'), isEmpty);
    },
  );

  testWidgets(
    'failed history load shows retry rather than an invented empty page',
    (tester) async {
      final backend = FakeBackend(), router = navigation();
      addTearDown(router.dispose);
      var fail = true;
      backend.on(
        'GET',
        '/diagnostics/history',
        (_) => fail
            ? errorResponse(503, 'internal_error')
            : okResponse(backend.fixtures.value('diagnostic_history')),
      );
      await tester.pumpWidget(_historyApp(backend, router));
      await tester.pumpAndSettle();
      expect(find.text('这一页没有摸底记录'), findsNothing);
      expect(find.text('重试'), findsOneWidget);
      fail = false;
      await tester.tap(find.text('重试'));
      await tester.pumpAndSettle();
      expect(find.byType(ExpansionTile), findsOneWidget);
    },
  );

  testWidgets(
    'student history disappears on parent switch before any new GET',
    (tester) async {
      final backend = FakeBackend(), router = navigation(), auth = _Auth();
      addTearDown(router.dispose);
      backend.on(
        'GET',
        '/diagnostics/history',
        (_) => okResponse(backend.fixtures.value('diagnostic_history')),
      );
      await tester.pumpWidget(_historyApp(backend, router, auth: auth));
      await tester.pumpAndSettle();
      expect(find.byType(ExpansionTile), findsOneWidget);
      final reads = backend.requests.length;
      auth.parent();
      await tester.pumpAndSettle();
      expect(find.byType(ExpansionTile), findsNothing);
      expect(backend.requests.length, reads);
    },
  );
}
