import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/solve/draft_store.dart';

import 'support/fake_backend.dart';

void main() {
  late MemoryStore memory;
  late DraftStore root;
  late DraftStore workspace;
  late Question question;
  late Map<String, dynamic> body;
  late String localId;

  DraftCreationCommand command({
    String phase = 'session_prepared',
    int generation = 1,
    String? sessionId,
    String? attemptId,
    Map<String, dynamic>? sessionBody,
    Map<String, dynamic>? attemptBody,
    String intentId = 'intent-one',
  }) => DraftCreationCommand(
    intentId: intentId,
    generation: generation,
    phase: phase,
    sessionKey: 'session-fixed',
    attemptKey: 'attempt-fixed',
    sessionBody: sessionBody ?? body,
    attemptBody: attemptBody,
    sessionId: sessionId,
    attemptId: attemptId,
    questionVersion: sessionId == null ? null : question.version,
  );

  setUp(() async {
    memory = MemoryStore();
    root = DraftStore(memory, 'owner');
    question = Question.fromJson(
      Fixtures.load().value('question_single_choice'),
    );
    body = {
      ...SessionCreate(
        questionId: question.id,
        origin: SessionOrigin.practice,
      ).toJson(),
      'expected_question_version': question.version,
    };
    localId = await root.readOrCreateLocalId(question.id);
    workspace = root.forLocal(localId);
    await workspace.claimScope(question.id);
    await workspace.saveWorkspaceContext(
      question.id,
      DraftWorkspaceContext(
        workspaceId: localId,
        question: question,
        sessionBody: body,
      ),
    );
  });

  test('prepared keys and complete bodies survive restart, account and scope isolated', () async {
    await workspace.prepareCreation(question.id, command());
    final reopened = DraftStore(memory, 'owner').forLocal(localId);
    final persisted = (await reopened.readCreation(question.id))!;
    expect(persisted.sessionKey, 'session-fixed');
    expect(persisted.attemptKey, 'attempt-fixed');
    expect(persisted.sessionBody, body);
    expect(persisted.phase, 'session_prepared');
    expect(
      await DraftStore(
        memory,
        'another',
      ).forLocal(localId).readCreation(question.id),
      isNull,
    );
    expect(
      await root.forLocal('other-workspace').readCreation(question.id),
      isNull,
    );
  });

  test(
    'disk failure before request preparation leaves no command to send',
    () async {
      memory.failWrites = true;
      await expectLater(
        workspace.prepareCreation(question.id, command()),
        throwsStateError,
      );
      memory.failWrites = false;
      expect(await workspace.readCreation(question.id), isNull);
    },
  );

  test('session result disk failure preserves original prepared request for replay', () async {
    await workspace.prepareCreation(question.id, command());
    memory.failWrites = true;
    await expectLater(
      workspace.advanceCreation(
        question.id,
        command(phase: 'session_known', generation: 2, sessionId: 'session-1'),
        expectedGeneration: 1,
      ),
      throwsStateError,
    );
    memory.failWrites = false;
    final recovered = (await workspace.readCreation(question.id))!;
    expect(recovered.phase, 'session_prepared');
    expect(recovered.sessionBody, body);
    expect(recovered.sessionKey, 'session-fixed');
  });

  test('CAS rejects stale generation, changed body and skipped stages without altering raw', () async {
    await workspace.prepareCreation(question.id, command());
    final original = Map<String, String>.of(memory.data);
    await expectLater(
      workspace.advanceCreation(
        question.id,
        command(phase: 'session_known', generation: 2, sessionId: 's'),
        expectedGeneration: 9,
      ),
      throwsStateError,
    );
    await expectLater(
      workspace.advanceCreation(
        question.id,
        command(
          phase: 'session_known',
          generation: 2,
          sessionId: 's',
          sessionBody: {...body, 'origin': 'review'},
        ),
        expectedGeneration: 1,
      ),
      throwsStateError,
    );
    await expectLater(
      workspace.advanceCreation(
        question.id,
        command(
          phase: 'attempt_known',
          generation: 2,
          sessionId: 's',
          attemptId: 'a',
        ),
        expectedGeneration: 1,
      ),
      throwsStateError,
    );
    expect(memory.data, original);
  });

  test('new owner lease rejects late response from prior controller', () async {
    await workspace.prepareCreation(question.id, command());
    final current = root.forLocal(localId);
    await current.claimScope(question.id);
    await expectLater(
      workspace.advanceCreation(
        question.id,
        command(phase: 'session_known', generation: 2, sessionId: 'late'),
        expectedGeneration: 1,
      ),
      throwsStateError,
    );
    expect(
      (await current.readCreation(question.id))!.phase,
      'session_prepared',
    );
  });

  test(
    'context version cannot be replaced by newest network question',
    () async {
      final changed = Question.fromJson({
        ...question.toJson(),
        'version': question.version + 1,
      });
      final original = Map<String, String>.of(memory.data);
      await expectLater(
        workspace.saveWorkspaceContext(
          question.id,
          DraftWorkspaceContext(
            workspaceId: localId,
            question: changed,
            sessionBody: {
              ...body,
              'expected_question_version': changed.version,
            },
          ),
        ),
        throwsStateError,
      );
      expect(memory.data, original);
      expect(
        (await workspace.readWorkspaceContext(question.id))!.question.version,
        question.version,
      );
    },
  );

  test(
    'old input without reliable context cannot acquire a version from latest',
    () async {
      final old = root.forLocal('old-unversioned');
      await old.writeDraft(
        LocalDraft(
          questionId: question.id,
          selected: const ['C'],
          savedAt: DateTime.utc(2026),
          dirty: true,
        ),
      );
      expect(await old.readWorkspaceContext(question.id), isNull);
      await expectLater(
        old.saveWorkspaceContext(
          question.id,
          DraftWorkspaceContext(
            workspaceId: 'old-unversioned',
            question: question,
            sessionBody: body,
          ),
        ),
        throwsStateError,
      );
      expect((await old.readDraft(question.id))!.selected, ['C']);
    },
  );

  test(
    'unknown bundle raw blocks command replacement and remains byte-identical',
    () async {
      final key = 'u/owner/draft-bundle/${question.id}';
      memory.data[key] = jsonEncode({'v': 100, 'evidence': 'keep exactly'});
      final original = memory.data[key];
      await expectLater(
        workspace.prepareCreation(question.id, command()),
        throwsFormatException,
      );
      expect(memory.data[key], original);
    },
  );
  Future<void> prepareAttemptKnown() async {
    await workspace.prepareCreation(question.id, command());
    await workspace.advanceCreation(
      question.id,
      command(phase: 'session_known', generation: 2, sessionId: 'session-1'),
      expectedGeneration: 1,
    );
    await workspace.advanceCreation(
      question.id,
      command(
        phase: 'attempt_prepared',
        generation: 3,
        sessionId: 'session-1',
        attemptBody: {'session_id': 'session-1'},
      ),
      expectedGeneration: 2,
    );
  }

  test(
    'attempt result failure retains fixed prepared attempt body and key',
    () async {
      await prepareAttemptKnown();
      memory.failWrites = true;
      await expectLater(
        workspace.advanceCreation(
          question.id,
          command(
            phase: 'attempt_known',
            generation: 4,
            sessionId: 'session-1',
            attemptId: 'attempt-1',
            attemptBody: {'session_id': 'session-1'},
          ),
          expectedGeneration: 3,
        ),
        throwsStateError,
      );
      memory.failWrites = false;
      final persisted = (await workspace.readCreation(question.id))!;
      expect(persisted.phase, 'attempt_prepared');
      expect(persisted.attemptBody, {'session_id': 'session-1'});
      expect(persisted.attemptKey, 'attempt-fixed');
    },
  );

  test('attach commits target active consumed source and completed command together', () async {
    await prepareAttemptKnown();
    await workspace.advanceCreation(
      question.id,
      command(
        phase: 'attempt_known',
        generation: 4,
        sessionId: 'session-1',
        attemptId: 'attempt-1',
        attemptBody: {'session_id': 'session-1'},
      ),
      expectedGeneration: 3,
    );
    final local = LocalDraft(
      questionId: question.id,
      selected: const ['C'],
      savedAt: DateTime.utc(2026),
      dirty: true,
    );
    await workspace.writeDraft(local);
    final target = LocalDraft.fromJson({
      ...local.toJson(),
      'sessionId': 'session-1',
      'attemptId': 'attempt-1',
    });
    memory.failWrites = true;
    await expectLater(
      workspace.attachCreation(
        target,
        intentId: 'intent-one',
        expectedGeneration: 4,
      ),
      throwsStateError,
    );
    memory.failWrites = false;
    expect((await workspace.readCreation(question.id))!.phase, 'attempt_known');
    expect(await root.readActive(question.id), isNull);
    expect((await workspace.readDraft(question.id))!.selected, ['C']);
    await workspace.attachCreation(
      target,
      intentId: 'intent-one',
      expectedGeneration: 4,
    );
    expect((await workspace.readCreation(question.id))!.phase, 'attached');
    expect((await root.readActive(question.id))!.attemptId, 'attempt-1');
    expect(await workspace.readDraft(question.id), isNull);
    final attached = root.forAttempt('attempt-1');
    expect((await attached.readDraft(question.id))!.selected, ['C']);
    expect(
      (await attached.readWorkspaceContext(question.id))!.trustedSessionId,
      'session-1',
    );
    expect((await attached.readCreation(question.id))!.phase, 'attached');
  });

  test('explicit new workspace preserves old input and command but owns future default', () async {
    await workspace.prepareCreation(question.id, command());
    await workspace.writeDraft(
      LocalDraft(
        questionId: question.id,
        selected: const ['A'],
        savedAt: DateTime.utc(2026),
      ),
    );
    final next = await workspace.newWorkspace(question.id);
    expect(await root.readOrCreateLocalId(question.id), next);
    expect(await root.readActive(question.id), isNull);
    expect((await root.forLocal(localId).readDraft(question.id))!.selected, [
      'A',
    ]);
    expect(
      (await root.forLocal(localId).readCreation(question.id))!.sessionKey,
      'session-fixed',
    );
    expect(await root.forLocal(next).readWorkspaceContext(question.id), isNull);
  });
  test('damaged numeric source versions are rejected without normalizing raw', () async {
    final key = 'u/owner/draft-bundle/${question.id}';
    final original = memory.data[key]!;
    for (final version in [1.0, 1.5, true, null, -1]) {
      final json = jsonDecode(original) as Map;
      json['workspaceContexts']['local/$localId']['sessionBody']['expected_question_version'] =
          version;
      final raw = jsonEncode(json);
      memory.data[key] = raw;
      await expectLater(
        workspace.readWorkspaceContext(question.id),
        throwsFormatException,
      );
      expect(memory.data[key], raw);
    }
  });

  test('attempt body corruption cannot be silently regenerated from session id', () async {
    await prepareAttemptKnown();
    final key = 'u/owner/draft-bundle/${question.id}';
    final json = jsonDecode(memory.data[key]!) as Map;
    json['creationIntents']['local/$localId']['history']['intent-one']['attemptBody']['session_id'] =
        'different';
    final raw = jsonEncode(json);
    memory.data[key] = raw;
    await expectLater(workspace.readCreation(question.id), throwsStateError);
    expect(memory.data[key], raw);
  });
  test('context scope and history map keys cannot redirect trusted origin or intent', () async {
    await workspace.prepareCreation(question.id, command());
    final key = 'u/owner/draft-bundle/${question.id}';
    final original = memory.data[key]!;
    for (final tamper in [0, 1]) {
      final json = jsonDecode(original) as Map;
      if (tamper == 0) {
        json['workspaceContexts']['local/$localId']['workspaceId'] = 'other';
      } else {
        json['creationIntents']['local/$localId']['history']['intent-one']['intentId'] =
            'other';
      }
      final raw = jsonEncode(json);
      memory.data[key] = raw;
      await expectLater(
        workspace.readCreation(question.id),
        throwsFormatException,
      );
      await expectLater(
        workspace.prepareCreation(question.id, command()),
        throwsFormatException,
      );
      expect(memory.data[key], raw);
    }
  });
  test(
    'late attachment from A cannot replace explicit selection of C',
    () async {
      await prepareAttemptKnown();
      await workspace.advanceCreation(
        question.id,
        command(
          phase: 'attempt_known',
          generation: 4,
          sessionId: 'session-1',
          attemptId: 'attempt-A',
          attemptBody: {'session_id': 'session-1'},
        ),
        expectedGeneration: 3,
      );
      final local = LocalDraft(
        questionId: question.id,
        selected: const ['A'],
        savedAt: DateTime.utc(2026),
      );
      await workspace.writeDraft(local);
      await root
          .forAttempt('C')
          .writeActive(
            question.id,
            const ActiveRef(sessionId: 'session-C', attemptId: 'C'),
          );
      final target = LocalDraft.fromJson({
        ...local.toJson(),
        'sessionId': 'session-1',
        'attemptId': 'attempt-A',
      });
      await workspace.attachCreation(
        target,
        intentId: 'intent-one',
        expectedGeneration: 4,
      );
      expect((await root.readActive(question.id))!.attemptId, 'C');
      expect((await workspace.readDraft(question.id))!.selected, ['A']);
    },
  );
  test(
    'selection CAS rejects same-scope late write after C navigation',
    () async {
      final captured = await workspace.readActiveEpoch(question.id);
      await root
          .forAttempt('C')
          .writeActive(
            question.id,
            const ActiveRef(sessionId: 'sC', attemptId: 'C'),
          );
      expect(
        await workspace.writeActive(
          question.id,
          const ActiveRef(sessionId: 'sA', attemptId: 'A'),
          expectedEpoch: captured,
        ),
        isFalse,
      );
      expect((await root.readActive(question.id))!.attemptId, 'C');
    },
  );
  test(
    'legacy command without captured selection epoch never auto-activates',
    () async {
      await prepareAttemptKnown();
      await workspace.advanceCreation(
        question.id,
        command(
          phase: 'attempt_known',
          generation: 4,
          sessionId: 'session-1',
          attemptId: 'attempt-A',
          attemptBody: {'session_id': 'session-1'},
        ),
        expectedGeneration: 3,
      );
      final source = LocalDraft(
        questionId: question.id,
        selected: const ['A'],
        savedAt: DateTime.utc(2026),
      );
      await workspace.writeDraft(source);
      final key = 'u/owner/draft-bundle/${question.id}';
      final json = jsonDecode(memory.data[key]!) as Map;
      json.remove('activeEpoch');
      json['creationIntents']['local/$localId']['history']['intent-one'].remove(
        'activationEpoch',
      );
      memory.data[key] = jsonEncode(json);
      expect(await workspace.readActiveEpoch(question.id), 0);
      expect(
        await workspace.attachCreation(
          LocalDraft.fromJson({
            ...source.toJson(),
            'sessionId': 'session-1',
            'attemptId': 'attempt-A',
          }),
          intentId: 'intent-one',
          expectedGeneration: 4,
        ),
        isFalse,
      );
      expect(await root.readActive(question.id), isNull);
      expect(
        (await workspace.readCopyReferences(question.id)).single.attemptId,
        'attempt-A',
      );
    },
  );
  test('captured epoch cannot be refreshed after selecting C', () async {
    await workspace.prepareCreation(question.id, command());
    await root
        .forAttempt('C')
        .writeActive(
          question.id,
          const ActiveRef(sessionId: 'sC', attemptId: 'C'),
        );
    final original = Map<String, String>.of(memory.data);
    final changed = DraftCreationCommand.fromJson({
      ...command(
        phase: 'session_known',
        generation: 2,
        sessionId: 's',
      ).toJson(),
      'activationEpoch': await root.readActiveEpoch(question.id),
    });
    await expectLater(
      workspace.advanceCreation(question.id, changed, expectedGeneration: 1),
      throwsStateError,
    );
    expect(memory.data, original);
    final blocked = DraftCreationCommand.fromJson({
      ...command(phase: 'blocked', generation: 2).toJson(),
      'resumePhase': 'session_prepared',
      'blockedReason': 'offline',
      'activationEpoch': 1,
    });
    await expectLater(
      workspace.advanceCreation(question.id, blocked, expectedGeneration: 1),
      throwsStateError,
    );
    expect(memory.data, original);
    await workspace.advanceCreation(
      question.id,
      DraftCreationCommand.fromJson({
        ...blocked.toJson(),
        'activationEpoch': null,
      }),
      expectedGeneration: 1,
    );
    final beforeResume = Map<String, String>.of(memory.data);
    await expectLater(
      workspace.advanceCreation(
        question.id,
        DraftCreationCommand.fromJson({
          ...command(generation: 3).toJson(),
          'activationEpoch': 1,
        }),
        expectedGeneration: 2,
      ),
      throwsStateError,
    );
    expect(memory.data, beforeResume);
    await workspace.advanceCreation(
      question.id,
      command(generation: 3),
      expectedGeneration: 2,
    );
    expect((await workspace.readCreation(question.id))!.activationEpoch, 0);
  });

  test('late result retains original context for offline opening', () async {
    await prepareAttemptKnown();
    await workspace.advanceCreation(
      question.id,
      command(
        phase: 'attempt_known',
        generation: 4,
        sessionId: 'session-1',
        attemptId: 'attempt-A',
        attemptBody: {'session_id': 'session-1'},
      ),
      expectedGeneration: 3,
    );
    final source = LocalDraft(
      questionId: question.id,
      selected: const ['A'],
      savedAt: DateTime.utc(2026),
    );
    await workspace.writeDraft(source);
    await root
        .forAttempt('C')
        .writeActive(
          question.id,
          const ActiveRef(sessionId: 'sC', attemptId: 'C'),
        );
    final target = LocalDraft.fromJson({
      ...source.toJson(),
      'sessionId': 'session-1',
      'attemptId': 'attempt-A',
    });
    final before = Map<String, String>.of(memory.data);
    memory.failWrites = true;
    await expectLater(
      workspace.attachCreation(
        target,
        intentId: 'intent-one',
        expectedGeneration: 4,
      ),
      throwsStateError,
    );
    memory.failWrites = false;
    expect(memory.data, before);
    expect(
      await workspace.attachCreation(
        target,
        intentId: 'intent-one',
        expectedGeneration: 4,
      ),
      isFalse,
    );
    final reopened = DraftStore(memory, 'owner').forAttempt('attempt-A');
    expect(await reopened.readWorkspaceContext(question.id), isNotNull);
    expect(
      (await reopened.readWorkspaceContext(question.id))!.question.toJson(),
      question.toJson(),
    );
    expect((await reopened.readDraft(question.id))!.selected, ['A']);
    expect((await reopened.readCreation(question.id))!.attemptId, 'attempt-A');
    expect((await workspace.readDraft(question.id))!.selected, ['A']);
    expect((await root.readActive(question.id))!.attemptId, 'C');
    final edited = target.toJson();
    (edited['answer'] as Map)['selected'] = ['B'];
    await reopened.writeDraft(LocalDraft.fromJson(edited));
    await workspace.attachCreation(
      target,
      intentId: 'intent-one',
      expectedGeneration: 4,
    );
    expect((await reopened.readDraft(question.id))!.selected, ['B']);
    expect((await workspace.readCreation(question.id))!.phase, 'attempt_known');
  });

  for (final legacy in [true, false]) {
    test(
      'copy result persists without activation eligibility legacy=$legacy',
      () async {
        final sourceStore = root.forAttempt('source');
        await sourceStore.claimScope(question.id);
        final source = LocalDraft(
          questionId: question.id,
          sessionId: 'copy-session',
          attemptId: 'source',
          selected: const ['A'],
          savedAt: DateTime.utc(2026),
        );
        await sourceStore.writeDraft(source);
        await sourceStore.archivePair(
          question.id,
          source,
          source,
          pending: true,
        );
        await sourceStore.savePendingCopy(
          question.id,
          PendingDraftCopy(
            snapshot: source,
            sourceAttemptId: 'source',
            observedRevision: 0,
            idempotencyKey: 'copy-fixed',
            recoveryGeneration: 1,
          ),
        );
        final key = 'u/owner/draft-bundle/${question.id}';
        if (legacy) {
          final json = jsonDecode(memory.data[key]!) as Map;
          json['pending']['attempt/source'].remove('activationEpoch');
          memory.data[key] = jsonEncode(json);
        } else {
          await root
              .forAttempt('C')
              .writeActive(
                question.id,
                const ActiveRef(sessionId: 'sC', attemptId: 'C'),
              );
        }
        final copy = LocalDraft.fromJson({
          ...source.toJson(),
          'attemptId': 'copy',
        });
        expect(
          await sourceStore.completePendingCopy(
            question.id,
            idempotencyKey: 'copy-fixed',
            copy: copy,
          ),
          isFalse,
        );
        final json = jsonDecode(memory.data[key]!) as Map;
        expect(json['pending']['attempt/source']['completedAttemptId'], 'copy');
        expect(
          json['pending']['attempt/source']['activationEpoch'],
          legacy ? null : 0,
        );
        expect(
          (await root.forAttempt('copy').readDraft(question.id))!.selected,
          ['A'],
        );
        const selected = ActiveRef(
          sessionId: 'copy-session',
          attemptId: 'copy',
        );
        final beforeSelection = Map<String, String>.of(memory.data);
        await expectLater(
          sourceStore.acknowledgeCopySelection(
            question.id,
            idempotencyKey: 'copy-fixed',
            selectedRef: selected,
          ),
          throwsStateError,
        );
        expect(memory.data, beforeSelection);
        await root.forAttempt('copy').writeActive(question.id, selected);
        final beforeAck = Map<String, String>.of(memory.data);
        for (final ref in [
          const ActiveRef(sessionId: 'wrong-session', attemptId: 'copy'),
          const ActiveRef(sessionId: 'copy-session', attemptId: 'source'),
          const ActiveRef(sessionId: 'copy-session', attemptId: 'other'),
        ]) {
          await expectLater(
            sourceStore.acknowledgeCopySelection(
              question.id,
              idempotencyKey: 'copy-fixed',
              selectedRef: ref,
            ),
            throwsStateError,
          );
          expect(memory.data, beforeAck);
        }
        await expectLater(
          sourceStore.acknowledgeCopySelection(
            question.id,
            idempotencyKey: 'wrong-key',
            selectedRef: selected,
          ),
          throwsStateError,
        );
        expect(memory.data, beforeAck);
        final recoveryKey =
            'u/owner/draft-recovery/${question.id}/attempt/source';
        final recoveryRaw = memory.data[recoveryKey]!;
        final corrupted = jsonDecode(recoveryRaw) as Map;
        corrupted['generation'] = 2;
        memory.data[recoveryKey] = jsonEncode(corrupted);
        await expectLater(
          sourceStore.acknowledgeCopySelection(
            question.id,
            idempotencyKey: 'copy-fixed',
            selectedRef: selected,
          ),
          throwsStateError,
        );
        expect(memory.data[key], beforeAck[key]);
        memory.data[recoveryKey] = recoveryRaw;
        memory.failWrites = true;
        await expectLater(
          sourceStore.acknowledgeCopySelection(
            question.id,
            idempotencyKey: 'copy-fixed',
            selectedRef: selected,
          ),
          throwsStateError,
        );
        memory.failWrites = false;
        expect(memory.data, beforeAck);
        await sourceStore.acknowledgeCopySelection(
          question.id,
          idempotencyKey: 'copy-fixed',
          selectedRef: selected,
        );
        expect(await sourceStore.readPendingCopy(question.id), isNull);
        expect((await sourceStore.readDraft(question.id))!.selected, ['A']);
        expect(memory.data[recoveryKey], recoveryRaw);
        await sourceStore.resolveRecovery(question.id, expectedGeneration: 1);
        expect((await sourceStore.readRecovery(question.id))!.pending, isFalse);
      },
    );
  }
  test(
    'retained workspace ids remain discoverable and owner isolated',
    () async {
      await workspace.writeDraft(
        LocalDraft(
          questionId: question.id,
          selected: const ['A'],
          savedAt: DateTime.utc(2026),
        ),
      );
      final next = await workspace.newWorkspace(question.id);
      expect(
        await root.listLocalWorkspaceIds(question.id),
        containsAll([localId, next]),
      );
      expect(
        await DraftStore(memory, 'other').listLocalWorkspaceIds(question.id),
        isEmpty,
      );
      expect(await root.listLocalWorkspaceIds('other-question'), isEmpty);
    },
  );
  for (final savedToScope in [false, true]) {
    test(
      'explicit new workspace never inherits retained unknown legacy input saved=$savedToScope',
      () async {
        final memory = MemoryStore();
        final root = DraftStore(memory, 'legacy-owner');
        final legacy = LocalDraft(
          questionId: question.id,
          selected: const ['C'],
          savedAt: DateTime.utc(2026),
        );
        await root.writeDraft(legacy);
        final legacyKey = 'u/legacy-owner/draft/${question.id}';
        final originalRaw = memory.data[legacyKey];
        final oldId = await root.readOrCreateLocalId(question.id);
        final old = root.forLocal(oldId);
        await old.claimScope(question.id);
        expect((await old.readDraft(question.id))!.selected, ['C']);
        if (savedToScope) await old.writeDraft(legacy);
        final other = root.forLocal('other');
        await other.writeDraft(
          LocalDraft(
            questionId: question.id,
            selected: const ['B'],
            savedAt: DateTime.utc(2026),
          ),
        );
        final beforeNewWorkspace = Map<String, String>.of(memory.data);
        memory.failWrites = true;
        await expectLater(old.newWorkspace(question.id), throwsStateError);
        memory.failWrites = false;
        expect(memory.data, beforeNewWorkspace);
        expect((await old.readDraft(question.id))!.selected, ['C']);
        final next = await old.newWorkspace(question.id);
        final fresh = root.forLocal(next);
        expect(await fresh.readDraft(question.id), isNull);
        expect((await old.readDraft(question.id))!.selected, ['C']);
        expect(memory.data[legacyKey], originalRaw);
        expect((await other.readDraft(question.id))!.selected, ['B']);
        final latest = Question.fromJson({
          ...question.toJson(),
          'version': question.version + 1,
        });
        await fresh.saveWorkspaceContext(
          question.id,
          DraftWorkspaceContext(
            workspaceId: next,
            question: latest,
            sessionBody: {...body, 'expected_question_version': latest.version},
          ),
        );
        expect(
          (await fresh.readWorkspaceContext(question.id))!.question.version,
          latest.version,
        );
        expect(await fresh.readDraft(question.id), isNull);
        expect(
          await root.listLocalWorkspaceIds(question.id),
          containsAll([oldId, next, 'other']),
        );
        await fresh.writeDraft(
          LocalDraft(
            questionId: question.id,
            selected: const ['A'],
            savedAt: DateTime.utc(2026),
          ),
        );
        expect((await fresh.readDraft(question.id))!.selected, ['A']);
        expect((await old.readDraft(question.id))!.selected, ['C']);
      },
    );
  }
}
