import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/profile/profile_journal_store.dart';

StudentProfile cloud(int revision, [String name = 'cloud']) =>
    StudentProfile.fromJson({
      'user_id': 'alice',
      'display_name': name,
      'subjects': ['math'],
      'onboarding_completed': false,
      'notices': <dynamic>[],
      'updated_at': '2026-11-16T00:00:00Z',
      'revision': revision,
    });

ProfileUpdate edit(String name, int revision) => ProfileUpdate.fromJson({
  'region_code': 'CN-51',
  'subjects': ['math'],
  'display_name': name,
  'expected_revision': revision,
});

void main() {
  test(
    'explicit local choice rebases while stale cloud choice keeps new input',
    () async {
      final store = ProfileJournalStore(MemoryStore(), 'alice');
      await store.rememberCloud(cloud(1));
      await store.edit(ProfileEdit(edit('mine', 1).toJson()));
      await store.rememberCloud(cloud(2, 'theirs'));
      final choosing = (await store.read())!;
      expect(choosing.editConflict, isTrue);
      expect(choosing.editBaseRevision, 1);
      await store.edit(ProfileEdit(edit('newer input', 1).toJson()));
      await expectLater(
        store.resolveEditConflict(
          editGeneration: choosing.editGeneration,
          useCloud: true,
        ),
        throwsStateError,
      );
      expect((await store.read())!.edit!['display_name'], 'newer input');
      await store.resolveEditConflict(editGeneration: 2);
      expect((await store.read())!.editBaseRevision, 2);
      await store.prepare(
        edit('newer input', 2),
        idempotencyKey: 'explicit',
        activeEpoch: 1,
      );
    },
  );

  test('refresh cannot silently rebase an unprepared edit', () async {
    final disk = MemoryStore();
    final store = ProfileJournalStore(disk, 'alice');
    await store.rememberCloud(cloud(1));
    await store.edit(ProfileEdit(edit('mine', 1).toJson()));
    await store.rememberCloud(cloud(2, 'theirs'));
    await store.edit(ProfileEdit(edit('mine', 2).toJson()));
    await expectLater(
      store.prepare(edit('mine', 2), idempotencyKey: 'new', activeEpoch: 1),
      throwsStateError,
    );
    expect(
      (await ProfileJournalStore(disk, 'alice').read())!.edit!['display_name'],
      'mine',
    );
  });

  test(
    'unknown offline edit source is not rebased by first real GET',
    () async {
      final store = ProfileJournalStore(MemoryStore(), 'alice');
      await store.edit(ProfileEdit(edit('mine', 0).toJson()));
      await store.rememberCloud(cloud(0));
      await expectLater(
        store.prepare(edit('mine', 0), idempotencyKey: 'new', activeEpoch: 1),
        throwsStateError,
      );
    },
  );

  test(
    'receipt may safely advance newer edit source only without newer cloud',
    () async {
      for (final newerCloud in [false, true]) {
        final store = ProfileJournalStore(MemoryStore(), 'alice');
        await store.rememberCloud(cloud(1));
        await store.edit(ProfileEdit(edit('A', 1).toJson()));
        await store.prepare(edit('A', 1), idempotencyKey: 'a', activeEpoch: 1);
        await store.edit(ProfileEdit(edit('B', 1).toJson()));
        if (newerCloud) await store.rememberCloud(cloud(3, 'C'));
        await store.recordResult('a', cloud(2, 'A'));
        await store.acknowledge('a');
        final action = store.prepare(
          edit('B', newerCloud ? 3 : 2),
          idempotencyKey: 'b',
          activeEpoch: 1,
        );
        if (newerCloud) {
          await expectLater(action, throwsStateError);
        } else {
          expect((await action).body.displayName, 'B');
        }
      }
    },
  );

  test(
    'same revision allows derived notices but rejects changed persisted data',
    () async {
      final disk = MemoryStore();
      final store = ProfileJournalStore(disk, 'alice');
      await store.rememberCloud(cloud(1));
      final refreshed = cloud(1).toJson()
        ..['notices'] = [
          {'code': 'configuration_updated', 'message': 'updated'},
        ]
        ..['exam_scheme_code'] = 'configuration-derived';
      await store.rememberCloud(StudentProfile.fromJson(refreshed));
      final before = disk.data[store.key];
      await expectLater(
        store.rememberCloud(cloud(1, 'changed')),
        throwsStateError,
      );
      expect(disk.data[store.key], before);
    },
  );

  test(
    'short concurrent edits serialize and retain the latest input',
    () async {
      final disk = MemoryStore();
      final first = ProfileJournalStore(disk, 'alice');
      final second = ProfileJournalStore(disk, 'alice');
      await Future.wait([
        first.edit(ProfileEdit({'display_name': 'first'})),
        second.edit(ProfileEdit({'display_name': 'second'})),
      ]);
      final bundle = (await first.read())!;
      expect(bundle.editGeneration, 2);
      expect(bundle.edit!['display_name'], 'second');
    },
  );

  test(
    'damaged pending body remains untouched and blocks another edit',
    () async {
      final disk = MemoryStore();
      final store = ProfileJournalStore(disk, 'alice');
      await store.rememberCloud(cloud(1));
      await store.edit(
        ProfileEdit({
          'region_code': 'CN-51',
          'subjects': ['math'],
          'display_name': 'A',
        }),
      );
      await store.prepare(edit('A', 1), idempotencyKey: 'a', activeEpoch: 1);
      final value = jsonDecode(disk.data[store.key]!) as Map;
      ((value['commands'] as List).single['body'] as Map).remove(
        'expected_revision',
      );
      disk.data[store.key] = jsonEncode(value);
      final before = disk.data[store.key];
      await expectLater(
        store.edit(ProfileEdit({'display_name': 'B'})),
        throwsFormatException,
      );
      expect(disk.data[store.key], before);
    },
  );

  test(
    'failed rejection and conflict resolution preserve both sides',
    () async {
      final disk = MemoryStore();
      final store = ProfileJournalStore(disk, 'alice');
      await store.rememberCloud(cloud(1));
      await store.edit(
        ProfileEdit({
          'region_code': 'CN-51',
          'subjects': ['math'],
          'display_name': 'mine',
        }),
      );
      await store.prepare(edit('mine', 1), idempotencyKey: 'a', activeEpoch: 1);
      disk.failWrites = true;
      await expectLater(
        store.reject(
          'a',
          code: 'profile_revision_conflict',
          cloud: cloud(2, 'theirs'),
        ),
        throwsStateError,
      );
      expect((await store.read())!.pending!.phase, 'prepared');
      disk.failWrites = false;
      await store.reject(
        'a',
        code: 'profile_revision_conflict',
        cloud: cloud(2, 'theirs'),
      );
      disk.failWrites = true;
      await expectLater(
        store.resolveConflict('a', editGeneration: 1, useCloud: true),
        throwsStateError,
      );
      final bundle = (await store.read())!;
      expect(bundle.pending!.phase, 'conflict');
      expect(bundle.edit!['display_name'], 'mine');
      expect(bundle.cloud!.displayName, 'theirs');
      disk.failWrites = false;
      await store.resolveConflict('a', editGeneration: 1, useCloud: true);
      expect((await store.read())!.edit, isNull);
      expect((await store.read())!.commands.single.body.displayName, 'mine');
    },
  );

  test(
    'incomplete offline input persists without inventing a revision',
    () async {
      final disk = MemoryStore();
      final store = ProfileJournalStore(disk, 'alice');
      await store.edit(
        ProfileEdit({'region_code': null, 'subjects': [], 'display_name': ''}),
      );
      final restored = (await ProfileJournalStore(disk, 'alice').read())!;
      expect(restored.revision, isNull);
      expect(restored.edit, {
        'region_code': null,
        'subjects': [],
        'display_name': '',
      });
    },
  );

  test(
    'wrong owner bundle is preserved and wrong owner response cannot write',
    () async {
      final disk = MemoryStore();
      final store = ProfileJournalStore(disk, 'alice');
      await store.rememberCloud(cloud(1));
      final before = disk.data[store.key];
      final wrong = cloud(2).toJson()..['user_id'] = 'bob';
      await expectLater(
        store.rememberCloud(StudentProfile.fromJson(wrong)),
        throwsFormatException,
      );
      expect(disk.data[store.key], before);
      final bundle = jsonDecode(before!) as Map<String, dynamic>;
      bundle['owner'] = 'bob';
      disk.data[store.key] = jsonEncode(bundle);
      final raw = disk.data[store.key];
      await expectLater(
        store.edit(ProfileEdit({'display_name': 'input'})),
        throwsFormatException,
      );
      expect(disk.data[store.key], raw);
    },
  );

  test('new edit cannot create a second pending intent', () async {
    final store = ProfileJournalStore(MemoryStore(), 'alice');
    await store.rememberCloud(cloud(1));
    await store.edit(
      ProfileEdit({
        'region_code': 'CN-51',
        'subjects': ['math'],
        'display_name': 'A',
      }),
    );
    await store.prepare(edit('A', 1), idempotencyKey: 'a', activeEpoch: 1);
    await store.edit(
      ProfileEdit({
        'region_code': 'CN-51',
        'subjects': ['math'],
        'display_name': 'B',
      }),
    );
    await expectLater(
      store.prepare(edit('B', 1), idempotencyKey: 'b', activeEpoch: 1),
      throwsStateError,
    );
    expect((await store.read())!.commands, hasLength(1));
  });

  test(
    'A receipt and acknowledgement preserve newer edit B and cloud',
    () async {
      final disk = MemoryStore();
      final store = ProfileJournalStore(disk, 'alice');
      await store.rememberCloud(cloud(1));
      await store.edit(
        ProfileEdit({
          'region_code': 'CN-51',
          'subjects': ['math'],
          'display_name': 'A',
        }),
      );
      final a = await store.prepare(
        edit('A', 1),
        idempotencyKey: 'key-a',
        activeEpoch: 7,
      );
      await store.edit(
        ProfileEdit({
          'region_code': 'CN-51',
          'subjects': ['math'],
          'display_name': 'B',
        }),
      );
      await store.rememberCloud(cloud(3, 'newer'));
      await store.recordResult(a.idempotencyKey, cloud(2, 'A'));
      await store.acknowledge(a.idempotencyKey);
      final restored = (await ProfileJournalStore(disk, 'alice').read())!;
      expect(restored.edit!['display_name'], 'B');
      expect(restored.cloud!.toJson()['revision'], 3);
      expect(restored.commands.single.result!.displayName, 'A');
      expect(restored.commands.single.phase, 'acked');
    },
  );

  test(
    'prepared replay freezes body/key and cannot reuse with other body',
    () async {
      final store = ProfileJournalStore(MemoryStore(), 'alice');
      await store.rememberCloud(cloud(1));
      await store.edit(
        ProfileEdit({
          'region_code': 'CN-51',
          'subjects': ['math'],
          'display_name': 'A',
        }),
      );
      final a = await store.prepare(
        edit('A', 1),
        idempotencyKey: 'key',
        activeEpoch: 1,
      );
      await store.edit(
        ProfileEdit({
          'region_code': 'CN-51',
          'subjects': ['math'],
          'display_name': 'B',
        }),
      );
      expect(
        (await store.read())!.commands.single.body.toJson(),
        a.body.toJson(),
      );
      await expectLater(
        store.prepare(edit('B', 1), idempotencyKey: 'key', activeEpoch: 1),
        throwsStateError,
      );
    },
  );

  test(
    'failed edit prepare result and ack writes leave previous bundle intact',
    () async {
      final disk = MemoryStore();
      final store = ProfileJournalStore(disk, 'alice');
      await store.rememberCloud(cloud(1));
      await store.edit(
        ProfileEdit({
          'region_code': 'CN-51',
          'subjects': ['math'],
          'display_name': 'A',
        }),
      );
      final before = disk.data[store.key];
      disk.failWrites = true;
      await expectLater(
        store.edit(
          ProfileEdit({
            'region_code': 'CN-51',
            'subjects': ['math'],
            'display_name': 'B',
          }),
        ),
        throwsStateError,
      );
      await expectLater(
        store.prepare(edit('A', 1), idempotencyKey: 'key', activeEpoch: 1),
        throwsStateError,
      );
      expect(disk.data[store.key], before);
      disk.failWrites = false;
      await store.prepare(edit('A', 1), idempotencyKey: 'key', activeEpoch: 1);
      disk.failWrites = true;
      await expectLater(
        store.recordResult('key', cloud(2, 'A')),
        throwsStateError,
      );
      expect((await store.read())!.commands.single.phase, 'prepared');
      disk.failWrites = false;
      await store.recordResult('key', cloud(2, 'A'));
      disk.failWrites = true;
      await expectLater(store.acknowledge('key'), throwsStateError);
      expect((await store.read())!.commands.single.phase, 'result_known');
      expect((await store.read())!.edit!['display_name'], 'A');
    },
  );

  test('unknown bundle is preserved and blocks mutations', () async {
    final disk = MemoryStore();
    final store = ProfileJournalStore(disk, 'alice');
    const raw = '{"v":99,"owner":"alice","precious":"input"}';
    disk.data[store.key] = raw;
    await expectLater(store.read(), throwsFormatException);
    await expectLater(store.rememberCloud(cloud(1)), throwsFormatException);
    expect(disk.data[store.key], raw);
  });

  test('legacy revision stays unknown and is never treated as zero', () async {
    final disk = MemoryStore();
    final legacy = cloud(0).toJson()..remove('revision');
    disk.data['u/alice/profile'] = jsonEncode(legacy);
    final store = ProfileJournalStore(disk, 'alice');
    expect((await store.read())!.revision, isNull);
    await store.edit(
      ProfileEdit({
        'region_code': 'CN-51',
        'subjects': ['math'],
        'display_name': 'offline',
      }),
    );
    await expectLater(
      store.prepare(edit('offline', 0), idempotencyKey: 'key', activeEpoch: 1),
      throwsStateError,
    );
    expect((await store.read())!.legacyProfile, legacy);
    await store.rememberCloud(cloud(0));
    await store.resolveEditConflict(editGeneration: 1);
    await store.prepare(
      edit('offline', 0),
      idempotencyKey: 'key',
      activeEpoch: 1,
    );
  });

  test(
    'conflict retains both sides and needs an explicit new intent',
    () async {
      final store = ProfileJournalStore(MemoryStore(), 'alice');
      await store.rememberCloud(cloud(1));
      await store.edit(
        ProfileEdit({
          'region_code': 'CN-51',
          'subjects': ['math'],
          'display_name': 'mine',
        }),
      );
      await store.prepare(
        edit('mine', 1),
        idempotencyKey: 'key',
        activeEpoch: 1,
      );
      await store.reject(
        'key',
        code: 'profile_revision_conflict',
        cloud: cloud(2, 'theirs'),
      );
      final bundle = (await store.read())!;
      expect(bundle.commands.single.phase, 'conflict');
      expect(bundle.edit!['display_name'], 'mine');
      expect(bundle.cloud!.displayName, 'theirs');
      await expectLater(
        store.prepare(edit('mine', 2), idempotencyKey: 'new', activeEpoch: 1),
        throwsStateError,
      );
      await store.resolveConflict('key', editGeneration: 1);
      await store.prepare(
        edit('mine', 2),
        idempotencyKey: 'new',
        activeEpoch: 1,
      );
      expect((await store.read())!.commands, hasLength(2));
    },
  );
}
