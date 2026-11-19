import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/solve/solve_controller.dart';

import 'support/fake_backend.dart';

void main() {
  test('session-only route attaches a new attempt to the requested session', () async {
    final backend = FakeBackend()..installLearningFlow();
    final api = TutorApiClient(
      ApiCore(
        baseUrl: 'http://127.0.0.1',
        transport: backend,
        tokenProvider: () => 'token',
      ),
    );
    final question =
        backend.fixtures.value('question_single_choice')['id'] as String;
    final original = await api.createSession(
      body: SessionCreate(questionId: question, origin: SessionOrigin.practice),
      idempotencyKey: 'original-session-key',
    );
    backend.sessionResources[original.id] = original.toJson();
    final controller = SolveController(
      api: api,
      store: MemoryStore(),
      userId: 'alice',
      args: SolveArgs(questionId: question, sessionId: original.id),
    );
    addTearDown(controller.dispose);
    await controller.start();
    expect(
      controller.session?.id,
      original.id,
      reason:
          '${controller.failure}; ${controller.actionError}; ${controller.creationBlockedReason}',
    );
    expect(
      controller.attempt?.sessionId,
      original.id,
      reason:
          '${controller.failure}; ${controller.actionError}; ${controller.creationBlockedReason}',
    );
    expect(
      backend.requests.where(
        (r) => r.method == 'POST' && r.uri.path.endsWith('/sessions'),
      ),
      hasLength(1),
    );
    expect(backend.attemptsCreated, 1);
  });

  test(
    'session-only route can read a submitted first attempt on a fresh device',
    () async {
      final backend = FakeBackend()..installLearningFlow();
      final api = TutorApiClient(
        ApiCore(
          baseUrl: 'http://127.0.0.1',
          transport: backend,
          tokenProvider: () => 'token',
        ),
      );
      final question =
          backend.fixtures.value('question_single_choice')['id'] as String;
      final session = await api.createSession(
        body: SessionCreate(
          questionId: question,
          origin: SessionOrigin.practice,
        ),
        idempotencyKey: 'read-session-create',
      );
      final attempt = await api.createAttempt(
        body: AttemptCreate(sessionId: session.id),
        idempotencyKey: 'read-attempt-create',
      );
      await api.submitAttempt(
        attemptId: attempt.id,
        body: SubmitRequest(answer: AnswerPayload(selectedOptions: ['B'])),
        idempotencyKey: 'read-attempt-submit',
      );
      final count = backend.requests.where((r) => r.method == 'POST').length;
      final controller = SolveController(
        api: api,
        store: MemoryStore(),
        userId: 'alice',
        args: SolveArgs(questionId: question, sessionId: session.id),
      );
      addTearDown(controller.dispose);
      await controller.start();
      expect(
        controller.attempt?.id,
        attempt.id,
        reason: '${controller.failure}; ${controller.actionError}',
      );
      expect(controller.phase, SolvePhase.readonly);
      expect(controller.canSubmit, isFalse);
      expect(backend.requests.where((r) => r.method == 'POST').length, count);
    },
  );
  test('session-only route restores cached draft offline without opening a new session', () async {
    final backend = FakeBackend()..installLearningFlow();
    final api = TutorApiClient(
      ApiCore(
        baseUrl: 'http://127.0.0.1',
        transport: backend,
        tokenProvider: () => 'token',
      ),
    );
    final question =
        backend.fixtures.value('question_single_choice')['id'] as String;
    final original = await api.createSession(
      body: SessionCreate(questionId: question, origin: SessionOrigin.practice),
      idempotencyKey: 'offline-session-key',
    );
    final disk = MemoryStore();
    SolveController controller() => SolveController(
      api: api,
      store: disk,
      userId: 'alice',
      args: SolveArgs(questionId: question, sessionId: original.id),
    );
    final first = controller();
    await first.start();
    first.selectOption('A');
    await first.flushNow();
    first.dispose();
    final writes = backend.requests.where((r) => r.method == 'POST').length;
    backend.offline = true;
    final restored = controller();
    addTearDown(restored.dispose);
    await restored.start();
    expect(restored.selected, contains('A'));
    expect(restored.question, isNotNull);
    expect(backend.requests.where((r) => r.method == 'POST').length, writes);
  });
  test('offline input before first attempt attaches to the fixed session without loss', () async {
    final backend = FakeBackend()..installLearningFlow();
    final api = TutorApiClient(
      ApiCore(
        baseUrl: 'http://127.0.0.1',
        transport: backend,
        tokenProvider: () => 'token',
      ),
    );
    final question =
        backend.fixtures.value('question_single_choice')['id'] as String;
    final original = await api.createSession(
      body: SessionCreate(questionId: question, origin: SessionOrigin.practice),
      idempotencyKey: 'unbound-session-key',
    );
    backend.sessionResources[original.id] = original.toJson();
    backend.failNextOn('/attempts', 503, 'service_unavailable');
    final disk = MemoryStore();
    SolveController controller() => SolveController(
      api: api,
      store: disk,
      userId: 'alice',
      args: SolveArgs(questionId: question, sessionId: original.id),
    );
    final first = controller();
    await first.start();
    backend.offline = true;
    first.selectOption('A');
    await first.flushNow();
    first.dispose();
    final restored = controller();
    addTearDown(restored.dispose);
    await restored.start();
    expect(restored.selected, contains('A'));
    backend.offline = false;
    await restored.retryNow();
    expect(
      restored.attempt?.sessionId,
      original.id,
      reason:
          '${restored.failure}; ${restored.actionError}; ${restored.creationBlockedReason}; ${restored.phase}; ${restored.sync}',
    );
    expect(restored.selected, contains('A'));
    expect(backend.serverAnswer?['selected_options'], ['A']);
    expect(
      backend.requests.where(
        (r) => r.method == 'POST' && r.uri.path.endsWith('/sessions'),
      ),
      hasLength(1),
    );
  });
}
