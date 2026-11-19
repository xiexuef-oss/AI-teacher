import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:tutor_student/features/onboarding/onboarding_page.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/data.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/profile/profile_page.dart';

import 'support/fake_backend.dart';

class _ProfilePageTransport implements ApiTransport {
  final backend = FakeBackend()
    ..installAppBasics()
    ..installParentFlow();
  final started = Completer<void>();
  final held = Completer<RawResponse>();
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    if (method == 'PUT' && uri.path.endsWith('/profile')) {
      started.complete();
      return held.future;
    }
    return backend.send(method: method, uri: uri, headers: headers, body: body);
  }
}

void main() {
  for (final useCloud in [false, true]) {
    testWidgets(
      'zero learning budget recovers and resolves conflict (cloud=$useCloud)',
      (tester) async {
        tester.view.physicalSize = const Size(1280, 2400);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final backend = FakeBackend()
          ..installAppBasics()
          ..installParentFlow();
        final profile = backend.fixtures.value('profile_saved')
          ..['revision'] = 1;
        Map<String, Object> settings(int minutes) => {
          'mode': 'boarding',
          'weekdays': [1, 3],
          'weekly_minutes': minutes,
          'school_progress': '化学流程',
          'exam_scope': '选择题',
        };
        profile['learning_settings'] = settings(50);
        backend.on('GET', '/profile', (_) => okResponse(profile));
        final owner = profile['user_id'] as String;
        final store = MemoryStore({
          'auth.token': 'test-token',
          'auth.userId': owner,
          'auth.role': 'student',
        });
        Future<void> mount() async {
          await tester.pumpWidget(
            ProviderScope(
              overrides: [
                keyValueStoreProvider.overrideWithValue(store),
                apiTransportProvider.overrideWithValue(backend),
              ],
              child: const MaterialApp(home: ProfilePage()),
            ),
          );
          await tester.pumpAndSettle();
        }

        final budget = find.byWidgetPredicate(
          (widget) =>
              widget is TextField && widget.decoration?.labelText == '每周可用分钟',
        );
        await mount();
        await tester.enterText(budget, '0');
        await tester.pumpAndSettle();
        await tester.pumpWidget(const SizedBox());
        backend.offline = true;
        await mount();
        expect(tester.widget<TextField>(budget).controller!.text, '0');

        backend.offline = false;
        profile['revision'] = 2;
        profile['learning_settings'] = settings(75);
        await tester.pumpWidget(const SizedBox());
        await mount();
        expect(tester.widget<TextField>(budget).controller!.text, '0');
        final choice = find.byKey(
          ValueKey(useCloud ? 'profile.useCloud' : 'profile.useLocal'),
        );
        await tester.ensureVisible(choice);
        await tester.tap(choice);
        await tester.pumpAndSettle();
        expect(
          tester.widget<TextField>(budget).controller!.text,
          useCloud ? '75' : '0',
        );
        expect(
          backend.requests.where((request) => request.method == 'PUT'),
          isEmpty,
        );
        final save = find.byKey(const ValueKey('profile.save'));
        if (!useCloud) {
          await tester.ensureVisible(save);
          await tester.tap(save);
          await tester.pumpAndSettle();
          expect(backend.lastProfileUpdate?['expected_revision'], 2);
          expect(backend.lastProfileUpdate?['learning_settings'], settings(0));
        }
      },
    );
  }

  testWidgets(
    'onboarding late A receipt cannot navigate away from unpersisted edit B',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final transport = _ProfilePageTransport();
      transport.backend.profileFixture = 'profile_empty';
      final owner =
          transport.backend.fixtures.value('profile_empty')['user_id']
              as String;
      final disk = MemoryStore({
        'auth.token': 'token',
        'auth.userId': owner,
        'auth.role': 'student',
      });
      final container = ProviderContainer(
        overrides: [
          keyValueStoreProvider.overrideWithValue(disk),
          apiTransportProvider.overrideWithValue(transport),
        ],
      );
      addTearDown(container.dispose);
      await container.read(profileProvider.future);
      final router = GoRouter(
        initialLocation: '/onboarding',
        routes: [
          GoRoute(
            path: '/onboarding',
            builder: (_, _) => const OnboardingPage(),
          ),
          GoRoute(
            path: '/home',
            builder: (_, _) => const Scaffold(body: Text('arrived home')),
          ),
        ],
      );
      addTearDown(router.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp.router(routerConfig: router),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('region.CN-51')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('onboarding.next')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('onboarding.next')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('onboarding.next')));
      await tester.pump();
      await transport.started.future;
      disk.failWrites = true;
      await tester.tap(find.byKey(const ValueKey('curriculum.PEP')));
      await tester.pump();
      disk.failWrites = false;
      transport.held.complete(
        okResponse(
          transport.backend.fixtures.value('profile_saved')
            ..['user_id'] = owner
            ..['revision'] = 1,
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('onboarding.page')), findsOneWidget);
      expect(
        tester
            .widget<ChoiceChip>(find.byKey(const ValueKey('curriculum.PEP')))
            .selected,
        isTrue,
      );
    },
  );

  testWidgets(
    'failed local edit is never replaced by the earlier conflict snapshot',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 3000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final backend = FakeBackend()
        ..installAppBasics()
        ..installParentFlow();
      var profile = backend.fixtures.value('profile_saved')..['revision'] = 1;
      backend.on('GET', '/profile', (_) => okResponse(profile));
      final store = MemoryStore({
        'auth.token': 'test-token',
        'auth.userId': profile['user_id'] as String,
        'auth.role': 'student',
      });
      final container = ProviderContainer(
        overrides: [
          keyValueStoreProvider.overrideWithValue(store),
          apiTransportProvider.overrideWithValue(backend),
        ],
      );
      addTearDown(container.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: ProfilePage()),
        ),
      );
      await tester.pumpAndSettle();
      final name = find.byKey(const ValueKey('profile.displayName'));
      await tester.enterText(name, 'A');
      await tester.pumpAndSettle();
      profile = Map<String, dynamic>.from(profile)
        ..['revision'] = 2
        ..['display_name'] = 'cloud';
      container.invalidate(profileProvider);
      await tester.pumpAndSettle();
      store.failWrites = true;
      await tester.enterText(name, 'B');
      await tester.pumpAndSettle();
      store.failWrites = false;
      await tester.tap(find.byKey(const ValueKey('profile.useLocal')));
      await tester.pumpAndSettle();
      expect(tester.widget<TextField>(name).controller!.text, 'B');
      expect(
        container.read(profileProvider.notifier).bundle!.edit!['display_name'],
        'B',
      );
    },
  );

  testWidgets(
    'legacy offline cache displays and persists edits without inventing revision',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final backend = FakeBackend()
        ..installAppBasics()
        ..installParentFlow()
        ..offline = true;
      final legacy = backend.fixtures.value('profile_saved')
        ..remove('revision');
      final owner = legacy['user_id'] as String;
      final store = MemoryStore({
        'auth.token': 'legacy-token',
        'auth.userId': owner,
        'auth.role': 'student',
        'u/$owner/profile': jsonEncode(legacy),
      });
      store.data['launch_config'] = jsonEncode(
        backend.fixtures.value('launch_config'),
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            keyValueStoreProvider.overrideWithValue(store),
            apiTransportProvider.overrideWithValue(backend),
          ],
          child: const MaterialApp(home: ProfilePage()),
        ),
      );
      await tester.pumpAndSettle();
      final name = find.byKey(const ValueKey('profile.displayName'));
      expect(name, findsOneWidget);
      await tester.enterText(name, 'offline edit');
      await tester.pumpAndSettle();
      final bundle = jsonDecode(
        store.data['u/$owner/profile_bundle']!,
      ) as Map<String, dynamic>;
      expect(bundle['cloud'], isNull);
      expect((bundle['edit'] as Map)['display_name'], 'offline edit');
      await tester.ensureVisible(find.byKey(const ValueKey('profile.save')));
      expect(
        tester
            .widget<FilledButton>(find.byKey(const ValueKey('profile.save')))
            .onPressed,
        isNull,
      );
      expect(backend.requests.where((r) => r.method == 'PUT'), isEmpty);
    },
  );

  testWidgets('editing B while save A waits survives the A receipt', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final transport = _ProfilePageTransport();
    final store = MemoryStore({
      'auth.token': 'test-token',
      'auth.userId':
          transport.backend.fixtures.value('profile_saved')['user_id']
              as String,
      'auth.role': 'student',
    });
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          keyValueStoreProvider.overrideWithValue(store),
          apiTransportProvider.overrideWithValue(transport),
        ],
        child: const MaterialApp(home: ProfilePage()),
      ),
    );
    await tester.pumpAndSettle();
    final name = find.byKey(const ValueKey('profile.displayName'));
    await tester.enterText(name, 'A');
    await tester.ensureVisible(find.byKey(const ValueKey('profile.save')));
    await tester.tap(find.byKey(const ValueKey('profile.save')));
    await tester.pump();
    await transport.started.future;
    await tester.ensureVisible(name);
    await tester.enterText(name, 'B');
    final result = transport.backend.fixtures.value('profile_saved')
      ..['revision'] =
          (transport.backend.fixtures.value('profile_saved')['revision']
                  as int? ??
              1) +
          1
      ..['display_name'] = 'A'
      ..['updated_at'] = '2026-11-17T00:00:00Z';
    transport.held.complete(okResponse(result));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(name).controller!.text, 'B');
    expect(find.byKey(const ValueKey('profile.saved')), findsNothing);
  });
}
