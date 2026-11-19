import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/data.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';

import 'support/fake_backend.dart';

class _SwitchableAuth extends AuthController {
  @override
  Future<AuthSession> build() async =>
      const AuthSession(userId: 'A', token: 'token-A');
  void useB() =>
      state = const AsyncData(AuthSession(userId: 'B', token: 'token-B'));
}

class _HeldProfileTransport implements ApiTransport {
  final fixtures = Fixtures.load();
  final started = Completer<void>();
  final response = Completer<RawResponse>();
  final seen = <Seen>[];

  Map<String, dynamic> profile(String name) => fixtures.value('profile_saved')
    ..['revision'] = name == 'saved A' ? 2 : 1
    ..['display_name'] = name
    ..['user_id'] = name == 'B' ? 'B' : 'A';

  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    seen.add((method: method, uri: uri, headers: headers, body: body));
    if (method == 'PUT' && uri.path.endsWith('/profile')) {
      started.complete();
      return response.future;
    }
    return okResponse(
      profile(headers['Authorization'] == 'Bearer token-B' ? 'B' : 'A'),
    );
  }
}

class _RecoveryTransport implements ApiTransport {
  final seen = <Seen>[];
  final fixtures = Fixtures.load();
  bool loseResponse = true;
  bool conflict = false;
  bool invalid = false;
  int revision = 1;
  Map<String, dynamic>? receipt;
  Map<String, dynamic> cloud() => fixtures.value('profile_saved')
    ..['user_id'] = 'A'
    ..['revision'] = revision
    ..['display_name'] = revision == 1 ? 'initial' : 'cloud';
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    seen.add((method: method, uri: uri, headers: headers, body: body));
    if (method != 'PUT') return okResponse(receipt ?? cloud());
    if (invalid) {
      invalid = false;
      return errorResponse(422, 'validation_error');
    }
    if (conflict) {
      conflict = false;
      revision = 2;
      return errorResponse(
        409,
        'profile_revision_conflict',
        details: {'server_profile': cloud()},
      );
    }
    receipt ??= cloud()
      ..['revision'] = ++revision
      ..['display_name'] = 'saved';
    if (loseResponse) {
      loseResponse = false;
      throw ApiException.network('lost response');
    }
    return okResponse(receipt!);
  }
}

void main() {
  test('launch options persist across offline restart; corrupt cache bytes remain intact', () async {
    final disk = MemoryStore();
    final backend = FakeBackend()..installAppBasics();
    ProviderContainer create() => ProviderContainer(
      overrides: [
        authProvider.overrideWith(_SwitchableAuth.new),
        keyValueStoreProvider.overrideWithValue(disk),
        apiTransportProvider.overrideWithValue(backend),
      ],
    );
    final first = create();
    final config = await first.read(launchConfigProvider.future);
    first.dispose();
    backend.offline = true;
    final second = create();
    expect(
      (await second.read(launchConfigProvider.future)).toJson(),
      config.toJson(),
    );
    second.dispose();
    disk.data['launch_config'] = '{unknown bytes';
    backend.offline = false;
    final third = create();
    await third.read(launchConfigProvider.future);
    expect(disk.data['launch_config'], '{unknown bytes');
    third.dispose();
  });

  test('refresh never silently rebases unsubmitted local edits onto another writer', () async {
    final transport = _RecoveryTransport()..loseResponse = false;
    final container = ProviderContainer(
      overrides: [
        authProvider.overrideWith(_SwitchableAuth.new),
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        apiTransportProvider.overrideWithValue(transport),
      ],
    );
    addTearDown(container.dispose);
    await container.read(profileProvider.future);
    await container.read(profileProvider.notifier).edit({
      'region_code': 'CN-51',
      'subjects': ['math'],
      'display_name': 'local',
    });
    transport.revision = 2;
    container.invalidate(profileProvider);
    await container.read(profileProvider.future);
    await expectLater(
      container
          .read(profileProvider.notifier)
          .save(
            ProfileUpdate.fromJson({
              'region_code': 'CN-51',
              'subjects': ['math'],
              'display_name': 'local',
              'expected_revision': 2,
            }),
          ),
      throwsStateError,
    );
    expect(transport.seen.where((r) => r.method == 'PUT'), isEmpty);
    final controller = container.read(profileProvider.notifier);
    expect(controller.bundle!.editConflict, isTrue);
    await controller.resolveConflict(useCloud: false);
    expect(controller.bundle!.editConflict, isFalse);
    await controller.save(
      ProfileUpdate.fromJson({
        'region_code': 'CN-51',
        'subjects': ['math'],
        'display_name': 'local',
        'expected_revision': 2,
      }),
    );
    expect(transport.seen.where((r) => r.method == 'PUT').length, 1);
  });

  test('definite validation rejection keeps input and permits a corrected new intent', () async {
    final transport = _RecoveryTransport()
      ..invalid = true
      ..loseResponse = false;
    final container = ProviderContainer(
      overrides: [
        authProvider.overrideWith(_SwitchableAuth.new),
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        apiTransportProvider.overrideWithValue(transport),
      ],
    );
    addTearDown(container.dispose);
    await container.read(profileProvider.future);
    final controller = container.read(profileProvider.notifier);
    ProfileUpdate body(String name) => ProfileUpdate.fromJson({
      'region_code': 'CN-51',
      'subjects': ['math'],
      'display_name': name,
      'expected_revision': 1,
    });
    await expectLater(
      controller.save(body('invalid')),
      throwsA(isA<ApiException>()),
    );
    expect(controller.bundle!.pending, isNull);
    expect(controller.bundle!.edit!['display_name'], 'invalid');
    await controller.save(body('fixed'));
    final writes = transport.seen.where((r) => r.method == 'PUT').toList();
    expect(writes.length, 2);
    expect(
      writes[1].headers['Idempotency-Key'],
      isNot(writes[0].headers['Idempotency-Key']),
    );
  });

  test('restart GET equality does not ACK unknown command; explicit retry reuses exact key/body', () async {
    final disk = MemoryStore();
    final transport = _RecoveryTransport();
    ProviderContainer create() => ProviderContainer(
      overrides: [
        authProvider.overrideWith(_SwitchableAuth.new),
        keyValueStoreProvider.overrideWithValue(disk),
        apiTransportProvider.overrideWithValue(transport),
      ],
    );
    final first = create();
    await first.read(profileProvider.future);
    await expectLater(
      first
          .read(profileProvider.notifier)
          .save(
            ProfileUpdate.fromJson({
              'region_code': 'CN-51',
              'subjects': ['math'],
              'display_name': 'saved',
              'expected_revision': 1,
            }),
          ),
      throwsA(isA<ApiException>()),
    );
    first.dispose();
    final second = create();
    addTearDown(second.dispose);
    await second.read(profileProvider.future);
    final controller = second.read(profileProvider.notifier);
    expect(controller.bundle!.pending!.phase, 'prepared');
    expect(transport.seen.where((r) => r.method == 'PUT').length, 1);
    await controller.retryPending();
    final writes = transport.seen.where((r) => r.method == 'PUT').toList();
    expect(writes.length, 2);
    expect(
      writes[1].headers['Idempotency-Key'],
      writes[0].headers['Idempotency-Key'],
    );
    expect(writes[1].headers['Authorization'], 'Bearer token-A');
    expect(writes[1].body, writes[0].body);
    expect(controller.bundle!.pending, isNull);
  });

  test('CAS conflict retains both sides until explicit local choice creates new intent', () async {
    final transport = _RecoveryTransport()
      ..conflict = true
      ..loseResponse = false;
    final container = ProviderContainer(
      overrides: [
        authProvider.overrideWith(_SwitchableAuth.new),
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        apiTransportProvider.overrideWithValue(transport),
      ],
    );
    addTearDown(container.dispose);
    await container.read(profileProvider.future);
    final controller = container.read(profileProvider.notifier);
    ProfileUpdate update(int revision) => ProfileUpdate.fromJson({
      'region_code': 'CN-51',
      'subjects': ['math'],
      'display_name': 'local',
      'expected_revision': revision,
    });
    await expectLater(controller.save(update(1)), throwsA(isA<ApiException>()));
    expect(controller.bundle!.pending!.phase, 'conflict');
    expect(controller.bundle!.edit!['display_name'], 'local');
    expect(controller.bundle!.cloud!.displayName, 'cloud');
    await controller.resolveConflict(useCloud: false);
    expect(controller.bundle!.edit!['display_name'], 'local');
    await controller.save(update(2));
    final writes = transport.seen.where((r) => r.method == 'PUT').toList();
    expect(writes.length, 2);
    expect(
      writes[1].headers['Idempotency-Key'],
      isNot(writes[0].headers['Idempotency-Key']),
    );
    expect(jsonDecode(writes[1].body!)['expected_revision'], 2);
  });

  test('late owner A save cannot replace owner B state or cache', () async {
    final transport = _HeldProfileTransport();
    final store = MemoryStore();
    final auth = _SwitchableAuth();
    final container = ProviderContainer(
      overrides: [
        authProvider.overrideWith(() => auth),
        keyValueStoreProvider.overrideWithValue(store),
        apiTransportProvider.overrideWithValue(transport),
      ],
    );
    addTearDown(container.dispose);
    await container.read(profileProvider.future);
    final body = ProfileUpdate.fromJson({
      'region_code': 'CN-51',
      'subjects': ['math'],
      'display_name': 'saved A',
      'expected_revision': 1,
    });
    final save = container.read(profileProvider.notifier).save(body);
    await transport.started.future;
    auth.useB();
    await container.read(studentSessionProvider.future);
    await container.read(profileProvider.future);
    final before = Map<String, String>.fromEntries(
      store.data.entries.where((e) => e.key.startsWith('u/B/')),
    );
    transport.response.complete(okResponse(transport.profile('saved A')));
    await save;
    expect(container.read(profileProvider).asData?.value.displayName, 'B');
    expect(
      Map<String, String>.fromEntries(
        store.data.entries.where((e) => e.key.startsWith('u/B/')),
      ),
      before,
    );
    expect(
      jsonDecode(
        transport.seen.firstWhere((r) => r.method == 'PUT').body!,
      )['display_name'],
      'saved A',
    );
  });
}
