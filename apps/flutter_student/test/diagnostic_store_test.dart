import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/diagnostic/diagnostic_store.dart';
import 'package:tutor_student/features/solve/write_journal.dart'
    show journalHash;

import 'support/fake_backend.dart';

final fixtures = Fixtures.load();
DiagnosticWorkspace created() =>
    DiagnosticWorkspace.fromJson(fixtures.value('diagnostic_created'));
const createBody = DiagnosticCreate(
  subject: Subject.math,
  expectedRevision: 0,
  expectedProfileRevision: 1,
);

void main() {
  test('export whitelists typed metadata and excludes another owner and unknown secrets', () async {
    final disk = MemoryStore();
    final alice = DiagnosticStore(disk, 'alice'),
        bob = DiagnosticStore(disk, 'bob');
    for (final store in [alice, bob]) {
      await store.rememberCloud(const DiagnosticWorkspace(revision: 0));
      await store.prepareCreate(
        createBody,
        store == alice ? 'alice-export-key' : 'bob-private-key',
      );
    }
    await alice.recordResult('alice-export-key', created().toJson());
    final raw =
        jsonDecode(disk.data[alice.storageKey]!) as Map<String, dynamic>;
    raw.remove('checksum');
    raw['token'] = 'unknown-private-token';
    (raw['commands'] as List).first['result']['token'] =
        'unknown-result-secret';
    raw['checksum'] = journalHash(raw);
    disk.data[alice.storageKey] = jsonEncode(raw);
    final before = Map<String, String>.from(disk.data);
    final exported = await alice.exportSnapshot();
    final text = jsonEncode(exported);
    expect(text, isNot(contains('bob-private-key')));
    expect(text, isNot(contains('unknown-private-token')));
    expect(text, isNot(contains('unknown-result-secret')));
    expect(disk.data, before);
    (exported['commands'] as List).first['body']['subject'] = 'physics';
    expect((await alice.read()).pending!.body['subject'], 'math');
    disk.data[alice.storageKey] = '{invalid';
    await expectLater(alice.exportSnapshot(), throwsFormatException);
    expect(disk.data[alice.storageKey], '{invalid');
  });
  test(
    'export includes command-only history without changing stored bytes',
    () async {
      final disk = MemoryStore(),
          journal = DiagnosticStore(MemoryStore(), 'unused');
      final owned = DiagnosticStore(disk, 'alice');
      await owned.rememberCloud(const DiagnosticWorkspace(revision: 0));
      await owned.prepareCreate(createBody, 'export-original-key');
      final before = Map<String, String>.from(disk.data);
      final output = await owned.exportSnapshot();
      expect(output['owner_id'], 'alice');
      expect((output['commands'] as List).single['key'], 'export-original-key');
      expect((output['commands'] as List).single['body'], createBody.toJson());
      expect(disk.data, before);
      expect((await journal.exportSnapshot())['commands'], isEmpty);
    },
  );
  test(
    'workspace is durable and owner scoped across a new store instance',
    () async {
      final disk = MemoryStore();
      await DiagnosticStore(
        disk,
        'alice',
      ).rememberCloud(const DiagnosticWorkspace(revision: 0));
      expect((await DiagnosticStore(disk, 'alice').cloud())?.revision, 0);
      expect(await DiagnosticStore(disk, 'bob').cloud(), isNull);
    },
  );

  test(
    'prepared body and key survive restart and cannot be silently rebased',
    () async {
      final disk = MemoryStore();
      final journal = DiagnosticStore(disk, 'alice');
      await journal.rememberCloud(const DiagnosticWorkspace(revision: 0));
      final original = await journal.prepareCreate(
        createBody,
        'create-fixed-001',
      );
      original.body['expected_revision'] = 999;
      final restarted = DiagnosticStore(disk, 'alice');
      await restarted.rememberCloud(created());
      final saved = (await restarted.read()).pending!;
      expect(saved.key, 'create-fixed-001');
      expect(saved.body, createBody.toJson());
      await expectLater(
        restarted.prepareAbandon(
          created().run!.id,
          const DiagnosticRevision(expectedRevision: 1),
          'new-command-key',
        ),
        throwsStateError,
      );
      expect((await restarted.read()).pending!.key, original.key);
    },
  );

  test(
    'historical receipt is durable but never replaces a newer workspace',
    () async {
      final journal = DiagnosticStore(MemoryStore(), 'alice');
      await journal.rememberCloud(const DiagnosticWorkspace(revision: 0));
      await journal.prepareCreate(createBody, 'create-fixed-001');
      final latest = fixtures.value('diagnostic_abandoned');
      await journal.rememberCloud(DiagnosticWorkspace.fromJson(latest));
      await journal.recordResult('create-fixed-001', created().toJson());
      expect((await journal.read()).pending!.phase, 'result_known');
      expect((await journal.cloud())!.revision, 3);
      await journal.acknowledge('create-fixed-001');
      expect((await journal.read()).pending, isNull);
      expect((await journal.cloud())!.revision, 3);
      expect((await journal.read()).commands.single.result, created().toJson());
    },
  );

  test('failed local preparation preserves previous bytes and has no prepared command', () async {
    final disk = MemoryStore();
    final journal = DiagnosticStore(disk, 'alice');
    await journal.rememberCloud(const DiagnosticWorkspace(revision: 0));
    final before = disk.data[journal.storageKey];
    disk.failWrites = true;
    await expectLater(
      journal.prepareCreate(createBody, 'local-write-fail'),
      throwsStateError,
    );
    expect(disk.data[journal.storageKey], before);
    expect((await journal.read()).pending, isNull);
  });

  test('concurrent preparation has one winner and keeps its source', () async {
    final disk = MemoryStore();
    final one = DiagnosticStore(disk, 'alice'),
        two = DiagnosticStore(disk, 'alice');
    await one.rememberCloud(const DiagnosticWorkspace(revision: 0));
    final results = await Future.wait([
      for (final (journal, key) in [
        (one, 'first-create-key'),
        (two, 'second-create-key'),
      ])
        journal
            .prepareCreate(createBody, key)
            .then<Object>((value) => value, onError: (Object error) => error),
    ]);
    expect(results.whereType<DiagnosticCommand>(), hasLength(1));
    expect(results.whereType<StateError>(), hasLength(1));
    expect((await two.read()).commands, hasLength(1));
  });

  test(
    'damaged and foreign-owner bundles are preserved, never overwritten',
    () async {
      final disk = MemoryStore();
      final alice = DiagnosticStore(disk, 'alice'),
          bob = DiagnosticStore(disk, 'bob');
      await alice.rememberCloud(const DiagnosticWorkspace(revision: 0));
      disk.data[bob.storageKey] = disk.data[alice.storageKey]!;
      final foreign = disk.data[bob.storageKey];
      await expectLater(bob.rememberCloud(created()), throwsFormatException);
      expect(disk.data[bob.storageKey], foreign);
      disk.data[alice.storageKey] = '{damaged';
      await expectLater(
        alice.prepareCreate(createBody, 'invalid-store-key'),
        throwsFormatException,
      );
      expect(disk.data[alice.storageKey], '{damaged');
    },
  );

  test(
    'body tampering is caught before a saved command can be replayed',
    () async {
      final disk = MemoryStore();
      final journal = DiagnosticStore(disk, 'alice');
      await journal.rememberCloud(const DiagnosticWorkspace(revision: 0));
      await journal.prepareCreate(createBody, 'tamper-create-key');
      final value =
          jsonDecode(disk.data[journal.storageKey]!) as Map<String, dynamic>;
      (value['commands'] as List).first['body']['subject'] = 'physics';
      disk.data[journal.storageKey] = jsonEncode(value);
      final damaged = disk.data[journal.storageKey];
      await expectLater(journal.read(), throwsFormatException);
      expect(disk.data[journal.storageKey], damaged);
    },
  );

  test('late receipt after explicit stop stays in history and never becomes pending', () async {
    final journal = DiagnosticStore(MemoryStore(), 'alice');
    await journal.rememberCloud(const DiagnosticWorkspace(revision: 0));
    await journal.prepareCreate(createBody, 'stopped-create-key');
    await journal.stop('stopped-create-key');
    await journal.recordResult('stopped-create-key', created().toJson());
    final bundle = await journal.read();
    expect(bundle.pending, isNull);
    expect(bundle.commands.single.phase, 'stopped');
    expect(bundle.commands.single.result, isNotNull);
    expect(bundle.cloud!.revision, 0);
  });

  test(
    'unknown receipts cannot unlock acknowledgement or overwrite known results',
    () async {
      final journal = DiagnosticStore(MemoryStore(), 'alice');
      await journal.rememberCloud(const DiagnosticWorkspace(revision: 0));
      await journal.prepareCreate(createBody, 'receipt-create-key');
      await expectLater(
        journal.acknowledge('receipt-create-key'),
        throwsStateError,
      );
      final wrong = created().toJson()..['revision'] = 2;
      await expectLater(
        journal.recordResult('receipt-create-key', wrong),
        throwsFormatException,
      );
      expect((await journal.read()).pending!.phase, 'prepared');
      await journal.recordResult('receipt-create-key', created().toJson());
      final changed = created().toJson();
      (changed['run'] as Map)['id'] = 'different-run';
      await expectLater(
        journal.recordResult('receipt-create-key', changed),
        throwsStateError,
      );
      expect((await journal.read()).pending!.result, created().toJson());
    },
  );

  test('open command pins plan position, question and version', () async {
    final journal = DiagnosticStore(MemoryStore(), 'alice');
    final workspace = created();
    await journal.rememberCloud(workspace);
    final command = await journal.prepareOpen(
      workspace.run!.id,
      1,
      const DiagnosticRevision(expectedRevision: 1),
      'open-session-key',
    );
    expect(command.questionId, workspace.run!.items.first.question.id);
    expect(command.questionVersion, workspace.run!.items.first.questionVersion);
    final wrong = fixtures.value('diagnostic_session')
      ..['question_version'] = 999;
    await expectLater(
      journal.recordResult(command.key, wrong),
      throwsFormatException,
    );
    await journal.recordResult(
      command.key,
      fixtures.value('diagnostic_session'),
    );
    expect((await journal.read()).pending!.phase, 'result_known');
    await expectLater(
      journal.prepareOpen(
        'different-run',
        1,
        const DiagnosticRevision(expectedRevision: 1),
        'different-open-key',
      ),
      throwsStateError,
    );
  });

  test(
    'late GET cannot erase known first submission at the same revision',
    () async {
      final journal = DiagnosticStore(MemoryStore(), 'alice');
      final old = fixtures.value('diagnostic_created');
      final progress = fixtures.value('diagnostic_created');
      final run = progress['run'] as Map;
      ((run['items'] as List).first as Map)['submission'] = {
        'attempt_id': 'first-attempt',
        'independent': true,
        'evaluation_state': 'verified',
        'is_correct': true,
      };
      run['summary']['submitted'] = 1;
      run['summary']['independent_correct'] = 1;
      await journal.rememberCloud(DiagnosticWorkspace.fromJson(progress));
      await journal.rememberCloud(DiagnosticWorkspace.fromJson(old));
      expect((await journal.cloud())!.run!.summary.submitted, 1);
      await journal.rememberCloud(const DiagnosticWorkspace(revision: 0));
      expect((await journal.cloud())!.revision, 1);
    },
  );
}
