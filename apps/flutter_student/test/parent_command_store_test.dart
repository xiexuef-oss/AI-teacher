import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/parent/parent_command_store.dart';

const code = '23456789AB';
const otherCode = '23456789AC';
final now = DateTime.utc(2026, 11, 16);
ParentInvite invite(int revision) => ParentInvite(
  id: 'invite',
  code: code,
  parentInviteRevision: revision,
  createdAt: now,
  expiresAt: now.add(const Duration(days: 1)),
);
Future<void> current(ParentCommandStore s, int? revision) async {
  final generation = await s.beginRefresh();
  await s.rememberCurrent(
    ParentLinks(links: [], parentInviteRevision: revision),
    generation: generation,
  );
}

void main() {
  test(
    'stored acknowledgement requires valid receipt, never GET equality',
    () async {
      final disk = MemoryStore();
      final s = ParentCommandStore(disk, 'student-a', 'student');
      await current(s, 0);
      await s.prepareCreate(
        const ParentInviteCreate(expectedParentInviteRevision: 0),
        key: 'create-key',
        activeEpoch: 1,
      );
      await current(s, 1);
      await expectLater(
        s.acknowledgeStoredResult('create-key'),
        throwsStateError,
      );
      await s.recordResult('create-key', invite(1));
      final before = disk.data[s.key];
      disk.failWrites = true;
      await expectLater(
        s.acknowledgeStoredResult('create-key'),
        throwsStateError,
      );
      expect(disk.data[s.key], before);
      disk.failWrites = false;
      final value = jsonDecode(before!) as Map;
      (value['commands'] as List).single['result']['code'] = code;
      disk.data[s.key] = jsonEncode(value);
      final damaged = disk.data[s.key];
      await expectLater(
        s.acknowledgeStoredResult('create-key'),
        throwsFormatException,
      );
      expect(disk.data[s.key], damaged);
    },
  );

  test('expired delivery explicitly acknowledges stored successful create after lost ACK', () async {
    final disk = MemoryStore();
    final store = ParentCommandStore(disk, 'student-a', 'student');
    await current(store, 0);
    await store.prepareCreate(
      const ParentInviteCreate(expectedParentInviteRevision: 0),
      key: 'known-create',
      activeEpoch: 1,
    );
    await store.recordResult('known-create', invite(1));
    disk.failWrites = true;
    await expectLater(store.acknowledge('known-create'), throwsStateError);
    disk.failWrites = false;
    final restarted = ParentCommandStore(disk, 'student-a', 'student');
    expect((await restarted.read())!.active!.phase, 'result_known');
    await restarted.reject('known-create', code: 'invite_response_expired');
    final bundle = (await restarted.read())!;
    expect(bundle.commands.single.result!['id'], 'invite');
    expect(bundle.commands.single.deliveryUnavailable, isTrue);
    expect(bundle.commands.single.phase, 'result_known');
    await restarted.acknowledgeStoredResult('known-create');
    expect((await restarted.read())!.active, isNull);
  });

  test('redeem stored result can be acknowledged offline after lost ACK without code', () async {
    final disk = MemoryStore();
    final store = ParentCommandStore(disk, 'parent-a', 'parent');
    await store.prepareRedeem(
      const ParentInviteRedeem(code: code),
      key: 'known-redeem',
      activeEpoch: 1,
    );
    await store.recordResult(
      'known-redeem',
      ParentStudent(studentId: 'student', linkedAt: now),
    );
    disk.failWrites = true;
    await expectLater(store.acknowledge('known-redeem'), throwsStateError);
    disk.failWrites = false;
    final restarted = ParentCommandStore(disk, 'parent-a', 'parent');
    expect((await restarted.read())!.active!.phase, 'result_known');
    await restarted.acknowledgeStoredResult('known-redeem');
    expect((await restarted.read())!.active, isNull);
    expect(
      (await restarted.read())!.commands.single.result!['student_id'],
      'student',
    );
    expect(jsonEncode(disk.data).contains(code), isFalse);
  });

  test(
    'revoke captures exact grant revision and explicit conflict keeps history',
    () async {
      final disk = MemoryStore();
      final s = ParentCommandStore(disk, 'student-a', 'student');
      ParentLink link(int revision) => ParentLink(
        id: 'link-a',
        parentId: 'parent-a',
        consentAt: now,
        linkedAt: now,
        authorizationRevision: revision,
      );
      final ticket = await s.beginRefresh();
      await s.rememberCurrent(
        ParentLinks(links: [link(3)]),
        generation: ticket,
      );
      await expectLater(
        s.prepareRevoke(
          'link-a',
          const ParentLinkRevoke(expectedAuthorizationRevision: 1),
          key: 'revoke-key',
          activeEpoch: 1,
        ),
        throwsStateError,
      );
      final command = await s.prepareRevoke(
        'link-a',
        const ParentLinkRevoke(expectedAuthorizationRevision: 3),
        key: 'revoke-key',
        activeEpoch: 1,
      );
      await s.reject(command.key, code: 'authorization_revision_conflict');
      expect((await s.read())!.active!.phase, 'conflict');
      disk.failWrites = true;
      await expectLater(
        s.resolveConflict(command.key, generation: command.generation),
        throwsStateError,
      );
      expect((await s.read())!.active!.phase, 'conflict');
      disk.failWrites = false;
      await s.resolveConflict(command.key, generation: command.generation);
      expect((await s.read())!.active, isNull);
      expect(
        (await s.read())!
            .commands
            .single
            .body!['expected_authorization_revision'],
        3,
      );
    },
  );

  test(
    'expired create replay separates unknown outcome from known success',
    () async {
      for (final known in [false, true]) {
        final s = ParentCommandStore(MemoryStore(), 'student-a', 'student');
        await current(s, 0);
        await s.prepareCreate(
          const ParentInviteCreate(expectedParentInviteRevision: 0),
          key: 'create-key',
          activeEpoch: 1,
        );
        if (known) {
          await s.recordResult('create-key', invite(1));
          await s.acknowledge('create-key');
        }
        await s.reject('create-key', code: 'invite_response_expired');
        final command = (await s.read())!.commands.single;
        expect(command.deliveryUnavailable, isTrue);
        expect(command.phase, known ? 'acked' : 'outcome_unavailable');
        if (!known) {
          await expectLater(s.acknowledge('create-key'), throwsStateError);
        }
      }
    },
  );

  test(
    'determinate reject write failure retains original prepared intent',
    () async {
      final disk = MemoryStore();
      final s = ParentCommandStore(disk, 'parent-a', 'parent');
      await s.prepareRedeem(
        const ParentInviteRedeem(code: code),
        key: 'redeem-key',
        activeEpoch: 1,
      );
      disk.failWrites = true;
      await expectLater(
        s.reject('redeem-key', code: 'invite_invalid'),
        throwsStateError,
      );
      expect((await s.read())!.active!.phase, 'prepared');
      disk.failWrites = false;
      await s.reject('redeem-key', code: 'invite_invalid');
      expect((await s.read())!.active, isNull);
      expect((await s.read())!.commands.single.phase, 'rejected');
    },
  );

  test(
    'body/key mismatch cannot reuse old intent and role cannot cross',
    () async {
      final disk = MemoryStore();
      final s = ParentCommandStore(disk, 'student-a', 'student');
      await current(s, 0);
      await s.prepareCreate(
        const ParentInviteCreate(expectedParentInviteRevision: 0),
        key: 'create-key',
        activeEpoch: 1,
      );
      await expectLater(
        s.prepareCreate(
          const ParentInviteCreate(expectedParentInviteRevision: 1),
          key: 'create-key',
          activeEpoch: 1,
        ),
        throwsStateError,
      );
      await expectLater(
        s.prepareRedeem(
          const ParentInviteRedeem(code: code),
          key: 'redeem-key',
          activeEpoch: 1,
        ),
        throwsArgumentError,
      );
      final parent = ParentCommandStore(disk, 'student-a', 'parent');
      expect(await parent.read(), isNull);
      final raw = jsonDecode(disk.data[s.key]!) as Map;
      (raw['commands'] as List).single['body']['unexpected'] = 'must preserve';
      disk.data[s.key] = jsonEncode(raw);
      final before = disk.data[s.key];
      await expectLater(s.beginRefresh(), throwsFormatException);
      expect(disk.data[s.key], before);
    },
  );

  test('canonical normalization matches shared backend fixtures', () {
    final rows = jsonDecode(
      File('../../contracts/fixtures/parent_invite_normalization.json')
          .readAsStringSync(),
    ) as List;
    for (final row in rows) {
      expect(
        normalizeParentInviteCode(row['input'] as String),
        row['normalized'],
      );
    }
  });
  test(
    'redeem restart requires same normalized body and stores no code',
    () async {
      final disk = MemoryStore();
      final s = ParentCommandStore(disk, 'parent-a', 'parent');
      final command = await s.prepareRedeem(
        const ParentInviteRedeem(code: '23-456789ab'),
        key: 'redeem-key',
        activeEpoch: 1,
      );
      expect(command.body, isNull);
      expect(jsonEncode(disk.data).contains(code), isFalse);
      expect(jsonEncode(disk.data).contains('23-456789ab'), isFalse);
      final restored = ParentCommandStore(disk, 'parent-a', 'parent');
      expect(
        (await restored.redeemBody(
          command.key,
          const ParentInviteRedeem(code: '23456 789Ab'),
        )).code,
        code,
      );
      await expectLater(
        restored.redeemBody(
          command.key,
          const ParentInviteRedeem(code: otherCode),
        ),
        throwsStateError,
      );
      expect((await restored.read())!.active!.key, command.key);
    },
  );
  test(
    'create body/key frozen; receipt sanitized and never replaces current',
    () async {
      final disk = MemoryStore();
      final s = ParentCommandStore(disk, 'student-a', 'student');
      await current(s, 1);
      await s.prepareCreate(
        const ParentInviteCreate(expectedParentInviteRevision: 1),
        key: 'create-key',
        activeEpoch: 2,
      );
      await current(s, 3);
      await s.recordResult('create-key', invite(2));
      await s.acknowledge('create-key');
      final bundle = (await s.read())!;
      expect(bundle.current!['parent_invite_revision'], 3);
      expect(bundle.commands.single.result!['parent_invite_revision'], 2);
      expect(jsonEncode(disk.data).contains(code), isFalse);
      expect(bundle.commands.single.result!.containsKey('code'), isFalse);
    },
  );
  test('unknown legacy version cannot prepare and GET does not ACK', () async {
    final s = ParentCommandStore(MemoryStore(), 'student-a', 'student');
    await current(s, null);
    await expectLater(
      s.prepareCreate(
        const ParentInviteCreate(expectedParentInviteRevision: 0),
        key: 'create-key',
        activeEpoch: 1,
      ),
      throwsStateError,
    );
    await current(s, 0);
    await s.prepareCreate(
      const ParentInviteCreate(expectedParentInviteRevision: 0),
      key: 'create-key',
      activeEpoch: 1,
    );
    await current(s, 1);
    expect((await s.read())!.active!.phase, 'prepared');
    await expectLater(
      s.prepareCreate(
        const ParentInviteCreate(expectedParentInviteRevision: 1),
        key: 'new-key-123',
        activeEpoch: 1,
      ),
      throwsStateError,
    );
  });
  test(
    'abandoned unknown frees lane while late old result cannot claim new lane',
    () async {
      final s = ParentCommandStore(MemoryStore(), 'parent-a', 'parent');
      final a = await s.prepareRedeem(
        const ParentInviteRedeem(code: code),
        key: 'old-key-123',
        activeEpoch: 1,
      );
      await s.abandonUnknown(a.key, generation: a.generation);
      await expectLater(
        s.prepareRedeem(
          const ParentInviteRedeem(code: code),
          key: 'same-key',
          activeEpoch: 1,
        ),
        throwsStateError,
      );
      await s.prepareRedeem(
        const ParentInviteRedeem(code: otherCode),
        key: 'new-key-123',
        activeEpoch: 1,
      );
      await s.recordResult(
        a.key,
        ParentStudent(studentId: 'student-a', linkedAt: now),
      );
      await s.acknowledge(a.key);
      expect((await s.read())!.active!.key, 'new-key-123');
      expect(
        (await s.read())!.commands.first.retryDisposition,
        'abandoned_unknown',
      );
    },
  );
  test(
    'failed prepare result ack abandon writes preserve original bundle',
    () async {
      final disk = MemoryStore();
      final s = ParentCommandStore(disk, 'parent-a', 'parent');
      disk.failWrites = true;
      await expectLater(
        s.prepareRedeem(
          const ParentInviteRedeem(code: code),
          key: 'redeem-key',
          activeEpoch: 1,
        ),
        throwsStateError,
      );
      expect(disk.data, isEmpty);
      disk.failWrites = false;
      final command = await s.prepareRedeem(
        const ParentInviteRedeem(code: code),
        key: 'redeem-key',
        activeEpoch: 1,
      );
      final before = Map.of(disk.data);
      disk.failWrites = true;
      await expectLater(
        s.recordResult(
          command.key,
          ParentStudent(studentId: 'student', linkedAt: now),
        ),
        throwsStateError,
      );
      await expectLater(
        s.abandonUnknown(command.key, generation: command.generation),
        throwsStateError,
      );
      expect(disk.data, before);
      disk.failWrites = false;
      await s.recordResult(
        command.key,
        ParentStudent(studentId: 'student', linkedAt: now),
      );
      disk.failWrites = true;
      await expectLater(s.acknowledge(command.key), throwsStateError);
      expect((await s.read())!.active!.phase, 'result_known');
    },
  );
  test('refresh ticket prevents old GET overwriting new state', () async {
    final s = ParentCommandStore(MemoryStore(), 'student-a', 'student');
    final a = await s.beginRefresh();
    final b = await s.beginRefresh();
    await s.rememberCurrent(
      ParentLinks(links: [], parentInviteRevision: 2),
      generation: b,
    );
    await s.rememberCurrent(
      ParentLinks(links: [], parentInviteRevision: 1),
      generation: a,
    );
    expect((await s.read())!.current!['parent_invite_revision'], 2);
  });
  test('unknown/wrong owner bundle remains untouched', () async {
    final disk = MemoryStore();
    final s = ParentCommandStore(disk, 'student-a', 'student');
    disk.data[s.key] = '{"v":99,"owner":"other","precious":"input"}';
    final before = disk.data[s.key];
    await expectLater(s.beginRefresh(), throwsFormatException);
    expect(disk.data[s.key], before);
  });
}
