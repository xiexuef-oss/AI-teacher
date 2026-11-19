import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/diagnostic/diagnostic_actions.dart';
import 'package:tutor_student/features/diagnostic/diagnostic_store.dart';

import 'support/fake_backend.dart';

class DiagnosticTestAuth extends AuthController {
  @override
  Future<AuthSession> build() async =>
      const AuthSession(userId: 'alice', token: 'alice-token');
  void use(String id) =>
      state = AsyncData(AuthSession(userId: id, token: '$id-token'));
}

class DiagnosticWire implements ApiTransport {
  final fixtures = Fixtures.load();
  final requests = <Seen>[];
  final receipts = <String, RawResponse>{};
  Map<String, dynamic> cloud = {'revision': 0, 'run': null};
  bool offline = false, loseResponse = false, failReadAfterWrite = false;
  bool holdNextPost = false, readFailure = false;
  String? reject;
  void Function()? afterResponse;
  final started = Completer<void>(), released = Completer<void>();
  List<Seen> get posts => requests.where((r) => r.method == 'POST').toList();

  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    requests.add((method: method, uri: uri, headers: headers, body: body));
    if (offline) throw const SocketException('offline');
    if (method == 'GET') {
      if (uri.path.endsWith('/profile')) {
        return okResponse(
          fixtures.value('profile_saved')
            ..['user_id'] = 'alice'
            ..['revision'] = 1
            ..['subjects'] = ['math'],
        );
      }
      if (readFailure) throw const SocketException('read unavailable');
      return okResponse(
        headers['Authorization'] == 'Bearer bob-token'
            ? {'revision': 0, 'run': null}
            : cloud,
      );
    }
    final key = headers['Idempotency-Key']!;
    if (reject != null) return errorResponse(409, reject!);
    final result = receipts.putIfAbsent(key, () {
      final request = jsonDecode(body!) as Map;
      if (uri.path.endsWith('/diagnostics')) {
        cloud = fixtures.value('diagnostic_created');
        return okResponse(cloud, status: 201);
      }
      if (uri.path.endsWith('/session')) {
        cloud = jsonDecode(jsonEncode(cloud)) as Map<String, dynamic>;
        cloud['revision'] = request['expected_revision'] + 1;
        ((cloud['run']['items'] as List).first as Map)['session_id'] = fixtures
            .value('diagnostic_session')['id'];
        return okResponse(fixtures.value('diagnostic_session'));
      }
      cloud = jsonDecode(jsonEncode(cloud)) as Map<String, dynamic>;
      cloud['revision'] = request['expected_revision'] + 1;
      cloud['run']['status'] = 'abandoned';
      cloud['run']['abandoned_at'] = '2026-11-17T00:00:00Z';
      return okResponse(cloud);
    });
    if (holdNextPost) {
      holdNextPost = false;
      started.complete();
      await released.future;
    }
    afterResponse?.call();
    if (failReadAfterWrite) {
      failReadAfterWrite = false;
      readFailure = true;
    }
    if (loseResponse) {
      loseResponse = false;
      throw const SocketException('response lost after commit');
    }
    return result;
  }
}

ProviderContainer diagnosticContainer(
  MemoryStore disk,
  DiagnosticWire wire, {
  DiagnosticTestAuth? auth,
}) => ProviderContainer(
  retry: (_, _) => null,
  overrides: [
    authProvider.overrideWith(() => auth ?? DiagnosticTestAuth()),
    keyValueStoreProvider.overrideWithValue(disk),
    apiTransportProvider.overrideWithValue(wire),
  ],
);

void main() {
  test('lost response survives restart and replays original key/body without mount POST', () async {
    final disk = MemoryStore(), wire = DiagnosticWire()..loseResponse = true;
    var container = diagnosticContainer(disk, wire);
    await container.read(diagnosticActionsProvider.future);
    await container
        .read(diagnosticActionsProvider.notifier)
        .create(Subject.math);
    expect(wire.posts, hasLength(1));
    final first = wire.posts.single;
    expect(
      (await DiagnosticStore(disk, 'alice').read()).pending!.phase,
      'prepared',
    );
    container.dispose();
    container = diagnosticContainer(disk, wire);
    addTearDown(container.dispose);
    await container.read(diagnosticActionsProvider.future);
    expect(wire.posts, hasLength(1));
    await container.read(diagnosticActionsProvider.notifier).resume();
    expect(wire.posts, hasLength(2));
    expect(wire.posts.last.body, first.body);
    expect(
      wire.posts.last.headers['Idempotency-Key'],
      first.headers['Idempotency-Key'],
    );
    expect((await DiagnosticStore(disk, 'alice').read()).pending, isNull);
    expect(wire.receipts, hasLength(1));
  });

  test(
    'known receipt survives failed GET and resumes with no duplicate POST',
    () async {
      final disk = MemoryStore(),
          wire = DiagnosticWire()..failReadAfterWrite = true;
      final container = diagnosticContainer(disk, wire);
      addTearDown(container.dispose);
      await container.read(diagnosticActionsProvider.future);
      await container
          .read(diagnosticActionsProvider.notifier)
          .create(Subject.math);
      final originalPending = (await DiagnosticStore(
        disk,
        'alice',
      ).read()).pending;
      expect(originalPending, isNotNull);
      expect(originalPending!.phase, 'result_known');
      wire.readFailure = false;
      await container.read(diagnosticActionsProvider.notifier).resume();
      expect(wire.posts, hasLength(1));
      expect(
        (await DiagnosticStore(disk, 'alice').read()).commands.single.phase,
        'acked',
      );
    },
  );

  test('disk failure prevents all network writes', () async {
    final disk = MemoryStore(), wire = DiagnosticWire();
    final container = diagnosticContainer(disk, wire);
    addTearDown(container.dispose);
    await container.read(diagnosticActionsProvider.future);
    disk.failWrites = true;
    await container
        .read(diagnosticActionsProvider.notifier)
        .create(Subject.math);
    expect(wire.posts, isEmpty);
    expect((await DiagnosticStore(disk, 'alice').read()).pending, isNull);
  });

  test(
    'open session is navigable only after current plan confirms its binding',
    () async {
      final disk = MemoryStore(), wire = DiagnosticWire();
      final container = diagnosticContainer(disk, wire);
      addTearDown(container.dispose);
      await container.read(diagnosticActionsProvider.future);
      final actions = container.read(diagnosticActionsProvider.notifier);
      await actions.create(Subject.math);
      final run = wire.cloud['run']['id'] as String;
      final session = await actions.open(run, 1);
      expect(session!.id, wire.fixtures.value('diagnostic_session')['id']);
      expect(jsonDecode(wire.posts.last.body!)['expected_revision'], 1);
      expect((await DiagnosticStore(disk, 'alice').cloud())!.revision, 2);
    },
  );

  test(
    'business CAS conflict rejects original command without rebasing or retry',
    () async {
      final disk = MemoryStore(), wire = DiagnosticWire();
      final container = diagnosticContainer(disk, wire);
      addTearDown(container.dispose);
      await container.read(diagnosticActionsProvider.future);
      wire.reject = 'diagnostic_revision_conflict';
      await container
          .read(diagnosticActionsProvider.notifier)
          .create(Subject.math);
      final bundle = await DiagnosticStore(disk, 'alice').read();
      expect(bundle.commands.single.phase, 'rejected');
      expect(bundle.commands.single.body['expected_revision'], 0);
      await container.read(diagnosticActionsProvider.notifier).resume();
      expect(wire.posts, hasLength(1));
    },
  );

  test(
    'offline build reads owned cache and never invents fresh progress or POSTs',
    () async {
      final disk = MemoryStore(), wire = DiagnosticWire()..offline = true;
      await DiagnosticStore(disk, 'alice').rememberCloud(
        DiagnosticWorkspace.fromJson(wire.fixtures.value('diagnostic_created')),
      );
      final container = diagnosticContainer(disk, wire);
      addTearDown(container.dispose);
      final view = await container.read(diagnosticActionsProvider.future);
      expect(view.fresh, isFalse);
      expect(view.bundle.cloud!.revision, 1);
      await container
          .read(diagnosticActionsProvider.notifier)
          .create(Subject.math);
      expect(wire.posts, isEmpty);
    },
  );

  test(
    'late A response during B session stays in A history and cannot navigate',
    () async {
      final disk = MemoryStore(), wire = DiagnosticWire()..holdNextPost = true;
      final auth = DiagnosticTestAuth();
      final container = diagnosticContainer(disk, wire, auth: auth);
      addTearDown(container.dispose);
      await container.read(diagnosticActionsProvider.future);
      final sending = container
          .read(diagnosticActionsProvider.notifier)
          .create(Subject.math);
      await wire.started.future;
      auth.use('bob');
      await container.read(diagnosticActionsProvider.future);
      wire.released.complete();
      expect(await sending, isNull);
      expect(
        (await DiagnosticStore(disk, 'alice').read()).pending!.phase,
        'result_known',
      );
      expect((await DiagnosticStore(disk, 'bob').read()).commands, isEmpty);
      expect(
        container
            .read(diagnosticActionsProvider)
            .asData!
            .value
            .bundle
            .cloud!
            .run,
        isNull,
      );
      auth.use('alice');
      await container.read(diagnosticActionsProvider.future);
      expect(wire.posts, hasLength(1));
      await container.read(diagnosticActionsProvider.notifier).resume();
      expect(wire.posts, hasLength(1));
      expect((await DiagnosticStore(disk, 'alice').read()).pending, isNull);
    },
  );

  test('A to B to A does not reactivate a previous in-flight action', () async {
    final disk = MemoryStore(), wire = DiagnosticWire()..holdNextPost = true;
    final auth = DiagnosticTestAuth();
    final container = diagnosticContainer(disk, wire, auth: auth);
    addTearDown(container.dispose);
    await container.read(diagnosticActionsProvider.future);
    final sending = container
        .read(diagnosticActionsProvider.notifier)
        .create(Subject.math);
    await wire.started.future;
    auth.use('bob');
    await container.read(diagnosticActionsProvider.future);
    auth.use('alice');
    await container.read(diagnosticActionsProvider.future);
    wire.released.complete();
    expect(await sending, isNull);
    final originalPending = (await DiagnosticStore(
      disk,
      'alice',
    ).read()).pending;
    expect(originalPending, isNotNull);
    expect(originalPending!.phase, 'result_known');
    expect(wire.posts, hasLength(1));
    await container.read(diagnosticActionsProvider.notifier).resume();
    expect((await DiagnosticStore(disk, 'alice').read()).pending, isNull);
    expect(wire.posts, hasLength(1));
  });
}
