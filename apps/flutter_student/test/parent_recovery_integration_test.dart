import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/parent/parent_home_page.dart';
import 'package:tutor_student/features/parent/parent_actions.dart';
import 'package:tutor_student/features/parent/parent_command_store.dart';
import 'package:tutor_student/features/profile/parent_access_section.dart';

import 'support/fake_backend.dart';

class _RedeemTransport implements ApiTransport {
  final backend = FakeBackend()
    ..installAppBasics()
    ..installParentFlow();
  final writes = <Seen>[];
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    if (method == 'POST' && uri.path.endsWith('/parents/links')) {
      writes.add((method: method, uri: uri, headers: headers, body: body));
      throw ApiException.network('response lost');
    }
    return backend.send(method: method, uri: uri, headers: headers, body: body);
  }
}

class _SwitchAuth extends AuthController {
  @override
  Future<AuthSession> build() async =>
      const AuthSession(userId: 'A', token: 'token-A');
  void switchB() =>
      state = const AsyncData(AuthSession(userId: 'B', token: 'token-B'));
}

class _CreateGate implements ApiTransport {
  final started = Completer<void>();
  final held = Completer<RawResponse>();
  final backend = FakeBackend()
    ..installAppBasics()
    ..installParentFlow();
  final seen = <Seen>[];
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    seen.add((method: method, uri: uri, headers: headers, body: body));
    if (method == 'POST' && uri.path.endsWith('/parent-invites')) {
      started.complete();
      return held.future;
    }
    return backend.send(method: method, uri: uri, headers: headers, body: body);
  }

  void release() => held.complete(
    okResponse(
      backend.fixtures.value('parent_invite')..['parent_invite_revision'] = 1,
      status: 201,
    ),
  );
}

class _CommittedLost implements ApiTransport {
  final backend = FakeBackend()
    ..installAppBasics()
    ..installParentFlow();
  final writes = <Seen>[];
  bool lose = true;
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    final response = await backend.send(
      method: method,
      uri: uri,
      headers: headers,
      body: body,
    );
    if (method == 'POST' && uri.path.endsWith('/parent-invites')) {
      writes.add((method: method, uri: uri, headers: headers, body: body));
      if (lose) {
        lose = false;
        throw ApiException.network('lost response');
      }
    }
    return response;
  }
}

class _ReplacedCreate extends _CreateGate {
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    if (method == 'POST' &&
        uri.path.endsWith('/parent-invites') &&
        started.isCompleted) {
      seen.add((method: method, uri: uri, headers: headers, body: body));
      return backend.send(
        method: method,
        uri: uri,
        headers: headers,
        body: body,
      );
    }
    return super.send(method: method, uri: uri, headers: headers, body: body);
  }
}

void main() {
  testWidgets(
    'undisplayable replaced invite still refreshes the next explicit create source',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final transport = _ReplacedCreate();
      final disk = MemoryStore();
      final container = ProviderContainer(
        overrides: [
          authProvider.overrideWith(_SwitchAuth.new),
          keyValueStoreProvider.overrideWithValue(disk),
          apiTransportProvider.overrideWithValue(transport),
          clockProvider.overrideWithValue(() => DateTime.utc(2026, 11, 10, 8)),
        ],
      );
      addTearDown(container.dispose);
      await container.read(parentActionsProvider.future);
      await container.read(parentActionsProvider.notifier).refresh();
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: Scaffold(body: ParentAccessSection())),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('parent.invite')));
      await tester.pump();
      await transport.started.future;
      transport.backend.parentInviteRevision = 2;
      transport.backend.pendingInvite = {
        'id': 'replacement-invite',
        'created_at': '2026-11-10T08:00:00Z',
        'expires_at': '2026-11-11T08:00:00Z',
      };
      transport.release();
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('parent.invite.code')).evaluate().length,
        0,
      );
      await tester.tap(find.byKey(const ValueKey('parent.invite')));
      await tester.pumpAndSettle();
      final writes = transport.seen
          .where(
            (r) => r.method == 'POST' && r.uri.path.endsWith('/parent-invites'),
          )
          .toList();
      expect(writes.length, 2);
      expect(
        jsonDecode(writes.last.body!)['expected_parent_invite_revision'],
        2,
      );
      expect(
        writes.last.headers['Idempotency-Key'],
        isNot(writes.first.headers['Idempotency-Key']),
      );
    },
  );

  test('server committed create recovers original key/body after restart and GET never ACKs', () async {
    final transport = _CommittedLost();
    final disk = MemoryStore();
    ProviderContainer create() => ProviderContainer(
      overrides: [
        authProvider.overrideWith(_SwitchAuth.new),
        keyValueStoreProvider.overrideWithValue(disk),
        apiTransportProvider.overrideWithValue(transport),
      ],
    );
    final first = create();
    await first.read(parentActionsProvider.future);
    await first.read(parentActionsProvider.notifier).refresh();
    await expectLater(
      first.read(parentActionsProvider.notifier).create(0),
      throwsA(isA<ApiException>()),
    );
    first.dispose();
    final second = create();
    addTearDown(second.dispose);
    await second.read(parentActionsProvider.future);
    await second.read(parentActionsProvider.notifier).refresh();
    expect(
      second.read(parentActionsProvider).requireValue!.active!.phase,
      'prepared',
    );
    await second.read(parentActionsProvider.notifier).retry();
    expect(transport.writes.length, 2);
    expect(transport.writes[1].body, transport.writes[0].body);
    expect(
      transport.writes[1].headers['Idempotency-Key'],
      transport.writes[0].headers['Idempotency-Key'],
    );
    expect(transport.backend.invitesCreated, 1);
  });
  test(
    'revoke conflict cannot automatically revoke a replacement authorization',
    () async {
      final backend = FakeBackend()
        ..installAppBasics()
        ..installParentFlow();
      final initial = Map<String, dynamic>.from(
        (backend.fixtures.value('parent_links')['links'] as List).first as Map,
      )..['authorization_revision'] = 1;
      backend.parentLinks = [initial];
      final container = ProviderContainer(
        overrides: [
          authProvider.overrideWith(_SwitchAuth.new),
          keyValueStoreProvider.overrideWithValue(MemoryStore()),
          apiTransportProvider.overrideWithValue(backend),
        ],
      );
      addTearDown(container.dispose);
      await container.read(parentActionsProvider.future);
      final actions = container.read(parentActionsProvider.notifier);
      await actions.refresh();
      backend.parentLinks = [
        Map<String, dynamic>.from(initial)..['authorization_revision'] = 3,
      ];
      await expectLater(
        actions.revoke(ParentLink.fromJson(initial)),
        throwsA(isA<ApiException>()),
      );
      expect(backend.revokes, 0);
      expect(
        container
            .read(parentActionsProvider)
            .requireValue!
            .active!
            .conflict!['authorization_revision'],
        3,
      );
      await actions.finishConflict();
      await actions.revoke(
        ParentLink.fromJson(
          Map<String, dynamic>.from(initial)..['authorization_revision'] = 3,
        ),
      );
      expect(backend.revokes, 1);
    },
  );

  testWidgets(
    'a delivered create response already past expiry never displays its code',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final backend = FakeBackend()
        ..installAppBasics()
        ..installParentFlow();
      final disk = MemoryStore();
      final container = ProviderContainer(
        overrides: [
          authProvider.overrideWith(_SwitchAuth.new),
          keyValueStoreProvider.overrideWithValue(disk),
          apiTransportProvider.overrideWithValue(backend),
          clockProvider.overrideWithValue(() => DateTime.utc(2100)),
        ],
      );
      addTearDown(container.dispose);
      await container.read(parentActionsProvider.future);
      await container.read(parentActionsProvider.notifier).refresh();
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: Scaffold(body: ParentAccessSection())),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('parent.invite')));
      await tester.pumpAndSettle();
      expect(backend.invitesCreated, 1);
      expect(
        find.byKey(const ValueKey('parent.invite.code')).evaluate().length,
        0,
      );
      expect(
        disk.data.values.join(),
        isNot(contains(backend.fixtures.value('parent_invite')['code'])),
      );
    },
  );

  testWidgets(
    'known create with unavailable delivery offers explicit successful-history closure',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final backend = FakeBackend()
        ..installAppBasics()
        ..installParentFlow();
      backend.on(
        'POST',
        '/me/parent-invites',
        (_) => errorResponse(409, 'invite_response_expired'),
      );
      final disk = MemoryStore();
      final journal = ParentCommandStore(disk, 'A', 'student');
      final ticket = await journal.beginRefresh();
      await journal.rememberCurrent(
        ParentLinks.fromJson({
          'links': [],
          'parent_invite_revision': 0,
          'pending_invite': null,
        }),
        generation: ticket,
      );
      await journal.prepareCreate(
        const ParentInviteCreate(expectedParentInviteRevision: 0),
        key: 'known-create',
        activeEpoch: 0,
      );
      await journal.recordResult(
        'known-create',
        ParentInvite.fromJson(
          backend.fixtures.value('parent_invite')
            ..['parent_invite_revision'] = 1,
        ),
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            authProvider.overrideWith(_SwitchAuth.new),
            keyValueStoreProvider.overrideWithValue(disk),
            apiTransportProvider.overrideWithValue(backend),
          ],
          child: const MaterialApp(home: Scaffold(body: ParentAccessSection())),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('parent.retry')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('parent.finishKnown')), findsOneWidget);
      final requests = backend.requests.length;
      await tester.tap(find.byKey(const ValueKey('parent.finishKnown')));
      await tester.pumpAndSettle();
      expect(backend.requests.length, requests);
      final restored = await journal.read();
      expect(restored!.active, isNull);
      expect(restored.commands.single.result, isNotNull);
    },
  );

  test('two explicit consecutive creates refresh the safe source without rebasing an existing command', () async {
    final backend = FakeBackend()
      ..installAppBasics()
      ..installParentFlow();
    final container = ProviderContainer(
      overrides: [
        authProvider.overrideWith(_SwitchAuth.new),
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        apiTransportProvider.overrideWithValue(backend),
      ],
    );
    addTearDown(container.dispose);
    await container.read(parentActionsProvider.future);
    final actions = container.read(parentActionsProvider.notifier);
    await actions.refresh();
    await actions.create(0);
    await actions.create(1);
    expect(backend.invitesCreated, 2);
  });

  test(
    'late create keeps original bearer and never exposes owner A code to B',
    () async {
      final transport = _CreateGate();
      final disk = MemoryStore();
      final auth = _SwitchAuth();
      final container = ProviderContainer(
        overrides: [
          authProvider.overrideWith(() => auth),
          keyValueStoreProvider.overrideWithValue(disk),
          apiTransportProvider.overrideWithValue(transport),
        ],
      );
      addTearDown(container.dispose);
      await container.read(parentActionsProvider.future);
      await container.read(parentActionsProvider.notifier).refresh();
      final pending = container.read(parentActionsProvider.notifier).create(0);
      await transport.started.future;
      auth.switchB();
      await container.read(parentActionsProvider.future);
      final before = Map<String, String>.fromEntries(
        disk.data.entries.where((e) => e.key.startsWith('u/B/')),
      );
      transport.release();
      expect(await pending, isNull);
      expect(
        Map<String, String>.fromEntries(
          disk.data.entries.where((e) => e.key.startsWith('u/B/')),
        ),
        before,
      );
      expect(transport.seen.last.headers['Authorization'], 'Bearer token-A');
      expect(
        disk.data.values.join(),
        isNot(
          contains(transport.backend.fixtures.value('parent_invite')['code']),
        ),
      );
    },
  );
  test(
    'create result persistence failure never returns a displayable code',
    () async {
      final transport = _CreateGate();
      final disk = MemoryStore();
      final container = ProviderContainer(
        overrides: [
          authProvider.overrideWith(_SwitchAuth.new),
          keyValueStoreProvider.overrideWithValue(disk),
          apiTransportProvider.overrideWithValue(transport),
        ],
      );
      addTearDown(container.dispose);
      await container.read(parentActionsProvider.future);
      await container.read(parentActionsProvider.notifier).refresh();
      final pending = container.read(parentActionsProvider.notifier).create(0);
      await transport.started.future;
      disk.failWrites = true;
      transport.release();
      await expectLater(pending, throwsStateError);
      expect(
        disk.data.values.join(),
        isNot(
          contains(transport.backend.fixtures.value('parent_invite')['code']),
        ),
      );
    },
  );

  testWidgets(
    'first redeem wire is canonical and unknown intent survives restart without plaintext',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final transport = _RedeemTransport();
      final disk = MemoryStore({
        'auth.token': 'parent-token',
        'auth.userId': 'parent-owner',
        'auth.role': 'parent',
      });
      Widget app() => ProviderScope(
        overrides: [
          keyValueStoreProvider.overrideWithValue(disk),
          apiTransportProvider.overrideWithValue(transport),
        ],
        child: const MaterialApp(home: ParentHomePage()),
      );
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('parent.code')),
        'abcde-fghjk',
      );
      await tester.pump();
      await tester.tap(find.byKey(const ValueKey('parent.link')));
      await tester.pumpAndSettle();
      expect(jsonDecode(transport.writes.single.body!)['code'], 'ABCDEFGHJK');
      expect(disk.data.values.join(), isNot(contains('ABCDEFGHJK')));
      expect(
        disk.data.keys.any((k) => k.contains('parent_authorization_bundle')),
        isTrue,
      );
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('parent.retry')), findsOneWidget);
      expect(transport.writes.length, 1);
    },
  );
}
