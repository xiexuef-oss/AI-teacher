import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/scan/scan_actions.dart';

import 'support/fake_backend.dart';

class _Auth extends AuthController {
  @override
  Future<AuthSession> build() async =>
      const AuthSession(userId: 'owner-A', token: 'token-A');
  void switchB() =>
      state = const AsyncData(AuthSession(userId: 'owner-B', token: 'token-B'));
}

class _Wire implements ApiTransport {
  final backend = FakeBackend()
    ..installAppBasics()
    ..installScanFlow(questionId: 'question-a');
  final writes = <Seen>[];
  void Function()? afterResponse;
  bool expired = false;
  String? lose;
  int? storageStatus;
  String? storageStage;
  String? storageCode;
  bool hold = false;
  final started = Completer<void>();
  final released = Completer<void>();
  final receipts = <String, RawResponse>{};
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    if (method == 'GET') {
      return backend.send(
        method: method,
        uri: uri,
        headers: headers,
        body: body,
      );
    }
    writes.add((method: method, uri: uri, headers: headers, body: body));
    if (expired) return errorResponse(404, 'not_found');
    if (storageStatus != null && uri.path.endsWith(storageStage!)) {
      final status = storageStatus!;
      storageStatus = null;
      return errorResponse(
        status,
        storageCode ??
            (status == 409 ? 'storage_conflict' : 'storage_unavailable'),
      );
    }
    final key = headers['Idempotency-Key']!;
    final result =
        receipts[key] ??
        await backend.send(
          method: method,
          uri: uri,
          headers: headers,
          body: body,
        );
    receipts[key] = result;
    if (hold) {
      hold = false;
      started.complete();
      await released.future;
    }
    if (lose != null && uri.path.endsWith(lose!)) {
      lose = null;
      throw ApiException.network('response lost');
    }
    afterResponse?.call();
    afterResponse = null;
    return result;
  }
}

class _FailDisk extends MemoryStore {
  int writes = 0;
  int? failAt;
  @override
  Future<void> write(String key, String value) async {
    if (++writes == failAt) throw StateError('one write failed');
    await super.write(key, value);
  }
}

final pixels = Uint8List.fromList([1, 2, 3, 4]);
ProviderContainer _setup(MemoryStore disk, _Wire wire, {_Auth? auth}) =>
    ProviderContainer(
      overrides: [
        authProvider.overrideWith(() => auth ?? _Auth()),
        keyValueStoreProvider.overrideWithValue(disk),
        apiTransportProvider.overrideWithValue(wire),
      ],
    );
void main() {
  test('business conflict still rejects the original scan command', () async {
    final disk = MemoryStore();
    final wire = _Wire();
    final container = _setup(disk, wire);
    addTearDown(container.dispose);
    await container.read(scanActionsProvider.future);
    final actions = container.read(scanActionsProvider.notifier);
    await actions.upload('image/png', pixels);
    await actions.edit('A', '');
    wire.storageStatus = 409;
    wire.storageStage = 'confirm';
    wire.storageCode = 'scan_already_confirmed';
    await expectLater(actions.confirm(), throwsA(isA<ApiException>()));
    expect(actions.workspace!.commands.last.phase, 'rejected');
    expect(actions.workspace!.active, isNull);
    final writes = wire.writes.length;
    await expectLater(actions.retry(), throwsStateError);
    expect(wire.writes.length, writes);
  });
  for (final status in [409, 503]) {
    for (final stage in ['uploads', 'content', 'scans', 'confirm']) {
      test(
        '$stage storage $status retains original command through restart',
        () async {
          final disk = MemoryStore();
          final wire = _Wire();
          final first = _setup(disk, wire);
          await first.read(scanActionsProvider.future);
          final actions = first.read(scanActionsProvider.notifier);
          if (stage == 'confirm') {
            await actions.upload('image/png', pixels);
            await actions.edit('A', '');
          }
          wire.storageStatus = status;
          wire.storageStage = stage;
          await expectLater(
            stage == 'confirm'
                ? actions.confirm()
                : actions.upload('image/png', pixels),
            throwsA(isA<ApiException>()),
          );
          final original = wire.writes.last;
          expect(actions.workspace!.active!.phase, 'prepared');
          first.dispose();
          final second = _setup(disk, wire);
          addTearDown(second.dispose);
          await second.read(scanActionsProvider.future);
          await second
              .read(scanActionsProvider.notifier)
              .retry(bytes: stage == 'content' ? pixels : null);
          expect(
            wire.writes.last.headers['Idempotency-Key'],
            original.headers['Idempotency-Key'],
          );
          expect(wire.writes.last.body, original.body);
          expect(wire.writes.last.uri, original.uri);
          expect(disk.data.values.join(), isNot(contains('AQIDBA==')));
        },
      );
    }
  }
  test(
    'known metadata result can ACK offline without bytes after lost ACK write',
    () async {
      final disk = _FailDisk();
      final wire = _Wire();
      final first = _setup(disk, wire);
      await first.read(scanActionsProvider.future);
      wire.afterResponse = () => disk.failAt = disk.writes + 2;
      await expectLater(
        first.read(scanActionsProvider.notifier).upload('image/png', pixels),
        throwsStateError,
      );
      expect(
        first.read(scanActionsProvider.notifier).workspace!.active!.phase,
        'result_known',
      );
      first.dispose();
      final second = _setup(disk, wire);
      addTearDown(second.dispose);
      await second.read(scanActionsProvider.future);
      wire.backend.offline = true;
      final count = wire.writes.length;
      await second.read(scanActionsProvider.notifier).acknowledge();
      expect(wire.writes.length, count);
      expect(
        second.read(scanActionsProvider.notifier).workspace!.mediaId,
        'scan-media',
      );
    },
  );
  test('TTL 404 retains unknown command in original workspace when starting another image', () async {
    final disk = MemoryStore();
    final wire = _Wire()..lose = 'content';
    final container = _setup(disk, wire);
    addTearDown(container.dispose);
    await container.read(scanActionsProvider.future);
    final actions = container.read(scanActionsProvider.notifier);
    await expectLater(
      actions.upload('image/png', pixels),
      throwsA(isA<ApiException>()),
    );
    final old = actions.workspace!.id;
    wire.expired = true;
    await expectLater(
      actions.retry(bytes: pixels),
      throwsA(isA<ApiException>()),
    );
    expect(actions.workspace!.active!.phase, 'unavailable');
    await actions.newWorkspace();
    expect(
      container
          .read(scanActionsProvider)
          .requireValue!
          .workspace(old)
          .active!
          .phase,
      'unavailable',
    );
    expect(actions.workspace!.id, isNot(old));
  });

  for (final stage in ['uploads', 'content', 'scans', 'confirm']) {
    test(
      '$stage committed response loss preserves exact original key across reconstruction',
      () async {
        final disk = MemoryStore();
        final wire = _Wire()..lose = stage;
        final first = _setup(disk, wire);
        await first.read(scanActionsProvider.future);
        final actions = first.read(scanActionsProvider.notifier);
        if (stage == 'confirm') {
          wire.lose = null;
          await actions.upload('image/png', pixels);
          await actions.edit('A', '');
          wire.lose = stage;
          await expectLater(actions.confirm(), throwsA(isA<ApiException>()));
        } else {
          await expectLater(
            actions.upload('image/png', pixels),
            throwsA(isA<ApiException>()),
          );
        }
        final original = wire.writes.last;
        first.dispose();
        final second = _setup(disk, wire);
        addTearDown(second.dispose);
        await second.read(scanActionsProvider.future);
        final restored = second.read(scanActionsProvider.notifier);
        expect(restored.workspace!.active!.phase, 'prepared');
        if (stage == 'content') {
          await expectLater(
            restored.retry(bytes: Uint8List.fromList([9, 9, 9, 9])),
            throwsStateError,
          );
          expect(
            wire.writes.length,
            stage == 'content' ? 2 : wire.writes.length,
          );
        }
        await restored.retry(bytes: stage == 'content' ? pixels : null);
        expect(
          wire.writes.last.headers['Idempotency-Key'],
          original.headers['Idempotency-Key'],
        );
        expect(wire.writes.last.body, original.body);
        expect(disk.data.values.join(), isNot(contains('AQIDBA==')));
      },
    );
  }
  test(
    'switching account while upload waits prevents subsequent content HTTP',
    () async {
      final wire = _Wire()..hold = true;
      final disk = MemoryStore();
      final auth = _Auth();
      final container = _setup(disk, wire, auth: auth);
      addTearDown(container.dispose);
      await container.read(scanActionsProvider.future);
      final pending = container
          .read(scanActionsProvider.notifier)
          .upload('image/png', pixels);
      await wire.started.future;
      auth.switchB();
      await container.read(scanActionsProvider.future);
      wire.released.complete();
      await expectLater(pending, throwsStateError);
      expect(wire.writes.length, 1);
      expect(wire.writes.single.headers['Authorization'], 'Bearer token-A');
      expect(
        container.read(scanActionsProvider.notifier).workspace!.mediaId,
        isNull,
      );
    },
  );
  test('new workspace while upload waits retains old receipt without chaining HTTP', () async {
    final wire = _Wire()..hold = true;
    final disk = MemoryStore();
    final container = _setup(disk, wire);
    addTearDown(container.dispose);
    await container.read(scanActionsProvider.future);
    final actions = container.read(scanActionsProvider.notifier);
    final old = actions.workspace!.id;
    final pending = actions.upload('image/png', pixels);
    await wire.started.future;
    await actions.newWorkspace();
    final next = actions.workspace!.id;
    wire.released.complete();
    await expectLater(pending, throwsStateError);
    expect(wire.writes.length, 1);
    expect(actions.workspace!.id, next);
    expect(actions.workspace!.mediaId, isNull);
    expect(
      container.read(scanActionsProvider).requireValue!.workspace(old).mediaId,
      'scan-media',
    );
  });
}
