import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/solve/draft_store.dart';

import 'support/fake_backend.dart';

void main() {
  late MemoryStore memory;
  late DraftStore store;
  late LocalDraft source;
  late Question question;

  Map<String, dynamic> syncBody() => DraftSync(
    baseRevision: source.baseRevision,
    answer: source.asServer().answer,
    strokes: source.strokes,
  ).toJson();

  Map<String, dynamic> submitResult(String attemptId, String sessionId) {
    final result = Fixtures.load().value('submit_correct');
    (result['attempt'] as Map)['id'] = attemptId;
    (result['attempt'] as Map)['session_id'] = sessionId;
    (result['session'] as Map)['id'] = sessionId;
    (result['session'] as Map)['question_id'] = question.id;
    (result['session'] as Map)['question_version'] = question.version;
    for (final event in result['events'] as List) {
      event['session_id'] = sessionId;
      event['meta']['question_id'] = question.id;
      event['meta']['question_version'] = question.version;
    }
    return result;
  }

  setUp(() async {
    memory = MemoryStore();
    final fixtures = Fixtures.load();
    question = Question.fromJson(fixtures.value('question_single_choice'));
    final sid = fixtures.value('session_created')['id'] as String;
    final aid = fixtures.value('attempt_created')['id'] as String;
    store = DraftStore(memory, 'owner').forAttempt(aid);
    await store.claimScope(question.id);
    await store.saveWorkspaceContext(
      question.id,
      DraftWorkspaceContext(
        workspaceId: aid,
        question: question,
        trustedSessionId: sid,
        sessionBody: SessionCreate(
          questionId: question.id,
          origin: SessionOrigin.practice,
          expectedQuestionVersion: question.version,
        ).toJson(),
      ),
    );
    source = LocalDraft(
      questionId: question.id,
      sessionId: sid,
      attemptId: aid,
      selected: const ['A'],
      dirty: true,
      savedAt: DateTime.utc(2026),
    );
    await store.writeDraft(source);
    await store.writeActive(
      question.id,
      ActiveRef(sessionId: sid, attemptId: aid),
    );
  });

  test(
    'full immutable sync command and edit generation survive restart',
    () async {
      final command = await store.prepareWrite(
        question.id,
        lane: 'draft_sync',
        body: syncBody(),
        sourceSnapshot: source,
      );
      final reopened = DraftStore(
        memory,
        'owner',
      ).forAttempt(source.attemptId!);
      final restored = (await reopened.readWrite(question.id, 'draft_sync'))!;
      expect(restored.body, syncBody());
      expect(restored.idempotencyKey, command.idempotencyKey);
      expect(restored.sourceSnapshot.toJson(), source.toJson());
      expect(
        restored.editGeneration,
        (await reopened.readEditState(question.id)).draftGeneration,
      );
      final raw = Map<String, String>.of(memory.data);
      await expectLater(
        store.prepareWrite(
          question.id,
          lane: 'draft_sync',
          body: {...syncBody(), 'base_revision': 99},
          sourceSnapshot: source,
        ),
        throwsStateError,
      );
      expect(memory.data, raw);
    },
  );

  test(
    'sync receipt preserves B dirty and its higher known revision',
    () async {
      final command = await store.prepareWrite(
        question.id,
        lane: 'draft_sync',
        body: syncBody(),
        sourceSnapshot: source,
      );
      final b = source.toJson();
      (b['answer'] as Map)['selected'] = ['B'];
      b['baseRevision'] = 5;
      await store.writeDraft(LocalDraft.fromJson(b));
      final known = await store.recordWriteResult(
        question.id,
        lane: 'draft_sync',
        intentId: command.intentId,
        expectedGeneration: command.generation,
        result: {...source.asServer().toJson(), 'revision': 1},
      );
      final ack = await store.ackDraftSync(
        question.id,
        intentId: known.intentId,
        expectedGeneration: known.generation,
      );
      expect(ack.current, isFalse);
      expect(ack.revision, 5);
      expect(ack.draft!.selected, ['B']);
      expect(ack.draft!.dirty, isTrue);
    },
  );

  for (final staleSelection in [false, true]) {
    test(
      'submit freezes A and continuation activation is atomic stale=$staleSelection',
      () async {
        final sync = await store.prepareWrite(
          question.id,
          lane: 'draft_sync',
          body: syncBody(),
          sourceSnapshot: source,
        );
        final pending = await store.prepareSubmit(
          question.id,
          sourceSnapshot: source,
          answer: source.asServer().answer!.toJson(),
          elapsedMs: 12345,
          syncIntentId: sync.intentId,
        );
        expect(pending.phase, 'awaiting_sync');
        expect(pending.body, isNull);
        await expectLater(
          store.finalizeSubmit(
            question.id,
            intentId: pending.intentId,
            expectedGeneration: pending.generation,
          ),
          throwsStateError,
        );
        final known = await store.recordWriteResult(
          question.id,
          lane: 'draft_sync',
          intentId: sync.intentId,
          expectedGeneration: sync.generation,
          result: {...source.asServer().toJson(), 'revision': 1},
        );
        await store.ackDraftSync(
          question.id,
          intentId: known.intentId,
          expectedGeneration: known.generation,
        );
        final b = source.toJson();
        (b['answer'] as Map)['selected'] = ['B'];
        await store.writeDraft(LocalDraft.fromJson(b));
        final ready = await store.finalizeSubmit(
          question.id,
          intentId: pending.intentId,
          expectedGeneration: pending.generation,
        );
        expect(ready.body!['elapsed_ms'], 12345);
        expect(ready.body!['expected_draft_revision'], 1);
        expect((ready.body!['answer'] as Map)['selected_options'], ['A']);
        await expectLater(
          store.prepareWrite(
            question.id,
            lane: 'draft_sync',
            body: syncBody(),
            sourceSnapshot: LocalDraft.fromJson(b),
          ),
          throwsStateError,
        );
        final result = submitResult(source.attemptId!, source.sessionId!);
        final recorded = await store.recordWriteResult(
          question.id,
          lane: 'submit',
          intentId: ready.intentId,
          expectedGeneration: ready.generation,
          result: result,
        );
        memory.failWrites = true;
        await expectLater(
          store.ackSubmit(
            question.id,
            intentId: recorded.intentId,
            expectedGeneration: recorded.generation,
          ),
          throwsStateError,
        );
        memory.failWrites = false;
        expect((await store.readDraft(question.id))!.selected, ['B']);
        final continuation = await store.ackSubmit(
          question.id,
          intentId: recorded.intentId,
          expectedGeneration: recorded.generation,
        );
        expect(continuation!.draft.selected, ['B']);
        expect(await store.readDraft(question.id), isNull);
        final snapshotBeforeTransfer = Map.of(memory.data);
        final exportedBeforeTransfer =
            (await store.readExportWriteJournals()).single;
        expect(
          exportedBeforeTransfer['continuations']
              .single['draft']['answer']['selected'],
          ['B'],
        );
        final exportedSubmit =
            (exportedBeforeTransfer['write_commands'] as List).singleWhere(
              (c) => c['lane'] == 'submit',
            );
        expect(exportedSubmit['body'], ready.body);
        expect(exportedSubmit['result']['attempt']['id'], source.attemptId);
        expect(exportedSubmit['phase'], 'acked');
        expect(memory.data, snapshotBeforeTransfer);
        expect(
          (await store.readContinuations(question.id)).single.id,
          continuation.id,
        );
        final creation = DraftCreationCommand(
          intentId: 'continue-intent',
          generation: 1,
          phase: 'attempt_prepared',
          sessionKey: 'continue-session',
          attemptKey: 'continue-attempt',
          sessionBody: (await store.readWorkspaceContext(question.id))!
              .sessionBody,
          attemptBody: {'session_id': source.sessionId},
          sessionId: source.sessionId,
          questionVersion: question.version,
          transferPolicy: {
            'kind': 'continuation',
            'continuationId': continuation.id,
          },
        );
        await store.prepareCreation(question.id, creation);
        final knownCreation = DraftCreationCommand.fromJson({
          ...creation.toJson(),
          'phase': 'attempt_known',
          'generation': 2,
          'attemptId': 'new-attempt',
        });
        await store.advanceCreation(
          question.id,
          knownCreation,
          expectedGeneration: 1,
        );
        if (staleSelection) {
          await DraftStore(memory, 'owner')
              .forAttempt('C')
              .writeActive(
                question.id,
                const ActiveRef(sessionId: 'session-C', attemptId: 'C'),
              );
        }
        final target = LocalDraft(
          questionId: question.id,
          sessionId: source.sessionId,
          attemptId: 'new-attempt',
          savedAt: DateTime.utc(2026),
        );
        final beforeTransfer = Map<String, String>.of(memory.data);
        memory.failWrites = true;
        await expectLater(
          store.attachCreation(
            target,
            intentId: creation.intentId,
            expectedGeneration: 2,
          ),
          throwsStateError,
        );
        memory.failWrites = false;
        expect(memory.data, beforeTransfer);
        expect(
          await store.attachCreation(
            target,
            intentId: creation.intentId,
            expectedGeneration: 2,
          ),
          !staleSelection,
        );
        final transferred = await store
            .forAttempt('new-attempt')
            .readDraft(question.id);
        if (staleSelection) {
          expect(
            (await store.readContinuations(question.id)).single.draft.selected,
            ['B'],
          );
          expect((await store.readActive(question.id))!.attemptId, 'C');
        } else {
          expect(transferred!.selected, ['B']);
          expect(transferred.dirty, isTrue);
          expect(await store.readContinuations(question.id), isEmpty);
          expect(
            (await store.readActive(question.id))!.sessionId,
            source.sessionId,
          );
        }
      },
    );
  }

  test('damaged request fields fail closed and preserve the exact raw record', () async {
    final command = await store.prepareWrite(
      question.id,
      lane: 'draft_sync',
      body: syncBody(),
      sourceSnapshot: source,
    );
    final key = 'u/owner/draft-bundle/${question.id}';
    final original = memory.data[key]!;
    for (final field in [
      'owner',
      'attemptId',
      'idempotencyKey',
      'activationEpoch',
      'body',
      'v',
    ]) {
      final json = jsonDecode(original) as Map;
      final record =
          json['writeJournal']['attempt/${source.attemptId}']['draft_sync']['history'][command
                  .intentId]
              as Map;
      record[field] = field == 'activationEpoch'
          ? 99
          : field == 'v'
          ? 99
          : field == 'body'
          ? {'base_revision': 99}
          : 'changed';
      final raw = jsonEncode(json);
      memory.data[key] = raw;
      await expectLater(
        store.readWrite(question.id, 'draft_sync'),
        throwsFormatException,
      );
      expect(memory.data[key], raw);
    }
    memory.data[key] = original;
    final mutable = command.body!;
    mutable['base_revision'] = 88;
    expect(
      (await store.readWrite(question.id, 'draft_sync'))!.body,
      syncBody(),
    );
  });

  test(
    'every sync persistence window preserves recoverable prior state',
    () async {
      memory.failWrites = true;
      await expectLater(
        store.prepareWrite(
          question.id,
          lane: 'draft_sync',
          body: syncBody(),
          sourceSnapshot: source,
        ),
        throwsStateError,
      );
      memory.failWrites = false;
      expect(await store.readWrite(question.id, 'draft_sync'), isNull);
      final command = await store.prepareWrite(
        question.id,
        lane: 'draft_sync',
        body: syncBody(),
        sourceSnapshot: source,
      );
      final result = {...source.asServer().toJson(), 'revision': 1};
      final before = Map<String, String>.of(memory.data);
      memory.failWrites = true;
      await expectLater(
        store.recordWriteResult(
          question.id,
          lane: 'draft_sync',
          intentId: command.intentId,
          expectedGeneration: command.generation,
          result: result,
        ),
        throwsStateError,
      );
      memory.failWrites = false;
      expect(memory.data, before);
      await expectLater(
        store.recordWriteResult(
          question.id,
          lane: 'draft_sync',
          intentId: command.intentId,
          expectedGeneration: 99,
          result: result,
        ),
        throwsStateError,
      );
      expect(memory.data, before);
      final known = await store.recordWriteResult(
        question.id,
        lane: 'draft_sync',
        intentId: command.intentId,
        expectedGeneration: command.generation,
        result: result,
      );
      final beforeAck = Map<String, String>.of(memory.data);
      memory.failWrites = true;
      await expectLater(
        store.ackDraftSync(
          question.id,
          intentId: known.intentId,
          expectedGeneration: known.generation,
        ),
        throwsStateError,
      );
      memory.failWrites = false;
      expect(memory.data, beforeAck);
      final ack = await store.ackDraftSync(
        question.id,
        intentId: known.intentId,
        expectedGeneration: known.generation,
      );
      expect(ack.current, isTrue);
      expect(ack.draft!.dirty, isFalse);
    },
  );

  test(
    'self check A B A creates new actions and late A preserves local B',
    () async {
      final keys = <String>{};
      for (final level in [
        SelfCheckLevel.done,
        SelfCheckLevel.partial,
        SelfCheckLevel.done,
      ]) {
        await store.saveLocalMarks(question.id, {'point': level});
        final body = SelfCheckSave(
          marks: [SelfCheckMark(pointKey: 'point', level: level)],
        ).toJson();
        final command = await store.prepareWrite(
          question.id,
          lane: 'self_check',
          body: body,
          sourceSnapshot: source,
        );
        keys.add(command.idempotencyKey);
        final result = Fixtures.load().value('self_check_pending')
          ..['attempt_id'] = source.attemptId
          ..['marks'] = body['marks'];
        await store.saveLocalMarks(question.id, {
          'point': SelfCheckLevel.missed,
        });
        final known = await store.recordWriteResult(
          question.id,
          lane: 'self_check',
          intentId: command.intentId,
          expectedGeneration: command.generation,
          result: result,
        );
        final ack = await store.ackSelfCheck(
          question.id,
          intentId: known.intentId,
          expectedGeneration: known.generation,
        );
        expect(ack.marks['point'], SelfCheckLevel.missed);
        expect(ack.confirmedMarks['point'], level);
      }
      expect(keys.length, 3);
      final beforeExport = Map.of(memory.data);
      final exported = (await store.readExportWriteJournals()).single;
      expect(
        (exported['write_receipts'] as List)
            .where((r) => r['lane'] == 'self_check')
            .length,
        2,
      );
      expect(
        exported['write_commands'].single['result']['marks'].single['level'],
        'done',
      );
      expect(exported['edit_state'].single['marks']['point'], 'missed');
      expect(exported['edit_state'].single['confirmed_marks']['point'], 'done');
      expect(memory.data, beforeExport);
      final reopened = DraftStore(
        memory,
        'owner',
      ).forAttempt(source.attemptId!);
      expect(
        (await reopened.readEditState(question.id)).marks['point'],
        SelfCheckLevel.missed,
      );
    },
  );

  test('many confirmed syncs retain receipts without copying all ink history', () async {
    final ink = StrokeDoc(
      version: 1,
      pages: [
        StrokePage(
          width: 1000,
          height: 1400,
          strokes: [
            Stroke(
              color: '#111111',
              width: 2,
              points: List<double>.generate(8000, (i) => i.toDouble()),
            ),
          ],
        ),
      ],
    );
    source = LocalDraft.fromJson({...source.toJson(), 'strokes': ink.toJson()});
    await store.writeDraft(source);
    int firstSize = 0;
    for (var i = 0; i < 12; i++) {
      source = (await store.readDraft(question.id))!;
      final command = await store.prepareWrite(
        question.id,
        lane: 'draft_sync',
        body: syncBody(),
        sourceSnapshot: source,
      );
      final known = await store.recordWriteResult(
        question.id,
        lane: 'draft_sync',
        intentId: command.intentId,
        expectedGeneration: command.generation,
        result: {...source.asServer().toJson(), 'revision': i + 1},
      );
      await store.ackDraftSync(
        question.id,
        intentId: known.intentId,
        expectedGeneration: known.generation,
      );
      if (i == 0) firstSize = memory.data.values.single.length;
    }
    expect(memory.data.values.single.length, lessThan(firstSize * 2));
    final json = jsonDecode(memory.data.values.single) as Map;
    expect((json['writeReceipts'] as Map).length, 11);
    expect(
      (json['writeJournal']['attempt/${source.attemptId}']['draft_sync']['history']
              as Map)
          .length,
      1,
    );
    expect(
      (await store.readDraft(question.id))!.strokes!.toJson(),
      ink.toJson(),
    );
  });
  test(
    'submission capture freezes A atomically while current B remains untouched',
    () async {
      final answer = source.asServer().answer!.toJson();
      final aSync = syncBody();
      final b = source.toJson();
      (b['answer'] as Map)['selected'] = ['B'];
      await store.writeDraft(LocalDraft.fromJson(b));
      final capture = await store.prepareSubmissionCapture(
        question.id,
        sourceSnapshot: source,
        answer: answer,
        elapsedMs: 77,
        body: aSync,
      );
      expect(capture.sync.sourceSnapshot.selected, ['A']);
      expect(capture.submit.sourceSnapshot.selected, ['A']);
      expect(capture.submit.elapsedMs, 77);
      expect(capture.submit.syncIntentId, capture.sync.intentId);
      expect((await store.readDraft(question.id))!.selected, ['B']);
    },
  );
  for (final resultAlreadyKnown in [false, true]) {
    test(
      'waiting dependency preserves click A across restart known=$resultAlreadyKnown',
      () async {
        final x = source;
        final oldSync = await store.prepareWrite(
          question.id,
          lane: 'draft_sync',
          body: syncBody(),
          sourceSnapshot: x,
        );
        final aJson = source.toJson();
        (aJson['answer'] as Map)['selected'] = ['C'];
        final a = LocalDraft.fromJson(aJson);
        await store.writeDraft(a);
        final capture = await store.prepareSubmissionCapture(
          question.id,
          sourceSnapshot: a,
          answer: a.asServer().answer!.toJson(),
          elapsedMs: 456,
          body: DraftSync(
            baseRevision: 0,
            answer: a.asServer().answer,
          ).toJson(),
        );
        expect(capture.submit.phase, 'waiting_dependency');
        expect(capture.submit.syncIntentId, isNull);
        expect(capture.sync.intentId, oldSync.intentId);
        expect(capture.submit.sourceSnapshot.selected, ['C']);
        final bJson = a.toJson();
        (bJson['answer'] as Map)['selected'] = ['B'];
        await store.writeDraft(LocalDraft.fromJson(bJson));
        if (resultAlreadyKnown) {
          await store.recordWriteResult(
            question.id,
            lane: 'draft_sync',
            intentId: oldSync.intentId,
            expectedGeneration: oldSync.generation,
            result: {...x.asServer().toJson(), 'revision': 1},
          );
        }
        final reopened = DraftStore(
          memory,
          'owner',
        ).forAttempt(source.attemptId!);
        await reopened.claimScope(question.id);
        final waiting = (await reopened.readWrite(question.id, 'submit'))!;
        expect(waiting.elapsedMs, 456);
        expect(waiting.sourceSnapshot.selected, ['C']);
        final before = Map<String, String>.of(memory.data);
        if (!resultAlreadyKnown) {
          await expectLater(
            reopened.prepareSubmitDependency(
              question.id,
              intentId: waiting.intentId,
              expectedGeneration: waiting.generation,
            ),
            throwsStateError,
          );
          expect(memory.data, before);
          final syncX = (await reopened.readWrite(question.id, 'draft_sync'))!;
          final known = await reopened.recordWriteResult(
            question.id,
            lane: 'draft_sync',
            intentId: syncX.intentId,
            expectedGeneration: syncX.generation,
            result: {...x.asServer().toJson(), 'revision': 1},
          );
          await reopened.ackDraftSync(
            question.id,
            intentId: known.intentId,
            expectedGeneration: known.generation,
          );
        } else {
          memory.failWrites = true;
          await expectLater(
            reopened.prepareSubmitDependency(
              question.id,
              intentId: waiting.intentId,
              expectedGeneration: waiting.generation,
            ),
            throwsStateError,
          );
          memory.failWrites = false;
          expect(memory.data, before);
        }
        final next = await reopened.prepareSubmitDependency(
          question.id,
          intentId: waiting.intentId,
          expectedGeneration: waiting.generation,
        );
        expect(next.sync.intentId, isNot(oldSync.intentId));
        expect(next.sync.sourceSnapshot.selected, ['C']);
        expect(next.sync.body!['base_revision'], 1);
        expect(next.submit.intentId, waiting.intentId);
        expect(next.submit.idempotencyKey, waiting.idempotencyKey);
        expect(next.submit.activationEpoch, waiting.activationEpoch);
        expect(next.submit.syncIntentId, next.sync.intentId);
        expect(next.submit.elapsedMs, 456);
        expect(next.submit.phase, 'awaiting_sync');
        expect((await reopened.readDraft(question.id))!.selected, ['B']);
      },
    );
  }
  for (final staleSelection in [false, true]) {
    test(
      'unbound capture binds atomically after creation stale=$staleSelection',
      () async {
        final localId = await store.newWorkspace(question.id);
        final local = DraftStore(memory, 'owner').forLocal(localId);
        await local.claimScope(question.id);
        final context = DraftWorkspaceContext(
          workspaceId: localId,
          question: question,
          sessionBody: SessionCreate(
            questionId: question.id,
            origin: SessionOrigin.practice,
            expectedQuestionVersion: question.version,
          ).toJson(),
        );
        await local.saveWorkspaceContext(question.id, context);
        final a = LocalDraft(
          questionId: question.id,
          selected: const ['A'],
          dirty: true,
          savedAt: DateTime.utc(2026),
        );
        await local.writeDraft(a);
        final answer = AnswerPayload(selectedOptions: ['A']);
        final dynamic capture = await local.prepareUnboundSubmission(
          question.id,
          sourceSnapshot: a,
          answer: answer.toJson(),
          elapsedMs: 987,
          bodyTemplate: DraftSync(baseRevision: 0, answer: answer).toJson(),
        );
        final b = a.toJson();
        (b['answer'] as Map)['selected'] = ['B'];
        await local.writeDraft(LocalDraft.fromJson(b));
        final reopened = DraftStore(memory, 'owner').forLocal(localId);
        await reopened.claimScope(question.id);
        final dynamic persisted = await reopened.readUnboundSubmission(
          question.id,
        );
        expect(persisted.sourceSnapshot.selected, ['A']);
        expect(persisted.elapsedMs, 987);
        var command = DraftCreationCommand(
          intentId: 'bind-creation',
          generation: 1,
          phase: 'session_prepared',
          sessionKey: 'bind-session-key',
          attemptKey: 'bind-attempt-key',
          sessionBody: context.sessionBody,
        );
        await reopened.prepareCreation(question.id, command);
        for (final phase in [
          'session_known',
          'attempt_prepared',
          'attempt_known',
        ]) {
          command = DraftCreationCommand.fromJson({
            ...command.toJson(),
            'phase': phase,
            'generation': command.generation + 1,
            'sessionId': 'new-session',
            'questionVersion': question.version,
            if (phase != 'session_known')
              'attemptBody': {'session_id': 'new-session'},
            if (phase == 'attempt_known') 'attemptId': 'new-attempt',
          });
          await reopened.advanceCreation(
            question.id,
            command,
            expectedGeneration: command.generation - 1,
          );
        }
        if (staleSelection) {
          await DraftStore(memory, 'owner')
              .forAttempt('C')
              .writeActive(
                question.id,
                const ActiveRef(sessionId: 'session-C', attemptId: 'C'),
              );
        }
        final target = LocalDraft.fromJson({
          ...b,
          'sessionId': 'new-session',
          'attemptId': 'new-attempt',
        });
        final before = Map<String, String>.of(memory.data);
        memory.failWrites = true;
        await expectLater(
          reopened.attachCreation(
            target,
            intentId: command.intentId,
            expectedGeneration: 4,
          ),
          throwsStateError,
        );
        memory.failWrites = false;
        expect(memory.data, before);
        expect(
          await reopened.attachCreation(
            target,
            intentId: command.intentId,
            expectedGeneration: 4,
          ),
          !staleSelection,
        );
        final bound = await reopened
            .forAttempt('new-attempt')
            .readWrite(question.id, 'submit');
        if (staleSelection) {
          expect(bound, isNull);
          expect(await reopened.readUnboundSubmission(question.id), isNotNull);
          expect((await reopened.readActive(question.id))!.attemptId, 'C');
        } else {
          expect(bound!.intentId, capture.intentId);
          expect(bound.idempotencyKey, capture.idempotencyKey);
          expect(bound.elapsedMs, 987);
          expect(bound.sourceSnapshot.selected, ['A']);
          expect(bound.attemptId, 'new-attempt');
          expect(bound.phase, 'awaiting_sync');
          expect(
            (await reopened.forAttempt('new-attempt').readDraft(question.id))!
                .selected,
            ['B'],
          );
          expect(await reopened.readUnboundSubmission(question.id), isNull);
          final targetStore = reopened.forAttempt('new-attempt');
          await targetStore.claimScope(question.id);
          // Promotion writes B directly. An unchanged flush must keep its
          // initial generation valid even when no edit counter was stored.
          await targetStore.writeDraft(
            (await targetStore.readDraft(question.id))!,
          );
          final sync = (await targetStore.readWrite(
            question.id,
            'draft_sync',
          ))!;
          final knownSync = await targetStore.recordWriteResult(
            question.id,
            lane: 'draft_sync',
            intentId: sync.intentId,
            expectedGeneration: sync.generation,
            result: {...sync.sourceSnapshot.asServer().toJson(), 'revision': 1},
          );
          await targetStore.ackDraftSync(
            question.id,
            intentId: knownSync.intentId,
            expectedGeneration: knownSync.generation,
          );
          final ready = await targetStore.finalizeSubmit(
            question.id,
            intentId: bound.intentId,
            expectedGeneration: bound.generation,
          );
          final result = submitResult('new-attempt', 'new-session');
          final knownSubmit = await targetStore.recordWriteResult(
            question.id,
            lane: 'submit',
            intentId: ready.intentId,
            expectedGeneration: ready.generation,
            result: result,
          );
          await targetStore.ackSubmit(
            question.id,
            intentId: knownSubmit.intentId,
            expectedGeneration: knownSubmit.generation,
          );
          final restarted = DraftStore(
            memory,
            'owner',
          ).forAttempt('new-attempt');
          final continuation = (await restarted.readContinuations(question.id))
              .single;
          expect(continuation.editGeneration, 0);
          expect(continuation.draft.selected, ['B']);
          expect(continuation.draft.dirty, isTrue);
          final beforeExport = Map.of(memory.data);
          final exported = (await restarted.readExportWriteJournals()).single;
          expect(exported['unbound_submissions'].single['phase'], 'bound');
          expect(
            exported['unbound_submissions'].single['bound_to']['attemptId'],
            'new-attempt',
          );
          expect(
            exported['continuations'].single['draft']['answer']['selected'],
            ['B'],
          );
          expect(memory.data, beforeExport);
        }
      },
    );
  }
}
