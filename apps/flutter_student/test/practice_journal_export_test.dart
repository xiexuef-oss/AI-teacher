import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/profile/local_recovery_export.dart';
import 'package:tutor_student/features/solve/draft_store.dart';
import 'package:tutor_student/features/profile/profile_journal_store.dart';
import 'package:tutor_student/features/profile/student_data_export_section.dart';

import 'support/fake_backend.dart';
import 'support/app_harness.dart';
import 'profile_journal_store_test.dart' show cloud, edit;

class ForeignPracticeKeys extends MemoryStore {
  bool readForeign = false;
  @override
  Future<List<String>> keys(String prefix) async =>
      prefix.endsWith('/draft-bundle/')
      ? [
          data.keys
              .firstWhere((key) => key.startsWith(prefix))
              .replaceFirst('u/alice/', 'u/other/'),
        ]
      : super.keys(prefix);
  @override
  Future<String?> read(String key) async {
    if (key.startsWith('u/') && !key.startsWith('u/alice/')) readForeign = true;
    return super.read(key);
  }
}

class DisappearingPractice extends MemoryStore {
  @override
  Future<List<String>> keys(String prefix) async {
    final found = await super.keys(prefix);
    if (prefix.endsWith('/draft-bundle/') && found.isNotEmpty) {
      data.remove(found.first);
    }
    return found;
  }
}

Future<({DraftStore store, LocalDraft source, Question question})> prepared(
  MemoryStore disk, {
  String owner = 'alice',
  bool local = false,
}) async {
  final fixtures = Fixtures.load();
  final q = Question.fromJson(fixtures.value('question_single_choice'));
  final sid = fixtures.value('session_created')['id'] as String;
  final aid = fixtures.value('attempt_created')['id'] as String;
  final root = DraftStore(disk, owner);
  final localId = local ? await root.readOrCreateLocalId(q.id) : null;
  final store = local ? root.forLocal(localId!) : root.forAttempt(aid);
  await store.claimScope(q.id);
  await store.saveWorkspaceContext(
    q.id,
    DraftWorkspaceContext(
      workspaceId: local ? localId! : aid,
      question: q,
      trustedSessionId: local ? null : sid,
      sessionBody: SessionCreate(
        questionId: q.id,
        origin: SessionOrigin.practice,
        expectedQuestionVersion: q.version,
      ).toJson(),
    ),
  );
  final source = LocalDraft(
    questionId: q.id,
    sessionId: local ? null : sid,
    attemptId: local ? null : aid,
    selected: [owner == 'bob' ? 'PRIVATE-OTHER-OWNER' : 'A'],
    dirty: true,
    savedAt: DateTime.utc(2026),
  );
  await store.writeDraft(source);
  if (!local) {
    await store.writeActive(q.id, ActiveRef(sessionId: sid, attemptId: aid));
  }
  return (store: store, source: source, question: q);
}

Map<String, dynamic> sync(LocalDraft draft) => DraftSync(
  baseRevision: draft.baseRevision,
  answer: draft.asServer().answer,
  strokes: draft.strokes,
).toJson();

Future<WriteCommand> recordSubmission(
  DraftStore store,
  LocalDraft source,
  Question question,
) async {
  final pair = await store.prepareSubmissionCapture(
    question.id,
    sourceSnapshot: source,
    answer: source.asServer().answer!.toJson(),
    elapsedMs: 42,
    body: sync(source),
  );
  final known = await store.recordWriteResult(
    question.id,
    lane: 'draft_sync',
    intentId: pair.sync.intentId,
    expectedGeneration: pair.sync.generation,
    result: {...source.asServer().toJson(), 'revision': 1},
  );
  await store.ackDraftSync(
    question.id,
    intentId: known.intentId,
    expectedGeneration: known.generation,
  );
  final ready = await store.finalizeSubmit(
    question.id,
    intentId: pair.submit.intentId,
    expectedGeneration: pair.submit.generation,
  );
  final result = Fixtures.load().value('submit_correct');
  result['attempt']['id'] = source.attemptId;
  result['attempt']['session_id'] = source.sessionId;
  result['session']['id'] = source.sessionId;
  result['session']['question_id'] = question.id;
  result['session']['question_version'] = question.version;
  for (final event in result['events'] as List) {
    event['session_id'] = source.sessionId;
    event['meta']['question_id'] = question.id;
    event['meta']['question_version'] = question.version;
  }
  return store.recordWriteResult(
    question.id,
    lane: 'submit',
    intentId: ready.intentId,
    expectedGeneration: ready.generation,
    result: result,
  );
}

void main() {
  test('practice export keeps original sync key body and source without secrets or mutation', () async {
    final disk = MemoryStore({'auth.token': 'PRIVATE-TOKEN'});
    final p = await prepared(disk);
    final command = await p.store.prepareWrite(
      p.question.id,
      lane: 'draft_sync',
      body: sync(p.source),
      sourceSnapshot: p.source,
    );
    await prepared(disk, owner: 'bob');
    final before = Map.of(disk.data);
    disk.failWrites = true;
    final value = (await DraftStore(
      disk,
      'alice',
    ).readExportWriteJournals()).single;
    final c = (value['write_commands'] as List).single;
    expect(value['question_id'], p.question.id);
    expect(c['key'], command.idempotencyKey);
    expect(c['body'], command.body);
    expect(c['source_snapshot'], p.source.toJson());
    expect(c['phase'], 'prepared');
    for (final secret in [
      'PRIVATE-TOKEN',
      'PRIVATE-OTHER-OWNER',
      'checksum',
      'activationEpoch',
      'activeEpoch',
      'sourceHash',
    ]) {
      expect(jsonEncode(value), isNot(contains(secret)));
    }
    expect(disk.data, before);
  });

  test('existing combined recovery file includes practice journals', () async {
    final disk = MemoryStore();
    final p = await prepared(disk);
    await p.store.prepareWrite(
      p.question.id,
      lane: 'draft_sync',
      body: sync(p.source),
      sourceSnapshot: p.source,
    );
    final value = await exportLocalRecoveryRecords(disk, 'alice');
    expect(
      value['practice'].single['write_commands'].single['lane'],
      'draft_sync',
    );
    expect(value['scope'], 'local_student_recovery_records');
  });

  test('creation and unbound submission retain keys and captured answer without fabricating resources', () async {
    final disk = MemoryStore();
    final p = await prepared(disk, local: true);
    final context = (await p.store.readWorkspaceContext(p.question.id))!;
    await p.store.prepareCreation(
      p.question.id,
      DraftCreationCommand(
        intentId: 'creation-intent',
        generation: 1,
        phase: 'session_prepared',
        sessionKey: 'session-key',
        attemptKey: 'attempt-key',
        sessionBody: context.sessionBody,
      ),
    );
    final capture = await p.store.prepareUnboundSubmission(
      p.question.id,
      sourceSnapshot: p.source,
      answer: const AnswerPayload(selectedOptions: ['A']).toJson(),
      elapsedMs: 123,
      bodyTemplate: DraftSync(
        baseRevision: 0,
        answer: const AnswerPayload(selectedOptions: ['A']),
      ).toJson(),
    );
    final before = Map.of(disk.data);
    final value = (await DraftStore(
      disk,
      'alice',
    ).readExportWriteJournals()).single;
    expect(value['creation_commands'].single['session_key'], 'session-key');
    expect(value['creation_commands'].single['attempt_request'], isNull);
    expect(value['creation_commands'].single['session_id'], isNull);
    expect(value['unbound_submissions'].single['key'], capture.idempotencyKey);
    expect(value['unbound_submissions'].single['phase'], 'local_prepared');
    expect(value['unbound_submissions'].single['answer']['selected_options'], [
      'A',
    ]);
    expect(value['unbound_submissions'].single['bound_to'], isNull);
    expect(disk.data, before);
  });

  test(
    'empty read creates nothing and cannot borrow another identity',
    () async {
      final disk = MemoryStore();
      await prepared(disk, owner: 'bob');
      final before = Map.of(disk.data);
      expect(
        await DraftStore(disk, 'alice').readExportWriteJournals(),
        isEmpty,
      );
      expect(disk.data, before);
    },
  );

  test('resource enumeration cannot read foreign keys or synthesize disappeared bundles', () async {
    final foreign = ForeignPracticeKeys();
    await prepared(foreign);
    await expectLater(
      DraftStore(foreign, 'alice').readExportWriteJournals(),
      throwsFormatException,
    );
    expect(foreign.readForeign, false);
    final missing = DisappearingPractice();
    await prepared(missing);
    await expectLater(
      DraftStore(missing, 'alice').readExportWriteJournals(),
      throwsFormatException,
    );
  });

  test('compacted sync receipt keeps its old key alongside the next immutable request', () async {
    final disk = MemoryStore();
    final p = await prepared(disk);
    final first = await p.store.prepareWrite(
      p.question.id,
      lane: 'draft_sync',
      body: sync(p.source),
      sourceSnapshot: p.source,
    );
    final known = await p.store.recordWriteResult(
      p.question.id,
      lane: 'draft_sync',
      intentId: first.intentId,
      expectedGeneration: first.generation,
      result: {
        ...p.source.asServer().toJson(),
        'revision': 1,
        'private_token': 'PRIVATE-RESULT',
      },
    );
    await p.store.ackDraftSync(
      p.question.id,
      intentId: known.intentId,
      expectedGeneration: known.generation,
    );
    final source = (await p.store.readDraft(p.question.id))!;
    final second = await p.store.prepareWrite(
      p.question.id,
      lane: 'draft_sync',
      body: sync(source),
      sourceSnapshot: source,
    );
    final before = Map.of(disk.data);
    final exported = (await DraftStore(
      disk,
      'alice',
    ).readExportWriteJournals()).single;
    expect(exported['write_receipts'], hasLength(1));
    expect(exported['write_receipts'].single['key'], first.idempotencyKey);
    expect(exported['write_receipts'].single['revision'], 1);
    expect(exported['write_commands'].single['key'], second.idempotencyKey);
    expect(jsonEncode(exported), isNot(contains('PRIVATE-RESULT')));
    expect(disk.data, before);
  });

  test(
    'known receipt projection excludes unknown fields without acknowledging it',
    () async {
      final disk = MemoryStore();
      final p = await prepared(disk);
      final command = await p.store.prepareWrite(
        p.question.id,
        lane: 'draft_sync',
        body: sync(p.source),
        sourceSnapshot: p.source,
      );
      await p.store.recordWriteResult(
        p.question.id,
        lane: 'draft_sync',
        intentId: command.intentId,
        expectedGeneration: command.generation,
        result: {
          ...p.source.asServer().toJson(),
          'revision': 1,
          'private_token': 'PRIVATE-RESULT',
        },
      );
      final before = Map.of(disk.data);
      final value = (await DraftStore(
        disk,
        'alice',
      ).readExportWriteJournals()).single;
      expect(value['write_commands'].single['phase'], 'result_known');
      expect(value['write_commands'].single['result']['revision'], 1);
      expect(jsonEncode(value), isNot(contains('PRIVATE-RESULT')));
      expect(disk.data, before);
    },
  );

  test(
    'combined limit counts practice metadata as well as other pending commands',
    () async {
      final disk = MemoryStore();
      final p = await prepared(disk);
      await p.store.prepareWrite(
        p.question.id,
        lane: 'draft_sync',
        body: sync(p.source),
        sourceSnapshot: p.source,
      );
      final records =
          (await DraftStore(
                disk,
                'alice',
              ).readExportWriteJournals()).single['record_count']
              as int;
      final profile = ProfileJournalStore(disk, 'alice');
      await profile.rememberCloud(cloud(0));
      await profile.edit(ProfileEdit(edit('local-edit', 0).toJson()));
      await profile.prepare(
        edit('local-edit', 0),
        idempotencyKey: 'profile-key',
        activeEpoch: 1,
      );
      final before = Map.of(disk.data);
      await expectLater(
        exportLocalRecoveryRecords(disk, 'alice', limit: records),
        throwsStateError,
      );
      expect(disk.data, before);
    },
  );

  testWidgets(
    'practice-only records are downloadable offline through the existing recovery entry',
    (tester) async {
      final disk = MemoryStore();
      await prepared(disk, owner: 'student');
      final h = AppHarness(store: disk)
        ..signInAs(role: 'student', userId: 'student');
      h.backend.offline = true;
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection.recovery(
              save: (bytes) async {
                final value = jsonDecode(utf8.decode(bytes)) as Map;
                expect(value['profile'], isNull);
                expect(value['resources'], isEmpty);
                expect(value['practice'].length, 1);
                saves++;
                return 'saved';
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final before = Map.of(h.store.data);
      await tester.tap(find.byKey(const ValueKey('profile.exportRecovery')));
      await tester.pumpAndSettle();
      expect(saves, 1);
      expect(h.store.data, before);
    },
  );

  test('submission export checks receipt events against the fixed session', () async {
    final disk = MemoryStore();
    final p = await prepared(disk);
    final command = await recordSubmission(p.store, p.source, p.question);
    final valid = (await p.store.readExportWriteJournals()).single;
    expect(
      (valid['write_commands'] as List).singleWhere(
        (c) => c['lane'] == 'submit',
      )['result']['session']['id'],
      p.source.sessionId,
    );
    final key = 'u/alice/draft-bundle/${p.question.id}';
    final bundle = jsonDecode(disk.data[key]!) as Map;
    final history =
        bundle['writeJournal']['attempt/${p.source.attemptId}']['submit']['history']
            as Map;
    final raw = Map<String, dynamic>.from(history[command.intentId] as Map);
    raw['result']['events'][0]['session_id'] = 'foreign-session';
    history[command.intentId] = WriteCommand.create(raw).toJson();
    disk.data[key] = jsonEncode(bundle);
    final before = Map.of(disk.data);
    await expectLater(p.store.readExportWriteJournals(), throwsFormatException);
    expect(disk.data, before);
  });

  test('pending conflict copy retains snapshot and original key without resolving it', () async {
    final disk = MemoryStore();
    final p = await prepared(disk);
    await p.store.archivePair(p.question.id, p.source, p.source, pending: true);
    final recovery = (await p.store.readRecovery(p.question.id))!;
    await p.store.savePendingCopy(
      p.question.id,
      PendingDraftCopy(
        snapshot: p.source,
        sourceAttemptId: p.source.attemptId!,
        observedRevision: 4,
        idempotencyKey: 'copy-original-key',
        recoveryGeneration: recovery.generation,
      ),
    );
    final before = Map.of(disk.data);
    final copy = (await DraftStore(
      disk,
      'alice',
    ).readExportWriteJournals()).single['pending_copies'].single;
    expect(copy['key'], 'copy-original-key');
    expect(copy['observed_revision'], 4);
    expect(copy['snapshot'], p.source.toJson());
    expect(disk.data, before);
  });

  for (final damage in [
    'version',
    'owner',
    'result',
    'corrupt_marker',
    'request',
    'source_version',
    'missing_result',
  ]) {
    test('invalid practice $damage fails whole export and preserves bytes', () async {
      final disk = MemoryStore();
      final p = await prepared(disk);
      final command = await p.store.prepareWrite(
        p.question.id,
        lane: 'draft_sync',
        body: sync(p.source),
        sourceSnapshot: p.source,
      );
      final key = 'u/alice/draft-bundle/${p.question.id}';
      final value = jsonDecode(disk.data[key]!) as Map;
      if (damage == 'version') {
        value['v'] = 99;
      } else if (damage == 'corrupt_marker') {
        disk.data['u/alice/draft-corrupt/${p.question.id}'] = 'PRIVATE-CORRUPT';
      } else {
        final path =
            value['writeJournal']['attempt/${p.source.attemptId}']['draft_sync'];
        final c = Map<String, dynamic>.from(
          path['history'][command.intentId] as Map,
        );
        if (damage == 'owner') c['owner'] = 'bob';
        if (damage == 'request') {
          c['body']['private_token'] = 'PRIVATE-UNSUPPORTED';
        }
        if (damage == 'source_version') c['sourceSnapshot']['v'] = 99;
        if (damage == 'missing_result') c['phase'] = 'acked';
        if (damage == 'result') {
          c['phase'] = 'result_known';
          c['result'] = {
            ...p.source.asServer().toJson(),
            'attempt_id': 'foreign-attempt',
          };
        }
        path['history'][command.intentId] = WriteCommand.create(c).toJson();
      }
      disk.data[key] = jsonEncode(value);
      final before = Map.of(disk.data);
      await expectLater(
        DraftStore(disk, 'alice').readExportWriteJournals(),
        throwsFormatException,
      );
      expect(disk.data, before);
    });
  }
}
