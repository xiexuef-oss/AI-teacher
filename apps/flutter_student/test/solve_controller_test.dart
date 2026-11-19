import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/solve/draft_store.dart';
import 'package:tutor_student/features/solve/solve_controller.dart';

import 'support/fake_backend.dart';

const _user = 'user-1';

class LostCreationBackend extends FakeBackend {
  String? losePath;
  Completer<void>? holdResponse;
  Completer<void>? responseEntered;
  void Function()? afterCreation;
  final receipts = <String, RawResponse>{};
  final creationWrites = <({String path, String key, String? body})>[];
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    if (method != 'POST' ||
        !(uri.path.endsWith('/sessions') || uri.path.endsWith('/attempts'))) {
      return super.send(method: method, uri: uri, headers: headers, body: body);
    }
    final key = headers['Idempotency-Key']!;
    creationWrites.add((path: uri.path, key: key, body: body));
    if (receipts.containsKey(key)) return receipts[key]!;
    final response = await super.send(
      method: method,
      uri: uri,
      headers: headers,
      body: body,
    );
    receipts[key] = response;
    afterCreation?.call();
    if (holdResponse != null) {
      if (!(responseEntered?.isCompleted ?? true)) responseEntered!.complete();
      await holdResponse!.future;
    }
    if (uri.path == losePath) {
      losePath = null;
      throw ApiException.network('successful creation response lost');
    }
    return response;
  }
}

class LostWriteBackend extends FakeBackend {
  String? loseSuffix;
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    final result = await super.send(
      method: method,
      uri: uri,
      headers: headers,
      body: body,
    );
    if (method != 'GET' &&
        loseSuffix != null &&
        uri.path.endsWith(loseSuffix!)) {
      loseSuffix = null;
      throw ApiException.network('write succeeded; receipt lost');
    }
    return result;
  }
}

class RefreshFailBackend extends FakeBackend {
  bool failRefresh = true;
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    final response = await super.send(
      method: method,
      uri: uri,
      headers: headers,
      body: body,
    );
    if (failRefresh && method == 'POST' && uri.path.endsWith('/next')) {
      failRefresh = false;
      failNextOn(r'/sessions/[^/]+$', 503, 'refresh_unavailable');
    }
    return response;
  }
}

class HeldSessionBackend extends FakeBackend {
  final entered = Completer<void>(), release = Completer<void>();
  late RawResponse terminal;
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    if (uri.path == '/api/v1/sessions/session-A') {
      entered.complete();
      await release.future;
      return terminal;
    }
    return super.send(method: method, uri: uri, headers: headers, body: body);
  }
}

class WorkspaceHeldBackend extends FakeBackend {
  String? heldPath, secondHeldPath;
  final entered = Completer<void>(), release = Completer<void>();
  final secondEntered = Completer<void>(), secondRelease = Completer<void>();
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    final response = await super.send(
      method: method,
      uri: uri,
      headers: headers,
      body: body,
    );
    if (uri.path == heldPath) {
      entered.complete();
      await release.future;
    }
    if (uri.path == secondHeldPath) {
      secondEntered.complete();
      await secondRelease.future;
    }
    return response;
  }
}

void installFreshWorkspace(
  Harness h, {
  String questionFixture = 'question_single_choice',
}) {
  final session = h.backend.fixtures.value('session_created')
    ..['id'] = 'new-session'
    ..['question_id'] = h.questionId
    ..['origin'] = h.origin
    ..['review_item_id'] = h.reviewItemId;
  final attempt = h.backend.fixtures.value('attempt_created')
    ..['id'] = 'new-attempt'
    ..['session_id'] = 'new-session';
  h.backend.onFixture('GET', '/questions/[^/]+', questionFixture);
  h.backend.on('POST', '/sessions', (_) => okResponse(session, status: 201));
  h.backend.on('GET', '/sessions/new-session', (_) => okResponse(session));
  h.backend.on('POST', '/attempts', (_) => okResponse(attempt, status: 201));
  h.backend.on('GET', '/attempts/new-attempt', (_) => okResponse(attempt));
}

class DelayedCopyBackend extends FakeBackend {
  final entered = Completer<void>();
  final release = Completer<void>();
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    final result = await super.send(
      method: method,
      uri: uri,
      headers: headers,
      body: body,
    );
    if (uri.path.endsWith('/copies')) {
      if (!entered.isCompleted) entered.complete();
      await release.future;
    }
    return result;
  }
}

class DelayedRecoveryStore extends MemoryStore {
  Completer<void>? block;
  Completer<void>? entered;
  @override
  Future<void> write(String key, String value) async {
    if (key.contains('/draft-recovery/') && block != null) {
      entered?.complete();
      entered = null;
      await block!.future;
    }
    await super.write(key, value);
  }
}

/// 控制器用真实的短定时器（几十毫秒），测试里轮询等待条件成立。
Future<void> until(
  bool Function() condition, {
  String reason = '条件没有在 3 秒内成立',
}) async {
  final deadline = DateTime.now().add(const Duration(seconds: 3));
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) fail(reason);
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
}

class Harness {
  Harness({
    String? questionId,
    this.origin = 'practice',
    this.reviewItemId,
    MemoryStore? store,
    FakeBackend? backend,
    this.autosaveDelay = const Duration(milliseconds: 15),
  }) : store = store ?? MemoryStore(),
       backend = backend ?? FakeBackend(),
       questionId =
           questionId ??
           Fixtures.load().value('question_single_choice')['id'] as String {
    if (backend == null) this.backend.installLearningFlow();
    core = ApiCore(
      baseUrl: 'http://127.0.0.1:8000',
      transport: this.backend,
      tokenProvider: () => 'tok',
    );
  }

  final MemoryStore store;
  final FakeBackend backend;
  final String questionId;
  final String origin;
  final String? reviewItemId;
  final Duration autosaveDelay;
  late final ApiCore core;
  int unauthenticated = 0;
  final List<SolveController> created = [];

  SolveController controller({String? sessionId, String? attemptId}) {
    final c = SolveController(
      api: TutorApiClient(core),
      store: store,
      userId: _user,
      args: SolveArgs(
        questionId: questionId,
        origin: origin,
        reviewItemId: reviewItemId,
        sessionId: sessionId,
        attemptId: attemptId,
      ),
      onUnauthenticated: () => unauthenticated += 1,
      autosaveDelay: autosaveDelay,
      syncDelay: const Duration(milliseconds: 40),
      retryDelay: const Duration(milliseconds: 80),
    );
    created.add(c);
    return c;
  }

  void dispose() {
    for (final c in created) {
      c.dispose();
    }
  }
}

Future<SolveController> started(Harness h) async {
  final c = h.controller();
  await c.start();
  return c;
}

Future<void> trustedOfflineWorkspace(Harness h) async {
  final root = DraftStore(h.store, _user);
  final id = await root.readOrCreateLocalId(h.questionId);
  final local = root.forLocal(id);
  await local.claimScope(h.questionId);
  final question = Question.fromJson(
    h.backend.fixtures.value('question_single_choice'),
  );
  await local.saveWorkspaceContext(
    h.questionId,
    DraftWorkspaceContext(
      workspaceId: id,
      question: question,
      sessionBody: SessionCreate(
        questionId: h.questionId,
        origin: SessionOrigin.practice,
        expectedQuestionVersion: question.version,
      ).toJson(),
    ),
  );
}

void main() {
  late Harness h;

  setUp(() {
    h = Harness();
    h.backend.on(
      'GET',
      '/attempts/(server-copy|replayed-copy|lost-response-copy|independent-copy)',
      (request) => okResponse({
        ...h.backend.fixtures.value('attempt_created'),
        'id': request.uri.path.split('/').last,
        'draft_revision': 1,
      }),
    );
  });
  tearDown(() => h.dispose());
  test('creation authentication pause resumes the original command only for its owner', () async {
    h.backend.failNextOn('/sessions', 401, 'unauthenticated');
    final c = await started(h);
    expect(c.canResumeCreation, isTrue);
    final before = h.backend.requests
        .where((r) => r.uri.path.endsWith('/sessions') && r.method == 'POST')
        .single;
    await c.resumeAuthenticatedCreation();
    expect(c.attempt, isNotNull);
    expect(c.creationBlockedReason, isNull);
    final after = h.backend.requests
        .where((r) => r.uri.path.endsWith('/sessions') && r.method == 'POST')
        .last;
    expect(after.body, before.body);
    expect(after.headers['Idempotency-Key'], before.headers['Idempotency-Key']);
  });
  test('an identity change during creation never sends the next stage using a new identity', () async {
    final backend = LostCreationBackend()..installLearningFlow();
    h = Harness(backend: backend);
    var current = true;
    backend.afterCreation = () => current = false;
    final c = SolveController(
      api: TutorApiClient(h.core),
      store: h.store,
      userId: _user,
      args: SolveArgs(questionId: h.questionId),
      isCurrentUser: () => current,
    );
    h.created.add(c);
    await c.start();
    expect(backend.sessionsCreated, 1);
    expect(backend.attemptsCreated, 0);
    expect(
      (await c.drafts.readCreation(h.questionId))!.phase,
      'session_prepared',
    );
    c.dispose();
    backend.afterCreation = null;
    final sameOwner = await started(h);
    expect(sameOwner.attempt, isNotNull);
    expect(backend.sessionsCreated, 1);
  });
  for (final missing in [true, false]) {
    test(
      'late ${missing ? '404' : 'DONE'} for A cannot clear the selected C workspace',
      () async {
        final backend = HeldSessionBackend()..installLearningFlow();
        h = Harness(backend: backend);
        final fixture = backend.fixtures.value('session_created');
        backend.terminal = missing
            ? errorResponse(404, 'not_found')
            : okResponse({
                ...fixture,
                'id': 'session-A',
                'origin': 'practice',
                'state': 'DONE',
              });
        await DraftStore(h.store, _user).writeActive(
          h.questionId,
          const ActiveRef(sessionId: 'session-A', attemptId: 'attempt-A'),
        );
        final a = h.controller();
        final starting = a.start();
        await backend.entered.future;
        backend.on(
          'GET',
          '/sessions/session-C',
          (_) => okResponse({
            ...fixture,
            'id': 'session-C',
            'origin': 'practice',
            'active_attempt_id': 'attempt-C',
          }),
        );
        backend.on(
          'GET',
          '/attempts/attempt-C',
          (_) => okResponse({
            ...backend.fixtures.value('attempt_created'),
            'id': 'attempt-C',
            'session_id': 'session-C',
          }),
        );
        await DraftStore(h.store, _user).writeActive(
          h.questionId,
          const ActiveRef(sessionId: 'session-C', attemptId: 'attempt-C'),
        );
        final c = h.controller(sessionId: 'session-C', attemptId: 'attempt-C');
        await c.start();
        backend.release.complete();
        await starting;
        expect(
          (await DraftStore(h.store, _user).readActive(h.questionId))
              ?.attemptId,
          'attempt-C',
        );
        expect(backend.sessionsCreated, 0);
      },
    );
  }
  test(
    'new workspace forgets explicit cloud route after blocked retry',
    () async {
      h.backend.sessionOrigin = 'practice';
      final fixture = h.backend.fixtures;
      final oldSession = fixture.value('session_created')['id'] as String;
      final oldAttempt = fixture.value('attempt_created')['id'] as String;
      final c = h.controller(sessionId: oldSession, attemptId: oldAttempt);
      await c.start();
      expect(c.attempt!.id, oldAttempt);
      c.selectOption('C');
      await c.submit();
      h.backend.failNextOn(r'/attempts$', 409, 'attempt_in_progress');
      await c.retry();
      expect(c.creationBlockedReason, isNotNull);
      installFreshWorkspace(h);
      final oldGets = h.backend
          .requestsTo(
            'GET',
            '/sessions/$oldSession'
                r'$',
          )
          .length;
      await c.openLatestWorkspace();
      expect(c.phase, SolvePhase.answering);
      expect(c.session!.id, 'new-session');
      expect(c.attempt!.id, 'new-attempt');
      expect(c.selected, isEmpty);
      expect(c.creationBlockedReason, isNull);
      expect(
        h.backend
            .requestsTo(
              'GET',
              '/sessions/$oldSession'
                  r'$',
            )
            .length,
        oldGets,
      );
    },
  );

  test(
    'new workspace clears old solution result self check and review display',
    () async {
      final backend = FakeBackend()
        ..submitFixture = 'submit_written'
        ..installLearningFlow(questionFixture: 'question_written');
      h = Harness(
        backend: backend,
        origin: 'review',
        reviewItemId: 'review-one',
        questionId: backend.fixtures.value('question_written')['id'] as String,
      );
      final c = await started(h);
      c.setPart('1', 'old work');
      await c.submit();
      expect(c.selfCheck, isNotNull);
      c.markPoint(c.selfCheck!.points.first.key, SelfCheckLevel.done);
      await c.tutor(
        TutorActionType.requestStandard,
        confirmEndIndependent: true,
      );
      expect(c.events, isNotEmpty);
      expect(c.evaluation, isNotNull);
      expect(c.reviewCompletion, isNull, reason: 'pending主观题不能完成复测');
      expect(c.reviewError, isNotNull);
      expect(c.marks, isNotEmpty);
      installFreshWorkspace(h, questionFixture: 'question_written');
      await c.openLatestWorkspace();
      expect(c.session!.id, 'new-session');
      expect(c.phase, SolvePhase.answering);
      expect(c.session!.usedSolution, isFalse);
      expect(c.events, isEmpty);
      expect(c.evaluation, isNull);
      expect(c.reviewItem, isNull);
      expect(c.reviewCompletion, isNull);
      expect(c.reviewError, isNull);
      expect(c.selfCheck, isNull);
      expect(c.marks, isEmpty);
      expect(c.selfCheckBusy, isFalse);
      expect(c.selfCheckError, isNull);
      expect(c.actionError, isNull);
      expect(c.failure, isNull);
      expect(c.sync, SaveStatus.saved);
      expect(c.parts, isEmpty);
    },
  );

  test('old tutor response cannot repopulate a new workspace', () async {
    final backend = WorkspaceHeldBackend()..installLearningFlow();
    h = Harness(backend: backend);
    final c = await started(h);
    final oldId = c.session!.id;
    backend.heldPath = '/api/v1/tutor/sessions/$oldId/next';
    final tutoring = c.tutor(
      TutorActionType.requestStandard,
      confirmEndIndependent: true,
    );
    await backend.entered.future;
    installFreshWorkspace(h);
    await c.openLatestWorkspace();
    expect(c.session!.id, 'new-session');
    expect(c.events, isEmpty);
    backend.secondHeldPath = '/api/v1/tutor/sessions/new-session/next';
    backend.on(
      'POST',
      '/tutor/sessions/new-session/next',
      (_) => okResponse({
        ...backend.fixtures.value('tutor_hint'),
        'session': c.session!.toJson(),
      }),
    );
    final newTutoring = c.tutor(TutorActionType.requestHint);
    await backend.secondEntered.future;
    expect(c.tutorBusy, isTrue);
    backend.release.complete();
    await tutoring;
    expect(
      c.tutorBusy,
      isTrue,
      reason: 'old finally cannot clear a new action',
    );
    expect(c.session!.id, 'new-session');
    expect(c.events, isEmpty);
    expect(c.session!.usedSolution, isFalse);
    expect(c.actionError, isNull);
    backend.secondRelease.complete();
    await newTutoring;
    expect(c.tutorBusy, isFalse);
  });

  test(
    'old tutor authentication error cannot expire a new workspace',
    () async {
      final backend = WorkspaceHeldBackend()..installLearningFlow();
      h = Harness(backend: backend);
      final c = await started(h);
      backend.heldPath = '/api/v1/tutor/sessions/${c.session!.id}/next';
      backend.failNextOn(backend.heldPath!, 401, 'token_expired');
      final oldAction = c.tutor(TutorActionType.requestHint);
      await backend.entered.future;
      installFreshWorkspace(h);
      await c.openLatestWorkspace();
      backend.release.complete();
      await oldAction;
      expect(c.session!.id, 'new-session');
      expect(c.authExpired, isFalse);
      expect(c.actionError, isNull);
      expect(c.tutorBusy, isFalse);
      expect(h.unauthenticated, 0);
    },
  );

  for (final save in [false, true]) {
    test(
      'old self check result cannot populate a new workspace save=$save',
      () async {
        final backend = WorkspaceHeldBackend()
          ..submitFixture = 'submit_written'
          ..installLearningFlow(questionFixture: 'question_written');
        h = Harness(
          backend: backend,
          questionId:
              backend.fixtures.value('question_written')['id'] as String,
        );
        final c = await started(h);
        c.setPart('1', 'old answer');
        await c.submit();
        for (final point in c.selfCheck!.points) {
          c.markPoint(point.key, SelfCheckLevel.done);
        }
        backend.heldPath = '/api/v1/attempts/${c.attempt!.id}/self-check';
        final operation = save ? c.saveSelfCheck() : c.loadSelfCheck();
        await backend.entered.future;
        installFreshWorkspace(h, questionFixture: 'question_written');
        await c.openLatestWorkspace();
        expect(c.selfCheck, isNull);
        expect(c.marks, isEmpty);
        backend.release.complete();
        await operation;
        expect(c.session!.id, 'new-session');
        expect(c.selfCheck, isNull);
        expect(c.marks, isEmpty);
        expect(c.selfCheckBusy, isFalse);
        expect(c.selfCheckError, isNull);
      },
    );
  }

  test(
    'new workspace does not reuse failed tutor key or stale error',
    () async {
      final c = await started(h);
      final oldId = c.session!.id;
      h.backend.failNextOn('/tutor/sessions/$oldId/next', 503, 'temporary');
      await c.tutor(TutorActionType.requestHint);
      final oldKey = h.backend
          .requestsTo('POST', '/tutor/sessions/$oldId/next')
          .last
          .headers['Idempotency-Key'];
      expect(c.actionError, isNotNull);
      installFreshWorkspace(h);
      await c.openLatestWorkspace();
      expect(c.actionError, isNull);
      h.backend.on(
        'POST',
        '/tutor/sessions/new-session/next',
        (_) => okResponse({
          ...h.backend.fixtures.value('tutor_hint'),
          'session': c.session!.toJson(),
        }),
      );
      await c.tutor(TutorActionType.requestHint);
      final newKey = h.backend
          .requestsTo('POST', '/tutor/sessions/new-session/next')
          .last
          .headers['Idempotency-Key'];
      expect(newKey, isNot(oldKey));
    },
  );

  test('an old unbound draft without verified origin is blocked and can explicitly open a blank latest workspace', () async {
    final root = DraftStore(h.store, _user);
    final old = LocalDraft(
      questionId: h.questionId,
      selected: const ['C'],
      savedAt: DateTime.now(),
    );
    await root.writeDraft(old);
    await root.writeQuestion(
      Question.fromJson(h.backend.fixtures.value('question_single_choice')),
    );
    final raw = h.store.data['u/$_user/draft/${h.questionId}'];
    final c = await started(h);
    expect(c.creationBlockedReason, isNotNull);
    expect(c.selected, {'C'});
    expect(c.canSubmit, isFalse);
    expect(h.backend.sessionsCreated, 0);
    expect(h.store.data['u/$_user/draft/${h.questionId}'], raw);
    final source = c.drafts;
    final latest = h.backend.fixtures.value('question_single_choice')
      ..['version'] = 2;
    final session = h.backend.fixtures.value('session_created')
      ..['question_version'] = 2;
    h.backend.on('GET', '/questions/[^/]+', (_) => okResponse(latest));
    h.backend.on('POST', '/sessions', (_) => okResponse(session, status: 201));
    h.backend.on('GET', '/sessions/[^/]+', (_) => okResponse(session));
    await c.openLatestWorkspace();
    expect(c.phase, SolvePhase.answering);
    expect(c.question!.version, 2);
    expect(c.selected, isEmpty);
    expect((await source.readDraft(h.questionId))!.selected, ['C']);
    expect(h.store.data['u/$_user/draft/${h.questionId}'], raw);
  });
  test(
    'late creation for A cannot replace an explicitly selected C workspace',
    () async {
      final backend = LostCreationBackend()
        ..installLearningFlow()
        ..holdResponse = Completer<void>()
        ..responseEntered = Completer<void>();
      h = Harness(backend: backend);
      final a = h.controller();
      final starting = a.start();
      await backend.responseEntered!.future;
      final session = {
        ...backend.fixtures.value('session_created'),
        'id': 'session-C',
        'origin': 'practice',
        'active_attempt_id': 'attempt-C',
      };
      backend.on('GET', '/sessions/session-C', (_) => okResponse(session));
      backend.on(
        'GET',
        '/attempts/attempt-C',
        (_) => okResponse({
          ...backend.fixtures.value('attempt_created'),
          'id': 'attempt-C',
          'session_id': 'session-C',
        }),
      );
      await DraftStore(h.store, _user).writeActive(
        h.questionId,
        const ActiveRef(sessionId: 'session-C', attemptId: 'attempt-C'),
      );
      final c = h.controller(sessionId: 'session-C', attemptId: 'attempt-C');
      await c.start();
      backend.holdResponse!.complete();
      await starting;
      expect(
        (await DraftStore(h.store, _user).readActive(h.questionId))!.attemptId,
        'attempt-C',
      );
      expect(a.attempt, isNull);
      expect(c.attempt!.id, 'attempt-C');
    },
  );
  test('retry response loss replays one fresh attempt without copying submitted input', () async {
    final backend = LostCreationBackend()..installLearningFlow();
    h = Harness(backend: backend);
    final c = await started(h);
    c.selectOption('A');
    await c.submit();
    backend.losePath = '/api/v1/attempts';
    await c.retry();
    c.dispose();
    final reopened = await started(h);
    expect(reopened.phase, SolvePhase.answering);
    expect(reopened.selected, isEmpty);
    expect(backend.sessionsCreated, 1);
    expect(backend.attemptsCreated, 2);
    final writes = backend.creationWrites
        .where((w) => w.path.endsWith('/attempts'))
        .toList();
    expect(writes, hasLength(3));
    expect(writes[1].key, writes[2].key);
    expect(writes[1].body, writes[2].body);
  });
  test('a creation response whose result cannot be saved is replayed after restart', () async {
    final backend = LostCreationBackend()..installLearningFlow();
    h = Harness(backend: backend);
    backend.afterCreation = () => h.store.failWrites = true;
    final c = await started(h);
    expect(c.localSaveFailed, isTrue);
    c.dispose();
    h.store.failWrites = false;
    backend.afterCreation = null;
    final reopened = await started(h);
    expect(reopened.attempt, isNotNull);
    expect(backend.sessionsCreated, 1);
    expect(backend.attemptsCreated, 1);
    final writes = backend.creationWrites
        .where((w) => w.path.endsWith('/sessions'))
        .toList();
    expect(writes[0].key, writes[1].key);
    expect(writes[0].body, writes[1].body);
  });
  for (final stage in ['sessions', 'attempts']) {
    test(
      'creation $stage response loss replays its durable body and key after reopen',
      () async {
        final backend = LostCreationBackend()
          ..installLearningFlow()
          ..losePath = '/api/v1/$stage';
        h = Harness(backend: backend);
        final c = await started(h);
        c.dispose();
        final reopened = await started(h);
        expect(reopened.phase, SolvePhase.answering);
        expect(backend.sessionsCreated, 1);
        expect(backend.attemptsCreated, 1);
        final attempts = backend.creationWrites
            .where((w) => w.path.endsWith('/$stage'))
            .toList();
        expect(attempts, hasLength(2));
        expect(attempts[1].key, attempts[0].key);
        expect(attempts[1].body, attempts[0].body);
      },
    );
  }
  test(
    'unbound v1 input keeps its source question after v2 is published',
    () async {
      h.backend.failNextOn('/sessions', 503, 'temporarily_unavailable');
      final c = await started(h);
      final version = c.question!.version;
      h.backend.offline = true;
      c.selectOption('C');
      await c.flushNow();
      c.dispose();
      h.backend.offline = false;
      final updated = h.backend.fixtures.value('question_single_choice')
        ..['version'] = version + 1;
      h.backend.on('GET', '/questions/[^/]+', (_) => okResponse(updated));
      h.backend.on(
        'POST',
        '/sessions',
        (_) => errorResponse(409, 'question_version_conflict'),
      );
      final reopened = await started(h);
      expect(reopened.question!.version, version);
      expect(reopened.selected, {'C'});
      expect(
        h.backend.requests.where(
          (r) => r.method == 'PUT' && r.uri.path.endsWith('/draft'),
        ),
        isEmpty,
      );
    },
  );

  test('resume honors the exact locally selected attempt rather than session default', () async {
    h.backend.sessionOrigin = 'practice';
    final session = h.backend.fixtures.value('session_created');
    final original = h.backend.fixtures.value('attempt_created');
    final chosen = {
      ...original,
      'id': 'selected-copy',
      'session_id': session['id'],
    };
    await DraftStore(h.store, _user).writeActive(
      h.questionId,
      ActiveRef(sessionId: session['id'] as String, attemptId: 'selected-copy'),
    );
    h.backend.on('GET', '/attempts/selected-copy', (_) => okResponse(chosen));
    final c = await started(h);
    expect(c.attempt!.id, 'selected-copy');
  });
  test(
    'restoring an existing session loads its pinned question version',
    () async {
      h.backend.sessionOrigin = 'practice';
      final session = h.backend.fixtures.value('session_created');
      final original = h.backend.fixtures.value('attempt_created');
      await DraftStore(h.store, _user).writeActive(
        h.questionId,
        ActiveRef(
          sessionId: session['id'] as String,
          attemptId: original['id'] as String,
        ),
      );
      h.backend.on(
        'GET',
        '/questions/[^/]+',
        (_) => errorResponse(404, 'question_unavailable'),
      );
      h.backend.onFixture(
        'GET',
        '/sessions/[^/]+/question',
        'question_single_choice',
      );
      final c = await started(h);
      expect(c.phase, SolvePhase.answering);
      expect(
        h.backend.requests.any((r) => r.uri.path.endsWith('/question')),
        isTrue,
      );
    },
  );

  group('303B resource write recovery', () {
    test('explicit server observed first C can record through draft B without inventing a submit ACK', () async {
      final backend = FakeBackend()
        ..installLearningFlow()
        ..submitFixture = 'submit_correct';
      final local = Harness(
        backend: backend,
        origin: 'review',
        reviewItemId: 'review-item-1',
      );
      addTearDown(local.dispose);
      final c = await started(local);
      final firstId = c.attempt!.id;
      await c.api.submitAttempt(
        attemptId: firstId,
        body: const SubmitRequest(
          answer: AnswerPayload(selectedOptions: ['B']),
        ),
        idempotencyKey: 'other-device-submit-1',
      );
      c.dispose();
      final restored = await started(local);
      await restored.retry();
      restored.selectOption('C');
      await restored.flushNow();
      expect(restored.attempt!.status, AttemptStatus.draft);
      await restored.recordSubmittedReview(explicitConfirmation: false);
      expect(backend.reviewHistory, isEmpty);
      await restored.recordSubmittedReview(explicitConfirmation: true);
      expect(
        restored.reviewCompletion?.result,
        ReviewResult.passed,
        reason: restored.reviewError?.toString(),
      );
      expect(backend.reviewState('review-item-1')['stage'], 1);
      expect(backend.reviewState('review-item-1')['last_attempt_id'], firstId);
      expect(restored.selected, {'C'});
      expect(
        await restored.drafts.findConfirmedFirstSubmission(
          local.questionId,
          restored.session!.id,
        ),
        isNull,
      );
      expect(backend.requestsTo('POST', r'/submit$').length, 1);
      expect(
        backend.bodyOf(
          backend.requestsTo('POST', r'/complete$').single,
        )!['attempt_id'],
        restored.attempt!.id,
      );
    });

    test('observed verified failure is legal and a business duplicate never becomes success', () async {
      final backend = FakeBackend()
        ..installLearningFlow()
        ..submitFixture = 'submit_incorrect';
      final local = Harness(
        backend: backend,
        origin: 'review',
        reviewItemId: 'review-item-1',
      );
      addTearDown(local.dispose);
      final c = await started(local);
      final firstId = c.attempt!.id;
      await c.api.submitAttempt(
        attemptId: firstId,
        body: const SubmitRequest(
          answer: AnswerPayload(selectedOptions: ['A']),
        ),
        idempotencyKey: 'other-device-failed-submit',
      );
      c.dispose();
      final restored = await started(local);
      await restored.recordSubmittedReview(explicitConfirmation: true);
      expect(
        restored.reviewCompletion?.result,
        ReviewResult.failed,
        reason: restored.reviewError?.toString(),
      );
      expect(backend.reviewState('review-item-1')['stage'], 0);
      await restored.recordSubmittedReview(explicitConfirmation: true);
      expect(restored.reviewCompletion, isNull);
      expect(
        restored.reviewError.toString(),
        contains('review_already_completed'),
      );
      expect(backend.reviewHistory.length, 1);
      expect(backend.sessionsCreated, 1);
      expect(backend.attemptsCreated, 1);
      expect(restored.reviewState!.stage, 0);
    });

    test(
      'unknown local submit cannot silently become a server observed review',
      () async {
        final backend = LostWriteBackend()
          ..installLearningFlow()
          ..submitFixture = 'submit_correct';
        final local = Harness(
          backend: backend,
          origin: 'review',
          reviewItemId: 'review-item-1',
        );
        addTearDown(local.dispose);
        final c = await started(local);
        c.selectOption('B');
        backend.loseSuffix = '/submit';
        await c.submit();
        expect(c.needsSubmissionRecovery, isTrue);
        await c.recordSubmittedReview(explicitConfirmation: true);
        expect(backend.requestsTo('POST', r'/complete$'), isEmpty);
        expect(backend.reviewHistory, isEmpty);
        expect(c.needsSubmissionRecovery, isTrue);
      },
    );

    test(
      'two views share one session command and late A cannot replace active B',
      () async {
        final backend = WorkspaceHeldBackend()..installLearningFlow();
        final local = Harness(backend: backend);
        addTearDown(local.dispose);
        final a = await started(local);
        backend.heldPath = '/api/v1/tutor/sessions/${a.session!.id}/next';
        final first = a.tutor(TutorActionType.requestHint);
        await backend.entered.future;
        final b = await started(local);
        final recovery = b.recoverTutor();
        backend.heldPath = null;
        backend.release.complete();
        await first;
        await recovery;
        expect(backend.requestsTo('POST', r'/next$').length, 1);
        expect(backend.hintsRevealed, 1);
        expect(b.needsTutorRecovery, isFalse);
        expect(b.session!.hintLevelRevealed, 1);
        expect(b.events.length, 1);
        expect(
          a.events,
          isEmpty,
          reason: 'old scope lease cannot repaint A after B became active',
        );
      },
    );

    test('two review views resolve one resource action without another POST or stale pending banner', () async {
      final backend = WorkspaceHeldBackend()
        ..installLearningFlow()
        ..submitFixture = 'submit_correct';
      final local = Harness(
        backend: backend,
        origin: 'review',
        reviewItemId: 'review-item-1',
      );
      addTearDown(local.dispose);
      final a = await started(local);
      backend.heldPath = '/api/v1/reviews/review-item-1/complete';
      a.selectOption('B');
      final first = a.submit();
      await backend.entered.future;
      final b = await started(local);
      final recovery = b.recoverReviewCompletion();
      backend.heldPath = null;
      backend.release.complete();
      await first;
      await recovery;
      expect(backend.requestsTo('POST', r'/complete$').length, 1);
      expect(backend.reviewState('review-item-1')['stage'], 1);
      expect(b.needsReviewRecovery, isFalse);
      expect(b.reviewState!.stage, 1);
      expect(b.reviewCompletion!.result, ReviewResult.passed);
    });

    test('later submission B never automatically records first C again or calls its result B', () async {
      final backend = FakeBackend()
        ..installLearningFlow()
        ..submitFixture = 'submit_correct';
      final local = Harness(
        backend: backend,
        origin: 'review',
        reviewItemId: 'review-item-1',
      );
      addTearDown(local.dispose);
      final c = await started(local);
      c.selectOption('B');
      await c.submit();
      final firstId = c.attempt!.id;
      expect(c.reviewCompletion!.result, ReviewResult.passed);
      await c.retry();
      c.selectOption('A');
      await c.submit();
      expect(c.attempt!.submissionNo, 2);
      expect(backend.requestsTo('POST', r'/complete$').length, 1);
      expect(backend.reviewHistory.length, 1);
      expect(
        c.reviewCompletion,
        isNull,
        reason: 'C completion must not describe the later B attempt',
      );
      expect(c.historicalReviewCompletion!.result, ReviewResult.passed);
      expect(backend.reviewState('review-item-1')['last_attempt_id'], firstId);
      expect(backend.reviewState('review-item-1')['stage'], 1);
    });

    test('explicit submitted route restores only matching pending review without reopening it for edits', () async {
      final backend = LostWriteBackend()
        ..installLearningFlow()
        ..submitFixture = 'submit_correct';
      final local = Harness(
        backend: backend,
        origin: 'review',
        reviewItemId: 'review-item-1',
      );
      addTearDown(local.dispose);
      final c = await started(local);
      final sessionId = c.session!.id;
      final attemptId = c.attempt!.id;
      c.selectOption('B');
      backend.loseSuffix = '/complete';
      await c.submit();
      expect(backend.reviewState('review-item-1')['stage'], 1);
      final original = backend.requestsTo('POST', r'/complete$').single;
      final rawBefore = local.store.data.entries
          .where((e) => e.key.contains('resource-journal/review/'))
          .map((e) => e.value)
          .single;
      c.dispose();
      final restored = local.controller(
        sessionId: sessionId,
        attemptId: attemptId,
      );
      await restored.start();
      expect(
        restored.phase,
        SolvePhase.submitted,
        reason: restored.actionError?.toString(),
      );
      expect(restored.needsReviewRecovery, isTrue);
      expect(restored.canSubmit, isFalse);
      expect(restored.localSaveFailed, isFalse);
      final rawAfter = local.store.data.entries
          .where((e) => e.key.contains('resource-journal/review/'))
          .map((e) => e.value)
          .single;
      expect(
        rawAfter,
        rawBefore,
        reason:
            'initialization only reads the original pending resource command',
      );
      expect(backend.requestsTo('POST', r'/complete$').length, 1);
      await restored.recoverReviewCompletion();
      final retry = backend.requestsTo('POST', r'/complete$').last;
      expect(
        retry.headers['Idempotency-Key'],
        original.headers['Idempotency-Key'],
      );
      expect(retry.body, original.body);
      expect(backend.reviewState('review-item-1')['stage'], 1);
      expect(restored.needsReviewRecovery, isFalse);
    });

    test('explicit submitted selection without ACK or pending resource cannot submit or mutate a journal', () async {
      final backend = FakeBackend()
        ..installLearningFlow()
        ..submitFixture = 'submit_correct';
      final local = Harness(
        backend: backend,
        origin: 'review',
        reviewItemId: 'review-item-1',
      );
      addTearDown(local.dispose);
      final c = await started(local);
      final sessionId = c.session!.id;
      final attemptId = c.attempt!.id;
      c.selectOption('A');
      await c.flushNow();
      await c.api.submitAttempt(
        attemptId: attemptId,
        body: const SubmitRequest(
          answer: AnswerPayload(selectedOptions: ['B']),
        ),
        idempotencyKey: 'foreign-device-unacknowledged-submit',
      );
      c.dispose();
      final before = Map.of(local.store.data);
      final restored = local.controller(
        sessionId: sessionId,
        attemptId: attemptId,
      );
      await restored.start();
      expect(restored.phase, isNot(SolvePhase.submitted));
      expect(
        restored.selected,
        {'A'},
        reason: 'local original is retained without guessing it was submitted',
      );
      expect(restored.canSubmit, isFalse);
      expect(restored.needsReviewRecovery, isFalse);
      final posts = backend.requests.where((r) => r.method != 'GET').length;
      await restored.submit();
      await restored.retryNow();
      expect(backend.requests.where((r) => r.method != 'GET').length, posts);
      expect(
        await restored.drafts.readWrite(local.questionId, 'submit'),
        isNull,
      );
      expect(
        local.store.data.entries.where(
          (e) => e.key.contains('resource-journal'),
        ),
        isEmpty,
      );
      expect(before.keys.where((k) => k.contains('resource-journal')), isEmpty);
    });

    test('terminal tutor refresh reads actual submitted C and preserves local B without its feedback', () async {
      final backend = WorkspaceHeldBackend()
        ..installLearningFlow()
        ..submitFixture = 'submit_correct';
      final local = Harness(backend: backend);
      addTearDown(local.dispose);
      final c = await started(local);
      final id = c.attempt!.id;
      final sid = c.session!.id;
      c.selectOption('A');
      await c.flushNow();
      backend.heldPath = '/api/v1/tutor/sessions/$sid/next';
      final hint = c.tutor(TutorActionType.requestHint);
      await backend.entered.future;
      await c.api.submitAttempt(
        attemptId: id,
        body: const SubmitRequest(
          answer: AnswerPayload(selectedOptions: ['B']),
        ),
        idempotencyKey: 'remote-real-submit-C',
      );
      c.selectOption('C');
      await c.flushNow();
      backend.heldPath = null;
      await c.api.tutorNext(
        sessionId: sid,
        body: const TutorAction(
          action: TutorActionType.requestStandard,
          confirmEndIndependent: true,
        ),
        idempotencyKey: 'remote-real-standard',
      );
      await c.api.tutorNext(
        sessionId: sid,
        body: const TutorAction(action: TutorActionType.markUnderstood),
        idempotencyKey: 'remote-real-understood',
      );
      expect((await c.api.getSession(sessionId: sid)).state, SessionState.done);
      backend.release.complete();
      await hint;
      expect(c.phase, isNot(SolvePhase.answering));
      expect(c.attempt!.status, AttemptStatus.submitted);
      expect(c.isFinished, isTrue);
      expect(c.canSubmit, isFalse);
      expect(c.assistanceAllowed, isFalse);
      expect(c.selected, {'C'});
      expect((await c.drafts.readDraft(local.questionId))!.selected, ['C']);
      expect(
        c.evaluation,
        isNull,
        reason: 'remote C feedback must not explain local B',
      );
      expect(await c.drafts.readWrite(local.questionId, 'submit'), isNull);
      final writes = backend.requests.where((r) => r.method != 'GET').length;
      await c.submit();
      expect(
        await c.tutor(TutorActionType.requestHint),
        TutorOutcome.notAllowed,
      );
      await c.retry();
      expect(backend.requests.where((r) => r.method != 'GET').length, writes);
      c.dispose();
      final reopened = await started(local);
      expect(reopened.phase, isNot(SolvePhase.answering));
      expect(reopened.selected, {'C'});
      expect(reopened.evaluation, isNull);
    });

    test('terminal refresh retains and explicitly replays an unknown original submit without guessing ACK', () async {
      final backend = WorkspaceHeldBackend()
        ..installLearningFlow()
        ..submitFixture = 'submit_correct';
      final local = Harness(backend: backend);
      addTearDown(local.dispose);
      final c = await started(local);
      final id = c.attempt!.id;
      final sid = c.session!.id;
      c.selectOption('A');
      await c.flushNow();
      final snapshot = (await c.drafts.readDraft(local.questionId))!;
      final capture = await c.drafts.prepareSubmissionCapture(
        local.questionId,
        sourceSnapshot: snapshot,
        answer: const AnswerPayload(selectedOptions: ['A']).toJson(),
        elapsedMs: 321,
        body: DraftSync(
          baseRevision: snapshot.baseRevision,
          answer: const AnswerPayload(selectedOptions: ['A']),
        ).toJson(),
      );
      final syncResult = await c.api.syncDraft(
        attemptId: id,
        body: DraftSync.fromJson(capture.sync.body!),
        idempotencyKey: capture.sync.idempotencyKey,
      );
      final syncKnown = await c.drafts.recordWriteResult(
        local.questionId,
        lane: 'draft_sync',
        intentId: capture.sync.intentId,
        expectedGeneration: capture.sync.generation,
        result: syncResult.toJson(),
      );
      await c.drafts.ackDraftSync(
        local.questionId,
        intentId: syncKnown.intentId,
        expectedGeneration: syncKnown.generation,
      );
      final originalCommand = await c.drafts.finalizeSubmit(
        local.questionId,
        intentId: capture.submit.intentId,
        expectedGeneration: capture.submit.generation,
      );
      c.pendingSubmission = originalCommand;
      final originalRaw = originalCommand.toJson();
      backend.heldPath = '/api/v1/tutor/sessions/$sid/next';
      final hint = c.tutor(TutorActionType.requestHint);
      await backend.entered.future;
      await c.api.submitAttempt(
        attemptId: id,
        body: const SubmitRequest(
          answer: AnswerPayload(selectedOptions: ['B']),
        ),
        idempotencyKey: 'remote-real-submit-C',
      );
      c.selectOption('C');
      await c.flushNow();
      backend.heldPath = null;
      await c.api.tutorNext(
        sessionId: sid,
        body: const TutorAction(
          action: TutorActionType.requestStandard,
          confirmEndIndependent: true,
        ),
        idempotencyKey: 'remote-real-standard',
      );
      await c.api.tutorNext(
        sessionId: sid,
        body: const TutorAction(action: TutorActionType.markUnderstood),
        idempotencyKey: 'remote-real-understood',
      );
      expect((await c.api.getSession(sessionId: sid)).state, SessionState.done);
      backend.release.complete();
      await hint;
      expect(c.phase, isNot(SolvePhase.answering));
      expect(c.attempt!.status, AttemptStatus.submitted);
      expect(c.isFinished, isTrue);
      expect(c.canSubmit, isFalse);
      expect(c.assistanceAllowed, isFalse);
      expect(c.selected, {'C'});
      expect((await c.drafts.readDraft(local.questionId))!.selected, ['C']);
      expect(
        c.evaluation,
        isNull,
        reason: 'remote C feedback must not explain local B',
      );
      expect(
        (await c.drafts.readWrite(local.questionId, 'submit'))!.toJson(),
        originalRaw,
      );
      expect(c.needsSubmissionRecovery, isTrue);
      final writes = backend.requests.where((r) => r.method != 'GET').length;
      await c.submit();
      expect(
        await c.tutor(TutorActionType.requestHint),
        TutorOutcome.notAllowed,
      );
      await c.retry();
      expect(backend.requests.where((r) => r.method != 'GET').length, writes);
      c.dispose();
      final reopened = await started(local);
      expect(reopened.phase, isNot(SolvePhase.answering));
      expect(reopened.selected, {'C'});
      expect(reopened.evaluation, isNull);
      expect(reopened.needsSubmissionRecovery, isTrue);
      final attemptsBefore = backend.requestsTo('POST', r'/submit$').length;
      await reopened.recoverOriginalSubmission();
      final replay = backend.requestsTo('POST', r'/submit$').last;
      expect(
        backend.requestsTo('POST', r'/submit$').length,
        attemptsBefore + 1,
      );
      expect(replay.headers['Idempotency-Key'], originalCommand.idempotencyKey);
      expect(backend.bodyOf(replay), originalCommand.body);
      expect(reopened.selected, {'C'});
      expect(reopened.evaluation, isNull);
    });

    test('result known retries only GET refresh and a later hint gets a new intent', () async {
      final backend = RefreshFailBackend()..installLearningFlow();
      final local = Harness(backend: backend);
      addTearDown(local.dispose);
      final c = await started(local);
      expect(await c.tutor(TutorActionType.requestHint), TutorOutcome.failed);
      expect(backend.hintsRevealed, 1);
      await c.recoverTutor();
      expect(c.needsTutorRecovery, isFalse);
      expect(backend.requestsTo('POST', r'/next$').length, 1);
      expect(c.session!.hintLevelRevealed, 1);
      await c.tutor(TutorActionType.requestHint);
      final calls = backend.requestsTo('POST', r'/next$').toList();
      expect(calls.length, 2);
      expect(
        calls.last.headers['Idempotency-Key'],
        isNot(calls.first.headers['Idempotency-Key']),
      );
      expect(backend.hintsRevealed, 2);
      expect(c.events.length, 2);
    });

    test('successful lost tutor reply survives restart without consuming a second hint', () async {
      final backend = LostWriteBackend()..installLearningFlow();
      final local = Harness(backend: backend);
      addTearDown(local.dispose);
      final c = await started(local);
      backend.loseSuffix = '/next';
      await c.tutor(TutorActionType.requestHint);
      final original = backend.requestsTo('POST', r'/next$').single;
      expect(backend.hintsRevealed, 1);
      c.dispose();
      final reopened = await started(local);
      await reopened.tutor(TutorActionType.requestHint);
      final retried = backend.requestsTo('POST', r'/next$').last;
      expect(
        retried.headers['Idempotency-Key'],
        original.headers['Idempotency-Key'],
      );
      expect(retried.body, original.body);
      expect(backend.hintsRevealed, 1);
      expect(backend.sessionEvents.values.single.length, 1);
      expect(reopened.events.length, 1);
    });

    test('fresh authoritative session preserves solution and DONE after a tutor reply', () async {
      final backend = WorkspaceHeldBackend()..installLearningFlow();
      final local = Harness(backend: backend);
      addTearDown(local.dispose);
      final c = await started(local);
      final id = c.session!.id;
      backend.heldPath = '/api/v1/tutor/sessions/$id/next';
      final pending = c.tutor(TutorActionType.requestHint);
      await backend.entered.future;
      backend.sessionResources[id] = {
        ...backend.sessionResources[id]!,
        'used_solution': true,
        'assisted': true,
        'independent_ended': true,
        'hint_level_revealed': 3,
        'state': 'DONE',
      };
      backend.heldPath = null;
      backend.release.complete();
      await pending;
      expect(c.session!.usedSolution, isTrue);
      expect(c.session!.hintLevelRevealed, 3);
      expect(c.session!.state, SessionState.done);
    });

    test(
      'event pagination uses actual page max seq instead of global highwater',
      () async {
        final c = await started(h);
        final template =
            h.backend.fixtures.value('tutor_hint')['events'] as List;
        h.backend.sessionEvents[c.session!.id] = [
          for (var i = 1; i <= 450; i++)
            {
              ...template.first as Map<String, dynamic>,
              'id': 'history-$i',
              'session_id': c.session!.id,
              'seq_no': i,
            },
        ];
        c.dispose();
        final reopened = await started(h);
        expect(reopened.events.length, 450);
        final cursors = h.backend
            .requestsTo('GET', r'/events$')
            .map((r) => r.uri.queryParameters['after_seq'])
            .toList();
        expect(cursors, containsAllInOrder(['0', '200', '400']));
      },
    );
  });

  group('开始作答', () {
    for (final brokenBundle in [false, true]) {
      test(
        'corrupt ${brokenBundle ? 'bundle' : 'attempt draft'} blocks start and preserves raw',
        () async {
          final session = h.backend.fixtures.value('session_created');
          final attempt = h.backend.fixtures.value('attempt_created');
          await DraftStore(h.store, _user).writeActive(
            h.questionId,
            ActiveRef(
              sessionId: session['id'] as String,
              attemptId: attempt['id'] as String,
            ),
          );
          final key = 'u/$_user/draft-bundle/${h.questionId}';
          final raw = brokenBundle
              ? 'not-json'
              : jsonEncode({
                  'v': 1,
                  'drafts': {
                    'attempt/${attempt['id']}': {'v': 99},
                  },
                  'pending': {},
                  'references': {},
                });
          h.store.data[key] = raw;
          final c = h.controller();
          await c.start();
          expect(c.phase, SolvePhase.failed);
          expect(c.failure, isNotNull);
          expect(h.store.data[key], raw);
          expect(
            h.backend.requests.where(
              (r) => r.method == 'PUT' || r.uri.path.endsWith('/submit'),
            ),
            isEmpty,
          );
        },
      );
    }
    test('取题、开会话、建作答，进入作答状态', () async {
      final c = await started(h);

      expect(c.phase, SolvePhase.answering);
      expect(c.question!.content.options, hasLength(4));
      expect(c.questionFromCache, isFalse);
      expect(c.session, isNotNull);
      expect(c.attempt!.attemptNo, 1);
      expect(c.sync, SaveStatus.saved);
      expect(h.backend.sessionsCreated, 1);
      expect(h.backend.attemptsCreated, 1);
      final created = h.backend.bodyOf(
        h.backend.requestsTo('POST', '/sessions').single,
      )!;
      expect(created['origin'], 'practice');
      expect(created.containsKey('review_item_id'), isFalse);
    });

    test('每个创建动作都带幂等键', () async {
      await started(h);
      for (final request in [
        ...h.backend.requestsTo('POST', '/sessions'),
        ...h.backend.requestsTo('POST', '/attempts'),
      ]) {
        expect(request.headers['Idempotency-Key'], isNotNull);
        expect(
          request.headers['Idempotency-Key']!.length,
          greaterThanOrEqualTo(8),
        );
      }
    });

    test('题目不存在时进入失败状态，并给出能看的原因', () async {
      final backend = FakeBackend();
      backend.on(
        'GET',
        '/questions/[^/]+',
        (_) => errorResponse(404, 'not_found'),
      );
      final c = await started(Harness(backend: backend));

      expect(c.phase, SolvePhase.failed);
      expect(c.failure, isNotNull);
    });
  });

  group('答案与提交条件', () {
    test('单选：选一个才能提交，再点另一个是换选', () async {
      final c = await started(h);
      expect(c.canSubmit, isFalse);

      c.selectOption('A');
      expect(c.canSubmit, isTrue);
      c.selectOption('B');
      expect(c.selected, {'B'});
    });

    test('多选：可以选多个，取消到一个都没有就不能提交', () async {
      final backend = FakeBackend()
        ..installLearningFlow(questionFixture: 'question_multiple_choice');
      final c = await started(
        Harness(
          backend: backend,
          questionId:
              Fixtures.load().value('question_multiple_choice')['id'] as String,
        ),
      );

      c.selectOption('A');
      c.selectOption('C');
      expect(c.selected, {'A', 'C'});
      expect(c.canSubmit, isTrue);
      c.selectOption('A');
      c.selectOption('C');
      expect(c.selected, isEmpty);
      expect(c.canSubmit, isFalse);
    });

    test('填空：每个空都填了才能提交，空白不算', () async {
      final backend = FakeBackend()
        ..installLearningFlow(questionFixture: 'question_fill');
      final c = await started(
        Harness(
          backend: backend,
          questionId: Fixtures.load().value('question_fill')['id'] as String,
        ),
      );

      expect(c.canSubmit, isFalse);
      c.setBlank('b1', '   ');
      expect(c.canSubmit, isFalse);
      c.setBlank('b1', '5 m/s²');
      expect(c.canSubmit, isTrue);
    });
  });

  group('草稿：本地保存与云端同步', () {
    test('改动后先落本地、再同步到云端，状态依次变化', () async {
      final c = await started(h);

      c.selectOption('A');
      expect(c.sync, SaveStatus.dirty);
      await until(
        () => h.store.data.values.any((v) => v.contains('"selected":["A"]')),
        reason: '没有写入本地草稿',
      );
      await until(() => c.sync == SaveStatus.saved);

      expect(h.backend.serverRevision, 1);
      expect(h.backend.serverAnswer, {
        'selected_options': ['A'],
      });
      final saved = (await c.drafts.readDraft(h.questionId))!.toJson();
      expect(saved['dirty'], isFalse);
      expect(saved['baseRevision'], 1);
    });

    test('笔迹和答案一起同步', () async {
      final c = await started(h);

      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);

      final strokes = h.backend.serverStrokes!;
      expect(strokes['version'], 1);
      expect(
        ((strokes['pages'] as List).single as Map)['strokes'],
        hasLength(1),
      );
    });

    test('每次同步都带当前的基准版本号，且幂等键随内容变化', () async {
      final c = await started(h);
      c.selectOption('A');
      await until(() => c.sync == SaveStatus.saved);
      c.selectOption('B');
      await until(() => h.backend.serverRevision == 2);

      final puts = h.backend.requestsTo('PUT', '/attempts/.+/draft').toList();
      expect(puts.map((r) => h.backend.bodyOf(r)!['base_revision']), [0, 1]);
      expect(
        puts[0].headers['Idempotency-Key'],
        isNot(puts[1].headers['Idempotency-Key']),
      );
    });

    test('重开页面能从本机恢复答案和笔迹，并接着用原来的会话与作答', () async {
      final first = await started(h);
      first.selectOption('C');
      first.ink.beginStroke(0, 20, 30);
      first.ink.extendStroke(90, 90, t: 10);
      first.ink.endStroke();
      await until(() => first.sync == SaveStatus.saved);
      first.dispose();

      final second = await started(h);

      expect(second.selected, {'C'});
      expect(second.ink.hasInk, isTrue);
      expect(h.backend.sessionsCreated, 1, reason: '不能重复开会话');
      expect(h.backend.attemptsCreated, 1);
      expect(second.sync, SaveStatus.saved);
    });

    test('应用被切到后台时立刻保存，不等定时器', () async {
      final c = await started(h);
      c.selectOption('D');
      await c.flushNow();

      final saved = (await c.drafts.readDraft(h.questionId))!.toJson();
      expect((saved['answer'] as Map)['selected'], ['D']);
      expect(saved['dirty'], isTrue);
    });

    test('本机存储写失败时明确告诉学生，而不是装作保存成功', () async {
      final c = await started(h);
      h.store.failWrites = true;

      c.selectOption('A');
      await until(() => c.localSaveFailed);

      expect(c.localSaveFailed, isTrue);
      h.store.failWrites = false;
      c.selectOption('B');
      await until(() => !c.localSaveFailed, reason: '存储恢复后应该清除提示');
    });
  });

  group('断网', () {
    test(
      'failed promotion keeps the local source recoverable and blocks submit',
      () async {
        await trustedOfflineWorkspace(h);
        h.backend.offline = true;
        final c = await started(h);
        c.selectOption('C');
        await c.flushNow();
        final source = c.drafts;
        h.backend.offline = false;
        h.store.failWrites = true;
        await c.submit();
        expect(c.phase, SolvePhase.answering);
        expect(c.localSaveFailed, isTrue);
        expect(
          h.backend.requests.where((r) => r.uri.path.endsWith('/submit')),
          isEmpty,
        );
        h.store.failWrites = false;
        expect((await source.readDraft(h.questionId))!.selected, ['C']);
        c.dispose();
        h.backend.offline = true;
        final reopened = await started(h);
        expect(reopened.selected, {'C'});
      },
    );
    test('an offline local draft cannot revive after its attached attempt is submitted', () async {
      await trustedOfflineWorkspace(h);
      h.backend.offline = true;
      final c = await started(h);
      expect(c.attempt, isNull);
      c.selectOption('C');
      await c.flushNow();
      expect((await c.drafts.readDraft(h.questionId))!.selected, ['C']);
      h.backend.offline = false;
      await c.retryNow();
      expect(c.actionError, isNull);
      await until(() => c.sync == SaveStatus.saved);
      await c.submit();
      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(await c.drafts.readDraft(h.questionId), isNull);
      await c.drafts.clearActive(h.questionId);
      c.dispose();
      final reopened = await started(h);
      expect(reopened.phase, SolvePhase.answering);
      expect(
        reopened.selected,
        isEmpty,
        reason: 'submitted offline content must not reappear in a new exercise',
      );
    });
    test('断网时草稿照常保存在本机，状态是"未同步"；网络恢复后自动补上', () async {
      final c = await started(h);
      h.backend.offline = true;

      c.selectOption('A');
      await until(() => c.sync == SaveStatus.offline);
      expect(await c.drafts.readDraft(h.questionId), isNotNull);
      expect(h.backend.serverRevision, 0);

      h.backend.offline = false;
      await until(() => c.sync == SaveStatus.saved, reason: '恢复网络后应该自动同步');
      expect(h.backend.serverRevision, 1);
    });

    test('开始时就没网：用缓存的题目离线作答，恢复后才创建会话并把草稿同步上去', () async {
      // 先在线打开一次，让题目被缓存
      final warm = await started(h);
      warm.dispose();
      final fresh = FakeBackend()
        ..installLearningFlow()
        ..sessionOrigin = 'practice';
      final harness = Harness(store: h.store, backend: fresh);
      fresh.offline = true;

      final c = await started(harness);

      expect(c.phase, SolvePhase.answering);
      expect(c.questionFromCache, isTrue);
      c.selectOption('B');
      await until(() => c.sync == SaveStatus.offline);
      expect(fresh.sessionsCreated, 0);

      fresh.offline = false;
      await until(() => c.sync == SaveStatus.saved);
      expect(fresh.sessionsCreated, 0);
      expect(fresh.serverAnswer, {
        'selected_options': ['B'],
      });
      harness.dispose();
    });

    test('开始时没网、也没有缓存的题目：说明原因，不白屏', () async {
      final backend = FakeBackend()..offline = true;
      final c = await started(Harness(backend: backend));

      expect(c.phase, SolvePhase.failed);
      expect((c.failure as ApiException).isNetwork, isTrue);
    });

    test('断网时不能提交，草稿保留，并说明原因', () async {
      final c = await started(h);
      c.selectOption('B');
      h.backend.offline = true;

      await c.submit();

      expect(c.phase, SolvePhase.answering);
      expect(c.actionError, isNotNull);
      expect((c.actionError as ApiException).isNetwork, isTrue);
      expect(c.selected, {'B'});
    });
  });

  group('版本冲突（409）', () {
    Future<SolveController> conflicted(Harness h) async {
      final c = await started(h);
      c.selectOption('A');
      await until(() => c.sync == SaveStatus.saved);
      // 别处把云端草稿改成了另一份
      h.backend.serverRevision = 5;
      h.backend.serverAnswer = {
        'selected_options': ['D'],
      };
      c.selectOption('B');
      await until(() => c.sync == SaveStatus.conflict);
      return c;
    }

    test('不静默覆盖：进入冲突状态，同时保留本地稿和云端稿', () async {
      final c = await conflicted(h);

      expect(c.conflictServerDraft!.revision, 5);
      expect(c.selected, {'B'}, reason: '本地稿原样保留');
      expect(h.backend.serverAnswer, {
        'selected_options': ['D'],
      }, reason: '云端稿没有被覆盖');
      expect(c.canSubmit, isFalse, reason: '有冲突时先解决再提交');
    });
    test(
      'conflict creates an independent server copy at observed revision',
      () async {
        final c = await conflicted(h);
        Map<String, dynamic>? sent;
        final sourceId = c.attempt!.id;
        h.backend.on('POST', '/attempts/[^/]+/copies', (request) {
          sent = jsonDecode(request.body!) as Map<String, dynamic>;
          final copiedAttempt = {
            ...c.attempt!.toJson(),
            'id': 'server-copy',
            'draft_revision': 1,
          };
          return okResponse({
            'session': c.session!.toJson(),
            'attempt': copiedAttempt,
            'draft': {
              'attempt_id': 'server-copy',
              'revision': 1,
              'answer': sent!['answer'],
              'strokes': sent!['strokes'],
              'updated_at': '2026-11-10T08:00:00Z',
            },
          }, status: 201);
        });
        await c.resolveConflictCreateCopy();
        expect(sent!['source_revision'], 5);
        expect(c.attempt!.id, 'server-copy');
        expect(c.selected, {'B'});
        expect(c.attempt!.id, isNot(sourceId));
        expect(h.backend.serverAnswer, {
          'selected_options': ['D'],
        });
      },
    );
    test(
      'copy mapping failure replays the same key after source submission',
      () async {
        final c = await conflicted(h);
        final keys = <String>[];
        Map<String, dynamic>? receipt;
        h.backend.on('POST', '/attempts/[^/]+/copies', (request) {
          keys.add(request.headers['Idempotency-Key']!);
          final sent = jsonDecode(request.body!) as Map<String, dynamic>;
          receipt ??= {
            'session': c.session!.toJson(),
            'attempt': {
              ...c.attempt!.toJson(),
              'id': 'replayed-copy',
              'draft_revision': 1,
            },
            'draft': {
              'attempt_id': 'replayed-copy',
              'revision': 1,
              'answer': sent['answer'],
              'strokes': sent['strokes'],
              'updated_at': '2026-11-10T08:00:00Z',
            },
          };
          if (keys.length == 1) h.store.failWrites = true;
          return okResponse(receipt!, status: 201);
        });
        await c.resolveConflictCreateCopy();
        expect(c.attempt!.id, isNot('replayed-copy'));
        h.store.failWrites = false;
        h.backend.submitted = true;
        await c.resolveConflictCreateCopy();
        expect(keys, hasLength(2));
        expect(keys[1], keys[0]);
        expect(c.attempt!.id, 'replayed-copy');
        expect(c.selected, {'B'});
      },
    );

    test('lost copy response survives restart and source submission', () async {
      final c = await conflicted(h);
      final keys = <String>[];
      final sourceAttempt = c.attempt!.toJson();
      final sourceSession = c.session!.toJson();
      Map<String, dynamic>? receipt;
      h.backend.on('POST', '/attempts/[^/]+/copies', (request) {
        keys.add(request.headers['Idempotency-Key']!);
        final sent = jsonDecode(request.body!) as Map<String, dynamic>;
        receipt ??= {
          'session': sourceSession,
          'attempt': {
            ...sourceAttempt,
            'id': 'lost-response-copy',
            'draft_revision': 1,
          },
          'draft': {
            'attempt_id': 'lost-response-copy',
            'revision': 1,
            'answer': sent['answer'],
            'strokes': sent['strokes'],
            'updated_at': '2026-11-10T08:00:00Z',
          },
        };
        if (keys.length == 1) {
          throw ApiException.network('response lost after creation');
        }
        return okResponse(receipt!, status: 201);
      });
      await c.resolveConflictCreateCopy();
      c.dispose();
      h.backend.submitted = true;
      final reopened = await started(h);
      await reopened.resolveConflictCreateCopy();
      expect(keys, hasLength(2));
      expect(keys[1], keys[0]);
      expect(reopened.actionError, isNull);
      expect(reopened.attempt!.id, 'lost-response-copy');
      expect(reopened.selected, {'B'});
      expect(reopened.session!.state, SessionState.diagnosed);
    });
    test(
      'a late copy response preserves newer editing and only records the copy',
      () async {
        final delayed = DelayedCopyBackend()..installLearningFlow();
        h = Harness(backend: delayed, autosaveDelay: const Duration(days: 1));
        delayed.on(
          'GET',
          '/attempts/late-copy',
          (request) => okResponse({
            ...delayed.fixtures.value('attempt_created'),
            'id': 'late-copy',
            'draft_revision': 1,
          }),
        );
        final c = await conflicted(h);
        final sourceId = c.attempt!.id;
        delayed.on('POST', '/attempts/[^/]+/copies', (request) {
          final body = jsonDecode(request.body!) as Map<String, dynamic>;
          return okResponse({
            'session': c.session!.toJson(),
            'attempt': {
              ...c.attempt!.toJson(),
              'id': 'late-copy',
              'draft_revision': 1,
            },
            'draft': {
              'attempt_id': 'late-copy',
              'revision': 1,
              'answer': body['answer'],
              'strokes': body['strokes'],
              'updated_at': '2026-11-10T08:00:00Z',
            },
          }, status: 201);
        });
        final copying = c.resolveConflictCreateCopy();
        await delayed.entered.future;
        c.selectOption('C');
        delayed.release.complete();
        await copying;
        expect(c.selected, {'C'});
        expect(c.attempt!.id, sourceId);
        expect(
          await c.drafts.forAttempt('late-copy').readDraft(h.questionId),
          isNotNull,
        );
        h.store.failWrites = true;
        await c.resolveConflictCreateCopy();
        expect(c.attempt!.id, sourceId);
        expect(c.selected, {'C'});
        expect(c.localSaveFailed, isTrue);
        expect(
          delayed.requests.where((r) => r.uri.path.endsWith('/copies')),
          hasLength(1),
        );
        h.store.failWrites = false;
        await c.resolveConflictCreateCopy();
        expect(c.attempt!.id, 'late-copy');
        expect(
          (await c.drafts.forAttempt(sourceId).readDraft(h.questionId))!
              .selected,
          ['C'],
        );
        final requests = delayed.requests
            .where((r) => r.uri.path.endsWith('/copies'))
            .toList();
        expect(
          requests[0].headers['Idempotency-Key'],
          requests[1].headers['Idempotency-Key'],
        );
        expect(requests[0].body, requests[1].body);
        final sessionId = c.session!.id;
        c.dispose();
        delayed.offline = true;
        final source = h.controller(sessionId: sessionId, attemptId: sourceId);
        await source.start();
        expect(source.selected, {'C'});
      },
    );
    test(
      'source and copied drafts retain separate offline edits across reopen',
      () async {
        final c = await conflicted(h);
        final source = c.attempt!.id;
        final session = c.session!.id;
        h.backend.on('POST', '/attempts/[^/]+/copies', (request) {
          final body = jsonDecode(request.body!) as Map<String, dynamic>;
          return okResponse({
            'session': c.session!.toJson(),
            'attempt': {
              ...c.attempt!.toJson(),
              'id': 'independent-copy',
              'draft_revision': 1,
            },
            'draft': {
              'attempt_id': 'independent-copy',
              'revision': 1,
              'answer': body['answer'],
              'strokes': body['strokes'],
              'updated_at': '2026-11-10T08:00:00Z',
            },
          }, status: 201);
        });
        await c.resolveConflictCreateCopy();
        h.backend.offline = true;
        c.selectOption('C');
        await c.flushNow();
        c.dispose();
        final original = h.controller(sessionId: session, attemptId: source);
        await original.start();
        expect(original.selected, {'B'});
        original.selectOption('D');
        await original.flushNow();
        original.dispose();
        final copied = h.controller(
          sessionId: session,
          attemptId: 'independent-copy',
        );
        await copied.start();
        expect(copied.phase, SolvePhase.answering);
        expect(copied.selected, {'C'});
        expect(
          (await copied.drafts.forAttempt(source).readDraft(h.questionId))!
              .selected,
          ['D'],
        );
      },
    );
    test('a copy submitted elsewhere after lost response never reopens as editable', () async {
      final c = await conflicted(h);
      final source = c.attempt!.id;
      h.backend.on(
        'POST',
        '/attempts/[^/]+/copies',
        (request) => okResponse({
          'session': c.session!.toJson(),
          'attempt': {...c.attempt!.toJson(), 'id': 'submitted-copy'},
          'draft': {
            'attempt_id': 'submitted-copy',
            'revision': 1,
            'answer': {
              'selected_options': ['B'],
            },
            'strokes': null,
            'updated_at': '2026-11-10T08:00:00Z',
          },
        }, status: 201),
      );
      h.backend.on(
        'GET',
        '/attempts/submitted-copy',
        (_) => okResponse({
          ...c.attempt!.toJson(),
          'id': 'submitted-copy',
          'status': 'submitted',
        }),
      );
      await c.resolveConflictCreateCopy();
      expect(c.attempt!.id, source);
      expect(c.selected, {'B'});
      expect(c.actionError.toString(), contains('副本已提交'));
      expect(await c.drafts.readPendingCopy(h.questionId), isNotNull);
    });
    test('legacy copy pending can only be acknowledged by explicit verified selection', () async {
      final c = await conflicted(h);
      final source = c.drafts;
      final sourceId = c.attempt!.id;
      var lost = true;
      h.backend.on('POST', '/attempts/[^/]+/copies', (request) {
        if (lost) {
          lost = false;
          throw ApiException.network('lost response');
        }
        return okResponse({
          'session': c.session!.toJson(),
          'attempt': {
            ...c.attempt!.toJson(),
            'id': 'server-copy',
            'draft_revision': 1,
          },
          'draft': {
            'attempt_id': 'server-copy',
            'revision': 1,
            'answer': {
              'selected_options': ['B'],
            },
            'strokes': null,
            'updated_at': '2026-11-10T08:00:00Z',
          },
        }, status: 201);
      });
      h.backend.on(
        'GET',
        '/attempts/server-copy/draft',
        (_) => okResponse({
          'attempt_id': 'server-copy',
          'revision': 1,
          'answer': {
            'selected_options': ['B'],
          },
          'strokes': null,
          'updated_at': '2026-11-10T08:00:00Z',
        }),
      );
      await c.resolveConflictCreateCopy();
      final bundleKey = 'u/$_user/draft-bundle/${h.questionId}';
      final bundle =
          jsonDecode(h.store.data[bundleKey]!) as Map<String, dynamic>;
      ((bundle['pending'] as Map).values.single as Map).remove(
        'activationEpoch',
      );
      h.store.data[bundleKey] = jsonEncode(bundle);
      await c.resolveConflictCreateCopy();
      expect(c.attempt!.id, sourceId);
      expect(c.selectableCopy!.attemptId, 'server-copy');
      expect(await source.readPendingCopy(h.questionId), isNotNull);
      c.selectOption('C');
      await c.openCreatedCopy();
      expect(c.attempt!.id, 'server-copy');
      expect((await source.readDraft(h.questionId))!.selected, ['C']);
      expect(await source.readPendingCopy(h.questionId), isNull);
    });
    test('冲突重启恢复，解决前留档，恢复本机副本先保留当前稿', () async {
      final c = await conflicted(h);
      await c.flushNow();
      await until(() => c.recoveryCopies.isNotEmpty);
      c.dispose();
      final reopened = await started(h);
      expect(reopened.sync, SaveStatus.conflict);
      expect(reopened.selected, {'B'});
      expect(reopened.conflictServerDraft!.answer!.selectedOptions, ['D']);
      await reopened.resolveConflictUseServer();
      expect(reopened.selected, {'D'});
      final before = reopened.recoveryCopies.length;
      await reopened.restoreCopy(0);
      expect(reopened.selected, {'B'});
      expect(reopened.recoveryCopies.length, before + 2);
      expect(reopened.recoveryCopies[before].selected, ['D']);
      expect(h.backend.serverAnswer!['selected_options'], ['D']);
    });

    test('离线重启也能恢复本机副本，不要求先取得云端作答', () async {
      final c = await conflicted(h);
      await c.resolveConflictUseServer();
      c.dispose();
      h.backend.offline = true;
      final reopened = await started(h);
      expect(reopened.attempt, isNull);
      expect(reopened.selected, {'D'});
      await reopened.restoreCopy(0);
      expect(reopened.selected, {'B'});
      expect(reopened.localSaveFailed, isFalse);
      expect((await reopened.drafts.readDraft(h.questionId))!.selected, ['B']);
      expect(h.backend.serverAnswer!['selected_options'], ['D']);
    });

    test('留档写入失败拒绝双方覆盖，云端和本机内容均不变', () async {
      final c = await conflicted(h);
      await until(() => c.recoveryCopies.isNotEmpty);
      h.store.failWrites = true;
      await c.resolveConflictKeepLocal();
      expect(c.sync, SaveStatus.conflict);
      expect(c.selected, {'B'});
      expect(h.backend.serverAnswer!['selected_options'], ['D']);
      expect(h.backend.serverRevision, 5);
      await c.resolveConflictUseServer();
      expect(c.sync, SaveStatus.conflict);
      expect(c.selected, {'B'});
      expect(c.conflictServerDraft, isNotNull);
      expect(c.localSaveFailed, isTrue);
    });

    test('等待留档时的新输入不会被迟到的云端选择覆盖', () async {
      h.dispose();
      final delayed = DelayedRecoveryStore();
      h = Harness(store: delayed);
      final c = await conflicted(h);
      await until(() => c.recoveryCopies.isNotEmpty);
      delayed.block = Completer<void>();
      final entered = Completer<void>();
      delayed.entered = entered;
      final resolving = c.resolveConflictUseServer();
      await entered.future;
      c.selectOption('C');
      delayed.block!.complete();
      await resolving;
      expect(c.selected, {'C'});
      expect(c.sync, SaveStatus.conflict);
      expect(h.backend.serverAnswer!['selected_options'], ['D']);
    });

    for (final corrupt in [false, true]) {
      test('${corrupt ? "损坏" : "待解决"}记录离线重启后联网不自动采用或上传', () async {
        final c = await conflicted(h);
        await c.flushNow();
        await until(() => c.recoveryCopies.isNotEmpty);
        c.dispose();
        final recoveryKey = h.store.data.keys.singleWhere(
          (key) => key.contains('/draft-recovery/'),
        );
        if (corrupt) {
          h.store.data[recoveryKey] = '{"v":99}';
          final local = await c.drafts.readDraft(h.questionId);
          final json = local!.toJson()..['dirty'] = false;
          await c.drafts.writeDraft(LocalDraft.fromJson(json));
        }
        final raw = h.store.data[recoveryKey];
        final puts = h.backend.requestsTo('PUT', '/draft').length;
        final gets = h.backend.requestsTo('GET', '/draft').length;
        final requests = h.backend.requests.length;
        h.backend.offline = true;
        final reopened = await started(h);
        h.backend.offline = false;
        await reopened.retryNow();
        await Future<void>.delayed(const Duration(milliseconds: 200));
        expect(h.backend.requestsTo('PUT', '/draft').length, puts);
        expect(h.backend.requestsTo('GET', '/draft').length, gets);
        expect(h.backend.requests.length, requests);
        expect(reopened.selected, {'B'});
        expect(reopened.sync, SaveStatus.conflict);
        expect(reopened.canSubmit, isFalse);
        expect(h.backend.serverAnswer!['selected_options'], ['D']);
        expect(h.backend.serverRevision, 5);
        expect(h.store.data[recoveryKey], raw);
        if (!corrupt) {
          await reopened.resolveConflictUseServer();
          expect(reopened.selected, {'D'});
          expect(reopened.sync, SaveStatus.saved);
        }
      });
    }

    test('恢复留档等待期间禁止提交且不触发提交请求', () async {
      h.dispose();
      final delayed = DelayedRecoveryStore();
      h = Harness(store: delayed);
      final c = await conflicted(h);
      await c.resolveConflictUseServer();
      delayed.block = Completer<void>();
      final entered = Completer<void>();
      delayed.entered = entered;
      final restoring = c.restoreCopy(0);
      await entered.future;
      expect(c.canSubmit, isFalse);
      await c.submit();
      expect(h.backend.requestsTo('POST', '/submit'), isEmpty);
      delayed.block!.complete();
      await restoring;
      expect(c.phase, SolvePhase.answering);
      expect(c.selected, {'B'});
    });

    test('保留本地稿：以云端版本为基准重新同步，覆盖云端', () async {
      final c = await conflicted(h);

      await c.resolveConflictKeepLocal();
      await until(() => c.sync == SaveStatus.saved);

      expect(h.backend.serverAnswer, {
        'selected_options': ['B'],
      });
      expect(h.backend.serverRevision, 6);
      expect(c.conflictServerDraft, isNull);
    });

    test('使用云端稿：本地内容换成云端的', () async {
      final c = await conflicted(h);

      await c.resolveConflictUseServer();

      expect(c.selected, {'D'});
      expect(c.sync, SaveStatus.saved);
      expect(c.conflictServerDraft, isNull);
      expect(h.backend.serverAnswer, {
        'selected_options': ['D'],
      });
    });

    test('云端内容与本地一致（例如响应丢了、重启后重复同步）时静默接受，不打扰学生', () async {
      final c = await started(h);
      h.backend.serverRevision = 3;
      h.backend.serverAnswer = {
        'selected_options': ['C'],
      };

      c.selectOption('C');
      await until(() => c.sync == SaveStatus.saved);

      expect(c.conflictServerDraft, isNull);
    });
  });

  group('提交', () {
    test('答对：记录评估，进入已提交状态，本地草稿清掉', () async {
      h.backend.submitFixture = 'submit_correct';
      final c = await started(h);
      c.selectOption('B');

      await c.submit();

      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(c.evaluation!.state, EvaluationState.verified);
      expect(c.evaluation!.isCorrect, isTrue);
      expect(c.events.map((e) => e.type), contains(TutorEventType.diagnosis));
      expect(c.session!.state, SessionState.diagnosed);
      expect(await c.drafts.readDraft(h.questionId), isNull);
      final body = h.backend.bodyOf(
        h.backend.requestsTo('POST', '/attempts/.+/submit').single,
      )!;
      expect(body['answer'], {
        'selected_options': ['B'],
      });
    });

    test('提交前会把最新的笔迹同步一遍', () async {
      h.backend.submitFixture = 'submit_correct';
      final c = await started(h);
      c.selectOption('B');
      c.ink.beginStroke(0, 5, 5);
      c.ink.extendStroke(50, 50, t: 9);
      c.ink.endStroke();

      await c.submit();

      expect(h.backend.serverStrokes, isNotNull);
    });

    test('判不出来：原样展示"待确认"，没有对错', () async {
      h.backend.submitFixture = 'submit_uncertain';
      final c = await started(h);
      c.selectOption('A');

      await c.submit();

      expect(c.evaluation!.state, EvaluationState.uncertain);
      expect(c.evaluation!.isCorrect, isNull);
      expect(c.events.first.type, TutorEventType.uncertainty);
    });

    test('网络失败后重试，用的是同一个幂等键（服务端不会当成新的提交）', () async {
      h.backend.submitFixture = 'submit_correct';
      final c = await started(h);
      c.selectOption('B');
      await c.flushNow();
      h.backend.failNextOn(r'/submit$', 503, 'internal_error');
      await c.submit();
      expect(c.phase, SolvePhase.answering);

      await c.submit();

      final keys = h.backend
          .requestsTo('POST', '/attempts/.+/submit')
          .map((r) => r.headers['Idempotency-Key'])
          .toList();
      expect(keys, hasLength(2));
      expect(keys[0], keys[1]);
      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
    });

    test(
      '303A retry freezes complete submission body including elapsed',
      () async {
        final c = await started(h);
        c.selectOption('B');
        h.backend.failNextOn(r'/submit$', 503, 'internal_error');
        await c.submit();
        await Future<void>.delayed(const Duration(milliseconds: 20));
        await c.submit();
        final writes = h.backend.requestsTo('POST', r'/submit$').toList();
        expect(writes.length, 2);
        expect(writes.last.body, writes.first.body);
        expect(
          writes.last.headers['Idempotency-Key'],
          writes.first.headers['Idempotency-Key'],
        );
      },
    );

    test('303A lost submit survives restart with fixed body and key', () async {
      final backend = LostWriteBackend()..installLearningFlow();
      final local = Harness(backend: backend);
      addTearDown(local.dispose);
      final c = await started(local);
      c.selectOption('A');
      backend.loseSuffix = '/submit';
      await c.submit();
      expect(backend.submitted, isTrue);
      final original = backend.requestsTo('POST', r'/submit$').single;
      c.dispose();
      final reopened = await started(local);
      expect(reopened.needsSubmissionRecovery, isTrue);
      await reopened.recoverOriginalSubmission();
      expect(reopened.phase, SolvePhase.submitted);
      final retry = backend.requestsTo('POST', r'/submit$').last;
      expect(retry.body, original.body);
      expect(
        retry.headers['Idempotency-Key'],
        original.headers['Idempotency-Key'],
      );
      expect(backend.attemptsCreated, 1);
      reopened.dispose();
      final confirmed = await started(local);
      expect(confirmed.phase, SolvePhase.submitted);
      expect(
        confirmed.selected,
        {'A'},
        reason: 'confirmed submission A stays visible after its local draft was ACK-cleared',
      );
    });

    test('303A unknown A edited to B sends no writes until explicit recovery and keeps continuation', () async {
      final backend = LostWriteBackend()..installLearningFlow();
      final local = Harness(backend: backend);
      addTearDown(local.dispose);
      final c = await started(local);
      await c.tutor(TutorActionType.requestHint);
      c.selectOption('A');
      backend.loseSuffix = '/submit';
      await c.submit();
      c.selectOption('B');
      await c.flushNow();
      final before = backend.requests.where((r) => r.method != 'GET').length;
      await c.retryNow();
      await c.submit();
      expect(backend.requests.where((r) => r.method != 'GET').length, before);
      expect(backend.submittedAnswer, {
        'selected_options': ['A'],
      });
      await c.recoverOriginalSubmission();
      expect(c.selected, {'A'});
      expect(c.continuations.single.draft.selected, ['B']);
      final id = c.continuations.single.id;
      await c.continueDraft(id);
      expect(c.phase, SolvePhase.answering);
      expect(c.selected, {'B'});
      expect(backend.sessionsCreated, 1);
      expect(backend.attemptsCreated, 2);
      expect(c.session!.assisted, isTrue);
      expect(c.session!.hintLevelRevealed, 1);
      expect(backend.submittedAttempts.values.single['answer'], {
        'selected_options': ['A'],
      });
      expect(c.continuations, isEmpty);
    });

    test(
      '303A first awaited capture preserves clicked A and immediate B',
      () async {
        final c = await started(h);
        c.selectOption('A');
        final submission = c.submit();
        c.selectOption('B');
        await submission;
        expect(
          c.phase,
          SolvePhase.submitted,
          reason: c.actionError?.toString(),
        );
        expect(h.backend.submittedAnswer, {
          'selected_options': ['A'],
        });
        expect(c.continuations.single.draft.selected, ['B']);
      },
    );

    test(
      '303A click A is durable while an earlier X sync is still in flight',
      () async {
        final backend = WorkspaceHeldBackend()..installLearningFlow();
        final local = Harness(backend: backend);
        addTearDown(local.dispose);
        final c = await started(local);
        backend.heldPath = '/api/v1/attempts/${c.attempt!.id}/draft';
        c.selectOption('C');
        await backend.entered.future;
        c.selectOption('A');
        final submission = c.submit();
        c.selectOption('B');
        await c.flushNow();
        await Future<void>.delayed(const Duration(milliseconds: 20));
        final capturedWhileXHeld = await c.drafts.readWrite(
          local.questionId,
          'submit',
        );
        backend.heldPath = null;
        backend.release.complete();
        await submission;
        expect(
          capturedWhileXHeld,
          isNotNull,
          reason:
              'clicked A and elapsed must already be durable before awaiting X',
        );
        expect(capturedWhileXHeld!.sourceSnapshot.selected, ['A']);
        expect(backend.submittedAnswer, {
          'selected_options': ['A'],
        });
        expect(c.continuations.single.draft.selected, ['B']);
      },
    );

    test('303A sync lost receipt restores fixed A before syncing dirty B after restart', () async {
      final backend = LostWriteBackend()..installLearningFlow();
      final local = Harness(backend: backend);
      addTearDown(local.dispose);
      final c = await started(local);
      backend.loseSuffix = '/draft';
      c.selectOption('A');
      await until(() => c.sync == SaveStatus.offline);
      c.selectOption('B');
      await c.flushNow();
      final original = backend.requestsTo('PUT', r'/draft$').single;
      c.dispose();
      final restored = await started(local);
      await until(() => restored.sync == SaveStatus.saved);
      final writes = backend.requestsTo('PUT', r'/draft$').toList();
      expect(writes[1].body, original.body);
      expect(
        writes[1].headers['Idempotency-Key'],
        original.headers['Idempotency-Key'],
      );
      expect(backend.serverAnswer, {
        'selected_options': ['B'],
      });
      expect(backend.serverRevision, 2);
      expect(restored.selected, {'B'});
    });

    test('303A unbound clicked A survives hanging creation and restart while B remains local', () async {
      final backend = LostCreationBackend()..installLearningFlow();
      final local = Harness(backend: backend);
      addTearDown(local.dispose);
      await trustedOfflineWorkspace(local);
      backend.offline = true;
      final c = await started(local);
      c.selectOption('A');
      await c.flushNow();
      backend.offline = false;
      final release = Completer<void>();
      backend.holdResponse = release;
      backend.responseEntered = Completer<void>();
      final original = c.submit();
      await backend.responseEntered!.future;
      c.selectOption('B');
      await c.flushNow();
      c.dispose();
      backend.holdResponse = null;
      final restored = await started(local);
      final recoveredIntent = restored.needsSubmissionRecovery;
      release.complete();
      await original;
      expect(
        recoveredIntent,
        isTrue,
        reason: 'unbound clicked A and fixed elapsed must be durable before create network',
      );
      await restored.recoverOriginalSubmission();
      expect(backend.submittedAnswer, {
        'selected_options': ['A'],
      });
      expect(
        restored.phase,
        SolvePhase.submitted,
        reason: restored.actionError?.toString(),
      );
      expect(restored.continuations.single.draft.selected, ['B']);
      expect(backend.sessionsCreated, 1);
      expect(backend.attemptsCreated, 1);
    });

    test('303A restart after sync ACK before submit finalization uses the original dependency', () async {
      final c = await started(h);
      c.selectOption('A');
      await c.flushNow();
      c.dispose();
      final snapshot = (await c.drafts.readDraft(h.questionId))!;
      final capture = await c.drafts.prepareSubmissionCapture(
        h.questionId,
        sourceSnapshot: snapshot,
        answer: const AnswerPayload(selectedOptions: ['A']).toJson(),
        elapsedMs: 123,
        body: DraftSync(
          baseRevision: 0,
          answer: const AnswerPayload(selectedOptions: ['A']),
        ).toJson(),
      );
      final saved = await c.api.syncDraft(
        attemptId: c.attempt!.id,
        body: DraftSync.fromJson(capture.sync.body!),
        idempotencyKey: capture.sync.idempotencyKey,
      );
      final known = await c.drafts.recordWriteResult(
        h.questionId,
        lane: 'draft_sync',
        intentId: capture.sync.intentId,
        expectedGeneration: capture.sync.generation,
        result: saved.toJson(),
      );
      await c.drafts.ackDraftSync(
        h.questionId,
        intentId: known.intentId,
        expectedGeneration: known.generation,
      );
      c.dispose();
      final restored = await started(h);
      await restored.recoverOriginalSubmission();
      expect(
        restored.phase,
        SolvePhase.submitted,
        reason: restored.actionError?.toString(),
      );
      expect(h.backend.requestsTo('PUT', r'/draft$').length, 1);
      expect(h.backend.submittedAnswer, {
        'selected_options': ['A'],
      });
    });

    test('在不能提交时调用 submit 什么也不发生', () async {
      final c = await started(h);
      await c.submit();
      expect(h.backend.requestsTo('POST', '/attempts/.+/submit'), isEmpty);
    });

    test('答错后可以再试一次：新建作答，清掉答案和笔迹', () async {
      final c = await started(h);
      c.selectOption('A');
      c.ink.beginStroke(0, 5, 5);
      c.ink.endStroke();
      await c.submit();
      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());

      await c.retry();

      expect(c.actionError, isNull);
      expect(c.phase, SolvePhase.answering);
      expect(c.selected, isEmpty);
      expect(c.ink.hasInk, isFalse);
      expect(c.evaluation, isNull);
      expect(h.backend.attemptsCreated, 2);
    });
  });

  group('辅导动作', () {
    test('offline restart restores confirmed tutor history without attaching remotely', () async {
      final c = await started(h);
      expect(await c.tutor(TutorActionType.requestHint), TutorOutcome.ok);
      final original = c.events.single.toJson();
      final sessionId = c.session!.id;
      c.dispose();
      h.backend.offline = true;
      final reopened = await started(h);
      expect(reopened.events.map((e) => e.toJson()), [original]);
      expect(reopened.session, isNull);
      expect(reopened.eventSessionId, sessionId);
      expect(
        await reopened.tutor(TutorActionType.requestHint),
        isNot(TutorOutcome.ok),
      );
      expect(h.backend.hintsRevealed, 1);
      final other = SolveController(
        api: TutorApiClient(h.core),
        store: h.store,
        userId: 'different-user',
        args: SolveArgs(questionId: h.questionId),
      );
      addTearDown(other.dispose);
      await other.start();
      expect(other.events, isEmpty);
      expect(other.eventSessionId, isNull);
    });

    test('给点提示：事件追加到时间线，会话更新', () async {
      final c = await started(h);

      final outcome = await c.tutor(TutorActionType.requestHint);

      expect(outcome, TutorOutcome.ok);
      expect(c.events.single.type, TutorEventType.hint);
      expect(c.events.single.hint.level, 1);
      expect(c.session!.assisted, isTrue);
    });

    test('提交前查看解析：先要求确认，没确认就不会有任何内容', () async {
      final c = await started(h);

      final outcome = await c.tutor(TutorActionType.requestStandard);

      expect(outcome, TutorOutcome.needsConfirmation);
      expect(c.events, isEmpty);
      expect(c.session!.usedSolution, isFalse);
    });

    test('确认结束独立作答之后才给解析', () async {
      final c = await started(h);

      final outcome = await c.tutor(
        TutorActionType.requestStandard,
        confirmEndIndependent: true,
      );

      expect(outcome, TutorOutcome.ok);
      expect(c.events.single.type, TutorEventType.standard);
      final body = h.backend.bodyOf(
        h.backend.requestsTo('POST', '/tutor/sessions/.+/next').last,
      )!;
      expect(body['confirm_end_independent'], isTrue);
    });

    test('提交之后看解析不需要确认', () async {
      final c = await started(h);
      c.selectOption('A');
      await c.submit();

      expect(await c.tutor(TutorActionType.requestStandard), TutorOutcome.ok);
    });

    test('一次点击一个动作：处理中重复点击被忽略', () async {
      final c = await started(h);

      final first = c.tutor(TutorActionType.requestHint);
      final second = await c.tutor(TutorActionType.requestHint);
      await first;

      expect(second, TutorOutcome.busy);
      expect(
        h.backend.requestsTo('POST', '/tutor/sessions/.+/next'),
        hasLength(1),
      );
    });

    test('服务端报错时返回失败并保留错误，时间线不变', () async {
      final c = await started(h);
      h.backend.failNext = (503, 'model_unavailable');

      final outcome = await c.tutor(TutorActionType.requestHint);

      expect(outcome, TutorOutcome.failed);
      expect(c.actionError, isNotNull);
      expect(c.events, isEmpty);
    });

    test('时间线里的事件顺序就是服务端给的顺序', () async {
      final c = await started(h);
      await c.tutor(TutorActionType.requestHint);
      await c.tutor(TutorActionType.requestVisual);

      expect(c.events.map((e) => e.type), [
        TutorEventType.hint,
        TutorEventType.notice,
      ]);
    });
  });

  group('复测会话', () {
    late Harness retest;
    setUp(
      () => retest = Harness(origin: 'review', reviewItemId: 'review-item-1'),
    );
    tearDown(() => retest.dispose());

    test('提交前不提供任何辅助，界面据此隐藏按钮', () async {
      final c = await started(retest);
      expect(c.assistanceAllowed, isFalse);
      expect(
        await c.tutor(TutorActionType.requestHint),
        TutorOutcome.notAllowed,
      );
      expect(
        retest.backend.requestsTo('POST', '/tutor/sessions/.+/next'),
        isEmpty,
      );
    });

    test('开会话时带上复测项；提交后自动记录复测结果', () async {
      retest.backend.submitFixture = 'submit_correct';
      final c = await started(retest);
      c.selectOption('B');

      await c.submit();

      final created = retest.backend.bodyOf(
        retest.backend.requestsTo('POST', '/sessions').single,
      )!;
      expect(created['origin'], 'review');
      expect(created['review_item_id'], 'review-item-1');
      expect(c.assistanceAllowed, isTrue);
      expect(c.reviewCompletion, isNotNull);
      expect(c.reviewCompletion!.result, ReviewResult.passed);
      final completed = retest.backend
          .requestsTo('POST', '/reviews/.+/complete')
          .single;
      expect(completed.uri.path, endsWith('/review-item-1/complete'));
    });
  });

  group('解答题', () {
    late Harness w;
    setUp(() {
      final backend = FakeBackend()
        ..submitFixture = 'submit_written'
        ..installLearningFlow(questionFixture: 'question_written');
      w = Harness(
        backend: backend,
        questionId: Fixtures.load().value('question_written')['id'] as String,
      );
    });
    tearDown(() => w.dispose());

    Future<SolveController> submitted([String text = '对称轴是 x=a']) async {
      final c = await started(w);
      c.setPart('1', text);
      await c.submit();
      return c;
    }

    test('有文字或有笔迹才能提交；只有空白不算', () async {
      final c = await started(w);
      expect(c.canSubmit, isFalse);

      c.setPart('1', '   ');
      expect(c.canSubmit, isFalse);
      c.setPart('1', '对称轴是 x=a');
      expect(c.canSubmit, isTrue);
      c.setPart('1', '');
      expect(c.canSubmit, isFalse);

      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      expect(c.canSubmit, isTrue, reason: '只有笔迹也可以提交');
    });

    test('只能写题目里有的小问；写得太长会被截到上限', () async {
      final c = await started(w);

      c.setPart('9', '没有这个小问');
      expect(c.parts, isEmpty);
      c.setPart('1', 'x' * 5000);
      expect(c.parts['1']!.length, 4000);
    });

    test('分小问的文字按小问顺序同步到云端草稿，没写的小问不发', () async {
      final c = await started(w);

      c.setPart('2', '最小值 -1');
      c.setPart('1', '对称轴 x=a');
      await until(() => w.backend.serverAnswer != null, reason: '草稿没有同步到云端');
      await until(() => c.sync == SaveStatus.saved);

      expect(w.backend.serverAnswer, {
        'parts': [
          {'key': '1', 'text': '对称轴 x=a'},
          {'key': '2', 'text': '最小值 -1'},
        ],
      });
    });

    test('分小问的文字先存在本机，重新打开时恢复', () async {
      final first = await started(w);
      first.setPart('2', '最小值 -1');
      await first.flushNow();

      final saved = await first.drafts.readDraft(w.questionId);
      expect(saved!.parts, {'2': '最小值 -1'});
      first.dispose();

      final second = await started(w);
      expect(second.parts, {'2': '最小值 -1'});
      expect(w.backend.sessionsCreated, 1, reason: '不能重复开会话');
    });

    test('提交：文字去掉首尾空白；结果是待自评，不是对也不是错', () async {
      final c = await submitted('  对称轴是 x=a  ');

      final body = w.backend.bodyOf(
        w.backend.requestsTo('POST', '/submit').single,
      )!;
      expect(body['answer'], {
        'parts': [
          {'key': '1', 'text': '对称轴是 x=a'},
        ],
      });
      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(c.evaluation!.state, EvaluationState.pending);
      expect(c.evaluation!.isCorrect, isNull);
      expect(c.events.single.uncertainty.reasonCode, 'subjective_self_check');
      expect(c.reviewItem, isNull);
    });

    test('只有笔迹也能提交；笔迹没同步上去时先拦住，不让服务端拒绝一个看似空白的答案', () async {
      final c = await started(w);
      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);
      await c.submit();
      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(
        w.backend.bodyOf(
          w.backend.requestsTo('POST', '/submit').single,
        )!['answer'],
        {'parts': <Object>[]},
      );
    });

    test('笔迹还在本机、没同步到云端时，只有笔迹的作答不能提交', () async {
      final c = await started(w);
      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);
      c.ink.beginStroke(0, 20, 20);
      c.ink.extendStroke(80, 80, t: 12);
      c.ink.endStroke();
      w.backend.offline = true;

      await c.submit();

      expect(c.phase, SolvePhase.answering);
      expect(c.actionError, isNotNull);
      expect(w.backend.requestsTo('POST', '/submit'), isEmpty);
      w.backend.offline = false;
    });

    test('提交之前不会去要自查要点', () async {
      final c = await started(w);
      c.setPart('1', '写了');
      await until(() => c.sync == SaveStatus.saved);

      expect(w.backend.requestsTo('GET', '/self-check'), isEmpty);
      expect(c.selfCheck, isNull);
    });

    test('提交之后自动取来自查要点；一条都还没标', () async {
      final c = await submitted();

      expect(c.selfCheck, isNotNull);
      expect(c.selfCheck!.points, isNotEmpty);
      expect(c.selfCheck!.marks, isEmpty);
      expect(c.marks, isEmpty);
      expect(c.selfCheckComplete, isFalse);
      expect(c.selfCheckDirty, isFalse);
    });

    test('逐条标出做到没有；全部标完才能保存；按要点清单的顺序、带幂等键', () async {
      final c = await submitted();
      final points = c.selfCheck!.points;

      await c.saveSelfCheck();
      expect(
        w.backend.requestsTo('PUT', '/self-check'),
        isEmpty,
        reason: '没标完不发',
      );

      for (final point in points.skip(1)) {
        c.markPoint(point.key, SelfCheckLevel.done);
      }
      expect(c.selfCheckComplete, isFalse, reason: '还差一条');
      c.markPoint(points.first.key, SelfCheckLevel.missed);
      expect(c.selfCheckComplete, isTrue);
      expect(c.selfCheckDirty, isTrue);

      await c.saveSelfCheck();

      final request = w.backend.requestsTo('PUT', '/self-check').single;
      expect(request.headers['Idempotency-Key'], isNotNull);
      final sent = (w.backend.bodyOf(request)!['marks'] as List<dynamic>)
          .cast<Map<String, dynamic>>();
      expect(sent.map((m) => m['point_key']), points.map((p) => p.key));
      expect(sent.first['level'], 'missed');
      expect(c.selfCheck!.savedAt, isNotNull);
      expect(c.selfCheck!.summary.missed, 1);
      expect(c.selfCheck!.summary.done, points.length - 1);
      expect(c.selfCheckDirty, isFalse);
      expect(c.phase, SolvePhase.submitted, reason: '自查不改变作答的状态');
      expect(c.evaluation!.state, EvaluationState.pending);
      expect(c.evaluation!.isCorrect, isNull);
    });

    test('改了自评再保存：换新的幂等键；没改就不是待保存的', () async {
      final c = await submitted();
      final points = c.selfCheck!.points;
      for (final point in points) {
        c.markPoint(point.key, SelfCheckLevel.done);
      }
      await c.saveSelfCheck();
      expect(c.selfCheckDirty, isFalse);

      c.markPoint(points.first.key, SelfCheckLevel.partial);
      expect(c.selfCheckDirty, isTrue);
      await c.saveSelfCheck();

      final keys = w.backend
          .requestsTo('PUT', '/self-check')
          .map((r) => r.headers['Idempotency-Key'])
          .toList();
      expect(keys, hasLength(2));
      expect(keys[0], isNot(keys[1]));
      expect(c.selfCheck!.summary.partial, 1);
    });

    test(
      '303A self check A B A is a new intent and server really ends in A',
      () async {
        final c = await submitted();
        final points = c.selfCheck!.points;
        for (final level in [
          SelfCheckLevel.done,
          SelfCheckLevel.partial,
          SelfCheckLevel.done,
        ]) {
          for (final p in points) {
            c.markPoint(p.key, level);
          }
          await c.saveSelfCheck();
        }
        final writes = w.backend.requestsTo('PUT', r'/self-check$').toList();
        expect(
          writes.map((r) => r.headers['Idempotency-Key']).toSet().length,
          3,
        );
        expect(
          w.backend.selfCheckMarks.every((m) => m['level'] == 'done'),
          isTrue,
        );
      },
    );

    test(
      '303A late self check A cannot overwrite locally edited B across restart',
      () async {
        final backend = WorkspaceHeldBackend()
          ..installLearningFlow(questionFixture: 'question_written')
          ..submitFixture = 'submit_written';
        final local = Harness(
          backend: backend,
          questionId:
              backend.fixtures.value('question_written')['id'] as String,
        );
        addTearDown(local.dispose);
        final c = await started(local);
        c.setPart(c.question!.content.subquestions.first.key, 'answer');
        await c.submit();
        for (final point in c.selfCheck!.points) {
          c.markPoint(point.key, SelfCheckLevel.done);
        }
        backend.heldPath = '/api/v1/attempts/${c.attempt!.id}/self-check';
        final saving = c.saveSelfCheck();
        await backend.entered.future;
        for (final point in c.selfCheck!.points) {
          c.markPoint(point.key, SelfCheckLevel.partial);
        }
        backend.heldPath = null;
        backend.release.complete();
        await saving;
        expect(
          c.marks.values.every((m) => m == SelfCheckLevel.partial),
          isTrue,
        );
        expect(c.selfCheckDirty, isTrue);
        c.dispose();
        final restored = await started(local);
        await restored.loadSelfCheck();
        expect(
          restored.marks.values.every((m) => m == SelfCheckLevel.partial),
          isTrue,
        );
        expect(
          backend.selfCheckMarks.every((m) => m['level'] == 'done'),
          isTrue,
        );
      },
    );

    test('保存失败：已标的内容还在，可以再点保存', () async {
      final c = await submitted();
      for (final point in c.selfCheck!.points) {
        c.markPoint(point.key, SelfCheckLevel.done);
      }
      w.backend.failNextOn('/self-check', 503, 'service_unavailable');

      await c.saveSelfCheck();
      expect(c.selfCheckError, isNotNull);
      expect(c.selfCheck!.savedAt, isNull);
      expect(c.selfCheckComplete, isTrue, reason: '标好的没有丢');

      await c.saveSelfCheck();
      expect(c.selfCheckError, isNull);
      expect(c.selfCheck!.savedAt, isNotNull);
    });

    test('取要点失败：作答仍是已提交的，之后可以重试', () async {
      final c = await started(w);
      c.setPart('1', '写了');
      w.backend.failNextOn('/self-check', 503, 'service_unavailable');

      await c.submit();

      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(c.selfCheck, isNull);
      expect(c.selfCheckError, isNotNull);

      await c.loadSelfCheck();
      expect(c.selfCheck, isNotNull);
      expect(c.selfCheckError, isNull);
    });

    test(
      '303A retry does not accept a late self check from the previous attempt',
      () async {
        final backend = WorkspaceHeldBackend()
          ..installLearningFlow(questionFixture: 'question_written')
          ..submitFixture = 'submit_written';
        final local = Harness(
          backend: backend,
          questionId:
              backend.fixtures.value('question_written')['id'] as String,
        );
        addTearDown(local.dispose);
        final c = await started(local);
        c.setPart(c.question!.content.subquestions.first.key, 'answer');
        await c.submit();
        backend.heldPath = '/api/v1/attempts/${c.attempt!.id}/self-check';
        final loading = c.loadSelfCheck();
        await backend.entered.future;
        await c.retry();
        backend.heldPath = null;
        backend.release.complete();
        await loading;
        expect(c.phase, SolvePhase.answering);
        expect(c.selfCheck, isNull);
        expect(c.selfCheckBusy, isFalse);
      },
    );

    test('再试一次：分小问的文字、自评和要点都清掉', () async {
      final c = await submitted();
      c.markPoint(c.selfCheck!.points.first.key, SelfCheckLevel.done);

      await c.retry();

      expect(c.phase, SolvePhase.answering);
      expect(c.parts, isEmpty);
      expect(c.selfCheck, isNull);
      expect(c.marks, isEmpty);
      expect(c.selfCheckError, isNull);
    });

    test('不是解答题就不去要自查要点', () async {
      final c = await started(h);
      c.selectOption('A');
      await c.submit();

      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(h.backend.requestsTo('GET', '/self-check'), isEmpty);
      expect(c.selfCheck, isNull);
    });
  });

  group('实验题', () {
    late Harness e;
    late Map<String, dynamic> question;
    setUp(() {
      final backend = FakeBackend()
        ..submitFixture = 'submit_experiment'
        ..selfCheckFixture = 'self_check_experiment_pending'
        ..installLearningFlow(questionFixture: 'question_experiment');
      question = Fixtures.load().value('question_experiment');
      e = Harness(backend: backend, questionId: question['id'] as String);
    });
    tearDown(() => e.dispose());

    /// 第一张表里留空的格子 v 的四行，加上表 2 的加速度
    void fillTables(SolveController c) {
      c.setCell('t1', 'r1', 'v', '0.400');
      c.setCell('t1', 'r2', 'v', '0.600');
      c.setCell('t1', 'r3', 'v', '0.800');
      c.setCell('t1', 'r4', 'v', '1.00');
      c.setCell('t2', 'r1', 'val', '2.00');
    }

    test('有填写的格子、小问文字或笔迹才能提交；只有空白不算', () async {
      final c = await started(e);
      expect(c.canSubmit, isFalse);

      c.setCell('t1', 'r1', 'v', '   ');
      c.setPart('1', '\n');
      expect(c.canSubmit, isFalse);
      c.setCell('t1', 'r1', 'v', '0.400');
      expect(c.canSubmit, isTrue);
      c.setCell('t1', 'r1', 'v', '');
      expect(c.canSubmit, isFalse);
      c.setPart('2', '用逐差法');
      expect(c.canSubmit, isTrue, reason: '只写文字也可以');
      c.setPart('2', '');

      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      expect(c.canSubmit, isTrue, reason: '只有笔迹也可以提交');
    });

    test('只能填题目里留空的格子；格子的值截到 40 字', () async {
      final c = await started(e);

      c.setCell('t1', 'r1', 'x', '9.99'); // 题目给定的格子
      c.setCell('t1', 'r1', 'seg', 'ZZ');
      c.setCell('t9', 'r1', 'v', '1'); // 不存在的表
      c.setCell('t1', 'r9', 'v', '1');
      c.setCell('t1', 'r1', 'zz', '1');
      expect(c.cells, isEmpty);

      c.setCell('t1', 'r1', 'v', '9' * 60);
      expect(c.cells['t1.r1.v']!.length, 40);
    });

    test('格子和小问按题目里的顺序同步到云端草稿，没填的不发', () async {
      final c = await started(e);

      c.setPart('2', '用逐差法');
      c.setCell('t2', 'r1', 'val', '2.00');
      c.setCell('t1', 'r2', 'v', '0.600');
      c.setCell('t1', 'r1', 'v', '0.400');
      await until(() => e.backend.serverAnswer != null, reason: '草稿没有同步到云端');
      await until(() => c.sync == SaveStatus.saved);

      expect(e.backend.serverAnswer, {
        'cells': [
          {'table': 't1', 'row': 'r1', 'col': 'v', 'value': '0.400'},
          {'table': 't1', 'row': 'r2', 'col': 'v', 'value': '0.600'},
          {'table': 't2', 'row': 'r1', 'col': 'val', 'value': '2.00'},
        ],
        'parts': [
          {'key': '2', 'text': '用逐差法'},
        ],
      });
    });

    test('格子先存在本机，重新打开时恢复；不重复开会话', () async {
      final first = await started(e);
      first.setCell('t1', 'r3', 'v', '0.800');
      await first.flushNow();

      final saved = await first.drafts.readDraft(e.questionId);
      expect(saved!.cells, {'t1.r3.v': '0.800'});
      first.dispose();

      final second = await started(e);
      expect(second.cells, {'t1.r3.v': '0.800'});
      expect(e.backend.sessionsCreated, 1);
    });

    test('提交：格子和文字去掉首尾空白；结果是待自评，不是对也不是错', () async {
      final c = await started(e);
      fillTables(c);
      c.setCell('t1', 'r1', 'v', '  0.400 ');
      c.setPart('1', '  T 等于 0.10 秒  ');
      await c.submit();

      final body = e.backend.bodyOf(
        e.backend.requestsTo('POST', '/submit').single,
      )!;
      expect(body['answer'], {
        'cells': [
          {'table': 't1', 'row': 'r1', 'col': 'v', 'value': '0.400'},
          {'table': 't1', 'row': 'r2', 'col': 'v', 'value': '0.600'},
          {'table': 't1', 'row': 'r3', 'col': 'v', 'value': '0.800'},
          {'table': 't1', 'row': 'r4', 'col': 'v', 'value': '1.00'},
          {'table': 't2', 'row': 'r1', 'col': 'val', 'value': '2.00'},
        ],
        'parts': [
          {'key': '1', 'text': 'T 等于 0.10 秒'},
        ],
      });
      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(c.evaluation!.state, EvaluationState.pending);
      expect(c.evaluation!.isCorrect, isNull);
      expect(c.events.single.uncertainty.reasonCode, 'subjective_self_check');
      expect(c.reviewItem, isNull);
    });

    test('只有笔迹也能提交（笔迹同步上去之后）', () async {
      final c = await started(e);
      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);

      await c.submit();

      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(
        e.backend.bodyOf(
          e.backend.requestsTo('POST', '/submit').single,
        )!['answer'],
        {'cells': <Object>[], 'parts': <Object>[]},
      );
    });

    test('提交之前不会去要自查要点和参考数据；提交之后取到，参考数据只在这时才有', () async {
      final c = await started(e);
      fillTables(c);
      expect(e.backend.requestsTo('GET', '/self-check'), isEmpty);
      expect(c.selfCheck, isNull);

      await c.submit();
      await until(() => c.selfCheck != null, reason: '自查要点没有取到');

      expect(c.selfCheck!.points, isNotEmpty);
      expect(c.selfCheck!.referenceCells, isNotEmpty);
      expect(
        c.selfCheck!.referenceCells.map((cell) => cell.value),
        containsAll(['0.400', '2.00']),
      );
    });

    test('再试一次：格子、文字、笔迹都清空，新建一份作答', () async {
      final c = await started(e);
      fillTables(c);
      c.setPart('1', '写过');
      await c.submit();

      await c.retry();

      expect(c.cells, isEmpty);
      expect(c.parts, isEmpty);
      expect(c.phase, SolvePhase.answering);
      expect(c.selfCheck, isNull);
    });

    test('版本冲突：使用云端稿之后，云端草稿里的格子也回来', () async {
      final c = await started(e);
      c.setCell('t1', 'r1', 'v', '0.4');
      await until(() => c.sync == SaveStatus.saved);
      // 别处把云端草稿改成了另一份
      e.backend.serverRevision = 5;
      e.backend.serverAnswer = {
        'cells': [
          {'table': 't1', 'row': 'r2', 'col': 'v', 'value': '别处写的'},
        ],
      };

      c.setCell('t1', 'r1', 'v', '0.41');
      await until(() => c.sync == SaveStatus.conflict, reason: '没有发现冲突');
      expect(c.cells, {'t1.r1.v': '0.41'}, reason: '本地稿原样保留');
      await c.resolveConflictUseServer();

      expect(c.cells, {'t1.r2.v': '别处写的'});
    });
  });

  group('证明题', () {
    late Harness p;
    late Map<String, dynamic> question;
    setUp(() {
      final backend = FakeBackend()
        ..submitFixture = 'submit_proof'
        ..selfCheckFixture = 'self_check_proof_pending'
        ..installLearningFlow(questionFixture: 'question_proof');
      question = Fixtures.load().value('question_proof');
      p = Harness(backend: backend, questionId: question['id'] as String);
    });
    tearDown(() => p.dispose());

    /// 三步的证明，第三步没写依据。
    void writeProof(SolveController c) {
      c.setStepText(0, '任取 x1<x2');
      c.setStepReason(0, '单调性的定义');
      c.addStep();
      c.setStepText(1, '作差通分');
      c.setStepReason(1, '通分，提公因式');
      c.addStep();
      c.setStepText(2, '所以 f(x1)<f(x2)');
    }

    test('一打开就有一张空白卡片；不是证明题就没有', () async {
      final c = await started(p);
      expect(c.steps, hasLength(1));
      expect(c.steps.single.isBlank, isTrue);

      final other = await started(h);
      expect(other.steps, isEmpty, reason: '单选题没有证明步骤');
    });

    test('至少一步写了文字或有笔迹才能提交；只有依据、只有空白都不算', () async {
      final c = await started(p);
      expect(c.canSubmit, isFalse);

      c.setStepText(0, '  \n');
      expect(c.canSubmit, isFalse);
      c.setStepReason(0, '已知');
      expect(c.canSubmit, isFalse, reason: '只写了依据、没有写这一步的内容');
      c.setStepText(0, '任取 x1<x2');
      expect(c.canSubmit, isTrue, reason: '依据可以不写');
      c.setStepText(0, '');
      c.setStepReason(0, '');
      expect(c.canSubmit, isFalse);

      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      expect(c.canSubmit, isTrue, reason: '只有笔迹也可以提交');
    });

    test('添加、上移、下移、删除：顺序就是证明的顺序', () async {
      final c = await started(p);
      c.setStepText(0, '甲');
      c.addStep();
      c.setStepText(1, '乙');
      c.addStep();
      c.setStepText(2, '丙');
      expect(c.steps.map((s) => s.text), ['甲', '乙', '丙']);

      c.moveStep(2, -1);
      expect(c.steps.map((s) => s.text), ['甲', '丙', '乙']);
      c.moveStep(0, 1);
      expect(c.steps.map((s) => s.text), ['丙', '甲', '乙']);
      c.moveStep(0, -1); // 已经在最前面
      c.moveStep(2, 1); // 已经在最后面
      expect(c.steps.map((s) => s.text), ['丙', '甲', '乙']);

      c.removeStep(1);
      expect(c.steps.map((s) => s.text), ['丙', '乙']);
      c.removeStep(7); // 不存在的步
      c.removeStep(-1);
      expect(c.steps, hasLength(2));
    });

    test('删到只剩一步时把它清成空白，卡片不会消失；依据跟着文字一起挪', () async {
      final c = await started(p);
      c.setStepText(0, '甲');
      c.setStepReason(0, '依据甲');
      c.addStep();
      c.setStepText(1, '乙');
      c.setStepReason(1, '依据乙');

      c.moveStep(1, -1);
      expect(c.steps.first.text, '乙');
      expect(c.steps.first.reason, '依据乙');

      c.removeStep(0);
      c.removeStep(0);
      expect(c.steps, hasLength(1));
      expect(c.steps.single.isBlank, isTrue);
    });

    test('最多 30 步；文字截到 1000 字、依据截到 400 字；不存在的步被忽略', () async {
      final c = await started(p);
      for (var i = 0; i < 40; i++) {
        c.addStep();
      }
      expect(c.steps, hasLength(30));
      expect(c.canAddStep, isFalse);

      c.setStepText(0, '证' * 1500);
      c.setStepReason(0, '依' * 900);
      expect(c.steps.first.text.length, 1000);
      expect(c.steps.first.reason.length, 400);
      c.setStepText(99, '不存在');
      c.setStepReason(-1, '不存在');
      expect(c.steps, hasLength(30));
    });

    test('结构变了（添加、删除、挪动）版本号才加一；写字不加', () async {
      final c = await started(p);
      final start = c.stepsRevision;

      c.setStepText(0, '甲');
      c.setStepReason(0, '依据');
      expect(c.stepsRevision, start);

      c.addStep();
      expect(c.stepsRevision, start + 1);
      c.moveStep(1, -1);
      expect(c.stepsRevision, start + 2);
      c.removeStep(0);
      expect(c.stepsRevision, start + 3);
      c.moveStep(0, -1); // 到头了，什么都没变
      expect(c.stepsRevision, start + 3);
    });

    test('步骤按学生排的顺序同步到云端草稿，空白卡片不发', () async {
      final c = await started(p);
      c.setStepText(0, '第一步');
      c.setStepReason(0, '依据一');
      c.addStep(); // 空白卡片
      c.addStep();
      c.setStepText(2, '第三步');
      await until(() => p.backend.serverAnswer != null, reason: '草稿没有同步到云端');
      await until(() => c.sync == SaveStatus.saved);

      expect(p.backend.serverAnswer, {
        'steps': [
          {'text': '第一步', 'reason': '依据一'},
          {'text': '第三步', 'reason': ''},
        ],
      });
    });

    test('步骤先存在本机（空白卡片也留着），重新打开时恢复；不重复开会话', () async {
      final first = await started(p);
      first.setStepText(0, '任取 x1<x2');
      first.setStepReason(0, '单调性的定义');
      first.addStep();
      first.addStep();
      first.setStepText(2, '结论');
      await first.flushNow();

      final saved = await first.drafts.readDraft(p.questionId);
      expect(saved!.steps.map((s) => (s.text, s.reason)), [
        ('任取 x1<x2', '单调性的定义'),
        ('', ''),
        ('结论', ''),
      ]);
      first.dispose();

      final second = await started(p);
      expect(second.steps.map((s) => s.text), ['任取 x1<x2', '', '结论']);
      expect(second.steps.first.reason, '单调性的定义');
      expect(p.backend.sessionsCreated, 1);
    });

    test('提交：文字和依据去掉首尾空白，空白卡片不发；结果是待自评，不是对也不是错', () async {
      final c = await started(p);
      writeProof(c);
      c.setStepText(0, '  任取 x1<x2  ');
      c.addStep(); // 末尾一张空白卡片
      await c.submit();

      final body = p.backend.bodyOf(
        p.backend.requestsTo('POST', '/submit').single,
      )!;
      expect(body['answer'], {
        'steps': [
          {'text': '任取 x1<x2', 'reason': '单调性的定义'},
          {'text': '作差通分', 'reason': '通分，提公因式'},
          {'text': '所以 f(x1)<f(x2)', 'reason': ''},
        ],
      });
      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(c.evaluation!.state, EvaluationState.pending);
      expect(c.evaluation!.isCorrect, isNull);
      expect(c.events.single.uncertainty.reasonCode, 'subjective_self_check');
      expect(c.reviewItem, isNull);
    });

    test('只有笔迹也能提交（笔迹同步上去之后）', () async {
      final c = await started(p);
      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);

      await c.submit();

      expect(c.phase, SolvePhase.submitted, reason: c.actionError?.toString());
      expect(
        p.backend.bodyOf(
          p.backend.requestsTo('POST', '/submit').single,
        )!['answer'],
        {'steps': <Object>[]},
      );
    });

    test('笔迹还在本机、没同步到云端时，只有笔迹的证明不能提交', () async {
      final c = await started(p);
      c.ink.beginStroke(0, 10, 10);
      c.ink.extendStroke(60, 60, t: 12);
      c.ink.endStroke();
      await until(() => c.sync == SaveStatus.saved);
      c.ink.beginStroke(0, 20, 20);
      c.ink.extendStroke(80, 80, t: 12);
      c.ink.endStroke();
      p.backend.offline = true;

      await c.submit();

      expect(c.phase, SolvePhase.answering);
      expect(c.actionError, isNotNull);
      expect(p.backend.requestsTo('POST', '/submit'), isEmpty);
      p.backend.offline = false;
    });

    test('提交之前不会去要自查要点和参考证明；提交之后取到，参考证明只在这时才有', () async {
      final c = await started(p);
      writeProof(c);
      expect(p.backend.requestsTo('GET', '/self-check'), isEmpty);
      expect(c.selfCheck, isNull);

      await c.submit();
      await until(() => c.selfCheck != null, reason: '自查要点没有取到');

      expect(c.selfCheck!.points, isNotEmpty);
      expect(c.selfCheck!.referenceSteps, isNotEmpty);
      expect(c.selfCheck!.referenceSteps.last.stage, ProofStage.conclusion);
      expect(c.selfCheck!.referenceCells, isEmpty);
    });

    test('再试一次：步骤、笔迹、自评都清空，留一张空白卡片，新建一份作答', () async {
      final c = await started(p);
      writeProof(c);
      await c.submit();
      await until(() => c.selfCheck != null);
      final before = c.stepsRevision;

      await c.retry();

      expect(c.steps, hasLength(1));
      expect(c.steps.single.isBlank, isTrue);
      expect(c.stepsRevision, greaterThan(before));
      expect(c.phase, SolvePhase.answering);
      expect(c.selfCheck, isNull);
      expect(c.canSubmit, isFalse);
    });

    test('版本冲突：使用云端稿之后，云端草稿里的步骤也回来；本地稿原样保留到那时', () async {
      final c = await started(p);
      c.setStepText(0, '本地写的');
      await until(() => c.sync == SaveStatus.saved);
      // 别处把云端草稿改成了另一份
      p.backend.serverRevision = 5;
      p.backend.serverAnswer = {
        'steps': [
          {'text': '别处写的第一步', 'reason': '别处的依据'},
          {'text': '别处写的第二步', 'reason': ''},
        ],
      };

      c.setStepText(0, '本地写的，又改了');
      await until(() => c.sync == SaveStatus.conflict, reason: '没有发现冲突');
      expect(c.steps.single.text, '本地写的，又改了');
      final before = c.stepsRevision;
      await c.resolveConflictUseServer();

      expect(c.steps.map((s) => s.text), ['别处写的第一步', '别处写的第二步']);
      expect(c.steps.first.reason, '别处的依据');
      expect(c.stepsRevision, greaterThan(before));
    });

    test('云端草稿是空的时，采用云端稿之后仍然有一张空白卡片', () async {
      final c = await started(p);
      c.setStepText(0, '本地写的');
      await until(() => c.sync == SaveStatus.saved);
      p.backend.serverRevision = 5;
      p.backend.serverAnswer = null;
      c.setStepText(0, '本地写的，又改了');
      await until(() => c.sync == SaveStatus.conflict);

      await c.resolveConflictUseServer();

      expect(c.steps, hasLength(1));
      expect(c.steps.single.isBlank, isTrue);
    });

    test('只有步骤、没有别的内容的本机草稿不会被当成空草稿丢掉（离线写的）', () async {
      // 先在线打开一次，让题目被缓存；再断网写证明
      final warm = await started(p);
      warm.dispose();
      final fresh = FakeBackend()
        ..submitFixture = 'submit_proof'
        ..sessionOrigin = 'practice'
        ..installLearningFlow(questionFixture: 'question_proof');
      final harness = Harness(
        store: p.store,
        backend: fresh,
        questionId: p.questionId,
      );
      fresh.offline = true;

      final c = await started(harness);
      expect(c.questionFromCache, isTrue);
      c.setStepText(0, '离线时写的');
      await c.flushNow();
      await until(() => c.sync == SaveStatus.offline);
      expect(fresh.sessionsCreated, 0);

      fresh.offline = false;
      await until(() => c.sync == SaveStatus.saved, reason: '恢复网络后应该自动同步');

      expect(fresh.sessionsCreated, 0);
      expect(fresh.serverAnswer, {
        'steps': [
          {'text': '离线时写的', 'reason': ''},
        ],
      });
      harness.dispose();
    });
  });

  group('登录失效', () {
    test('401：通知外层重新登录，未同步的草稿仍在本机', () async {
      final c = await started(h);
      h.backend.failNext = (401, 'unauthenticated');

      c.selectOption('A');
      await c.flushNow();
      await until(() => h.unauthenticated > 0);

      expect(c.authExpired, isTrue);
      expect(await c.drafts.readDraft(h.questionId), isNotNull);
    });
  });

  group('本地数据按用户隔离', () {
    test('另一个用户看不到这个用户的草稿', () async {
      final c = await started(h);
      c.selectOption('A');
      await c.flushNow();

      final other = DraftStore(h.store, 'user-2');
      expect(await other.readDraft(h.questionId), isNull);
      expect(
        await DraftStore(h.store, _user).readDraft(h.questionId),
        isNotNull,
      );
    });
  });
}
