import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/solve/solve_controller.dart';

import 'support/fake_backend.dart';

void main() {
  test('real DONE probe restores readonly actual C without inventing a local submit receipt', () async {
    final capture = jsonDecode(
      File('test/support/fixtures/tutor_done_real_probe.json')
          .readAsStringSync(),
    ) as Map<String, dynamic>;
    final store = MemoryStore();
    for (final entry in (capture['storage'] as Map).entries) {
      store.data[(entry.key as String).replaceFirst('flutter.', '')] =
          jsonDecode(entry.value as String) as String;
    }
    final backend = FakeBackend()..installLearningFlow();
    final responses = (capture['responses'] as List)
        .cast<Map<String, dynamic>>();
    for (final response in responses) {
      backend.on(
        'GET',
        response['path'] as String,
        (_) => okResponse(response['data']),
      );
    }
    final sessionData =
        responses.firstWhere(
              (r) => (r['path'] as String).startsWith('/sessions/'),
            )['data']
            as Map<String, dynamic>;
    final attemptData =
        responses.firstWhere(
              (r) => (r['path'] as String).startsWith('/attempts/'),
            )['data']
            as Map<String, dynamic>;
    final bundleKey = store.data.keys.singleWhere(
      (k) => k.contains('/draft-bundle/'),
    );
    final journalKey = store.data.keys.singleWhere(
      (k) => k.contains('/resource-journal/session/'),
    );
    final journalBefore = store.data[journalKey];
    final controller = SolveController(
      api: TutorApiClient(
        ApiCore(
          baseUrl: 'http://127.0.0.1:8000',
          transport: backend,
          tokenProvider: () => 'local-test-token',
        ),
      ),
      store: store,
      userId: bundleKey.split('/')[1],
      args: SolveArgs(
        questionId: sessionData['question_id'] as String,
        origin: 'practice',
        sessionId: sessionData['id'] as String,
        attemptId: attemptData['id'] as String,
      ),
    );
    addTearDown(controller.dispose);
    await controller.start();
    expect(
      controller.phase,
      SolvePhase.readonly,
      reason: controller.actionError?.toString(),
    );
    expect(controller.session!.state, SessionState.done);
    expect(controller.attempt!.status, AttemptStatus.submitted);
    expect(controller.evaluation, isNull);
    expect(controller.canSubmit, isFalse);
    expect(controller.assistanceAllowed, isFalse);
    expect(controller.events.length, 6);
    expect(store.data[journalKey], journalBefore);
    expect(
      await controller.drafts.readWrite(
        sessionData['question_id'] as String,
        'submit',
      ),
      isNull,
    );
    expect(backend.requests.every((r) => r.method == 'GET'), isTrue);
  });

  test('real browser R2 submitted explicit route preserves prepared review for readonly recovery', () async {
    final capture = jsonDecode(
      File('test/support/fixtures/review_recovery_explicit_r2.json')
          .readAsStringSync(),
    ) as Map<String, dynamic>;
    final store = MemoryStore();
    for (final entry in (capture['storage'] as Map).entries) {
      // SharedPreferences wraps a saved String once in localStorage.
      store.data[(entry.key as String).replaceFirst('flutter.', '')] =
          jsonDecode(entry.value as String) as String;
    }
    final backend = FakeBackend()..installLearningFlow();
    final responses = (capture['responses'] as List)
        .cast<Map<String, dynamic>>();
    for (final response in responses) {
      backend.on(
        'GET',
        response['path'] as String,
        (_) => okResponse(response['data']),
      );
    }
    final sessionData =
        responses.firstWhere(
              (r) => (r['path'] as String).startsWith('/sessions/'),
            )['data']
            as Map<String, dynamic>;
    final attemptData =
        responses.firstWhere(
              (r) => (r['path'] as String).startsWith('/attempts/'),
            )['data']
            as Map<String, dynamic>;
    final bundleKey = store.data.keys.singleWhere(
      (k) => k.contains('/draft-bundle/'),
    );
    final reviewKey = store.data.keys.singleWhere(
      (k) => k.contains('/resource-journal/review/'),
    );
    final bundleBefore = store.data[bundleKey];
    final reviewBefore = store.data[reviewKey];
    final owner = bundleKey.split('/')[1];
    final controller = SolveController(
      api: TutorApiClient(
        ApiCore(
          baseUrl: 'http://127.0.0.1:8000',
          transport: backend,
          tokenProvider: () => 'local-test-token',
        ),
      ),
      store: store,
      userId: owner,
      args: SolveArgs(
        questionId: sessionData['question_id'] as String,
        origin: 'review',
        reviewItemId: sessionData['review_item_id'] as String,
        sessionId: sessionData['id'] as String,
        attemptId: attemptData['id'] as String,
      ),
    );
    addTearDown(controller.dispose);
    await controller.start();
    expect(
      controller.phase,
      SolvePhase.submitted,
      reason: controller.actionError?.toString(),
    );
    expect(controller.localSaveFailed, isFalse);
    expect(controller.needsReviewRecovery, isTrue);
    expect(controller.canSubmit, isFalse);
    expect(controller.selected, {'B'});
    expect(controller.reviewState!.stage, 1);
    expect(backend.requests.every((r) => r.method == 'GET'), isTrue);
    expect(store.data[bundleKey], bundleBefore);
    expect(store.data[reviewKey], reviewBefore);
  });
}
