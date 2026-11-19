import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/features/parent/parent_command_store.dart';
import 'package:tutor_student/features/profile/local_recovery_export.dart';
import 'package:tutor_student/features/profile/profile_journal_store.dart';
import 'package:tutor_student/features/profile/profile_page.dart';
import 'package:tutor_student/features/profile/student_data_export_section.dart';
import 'package:tutor_student/features/solve/draft_store.dart';
import 'package:tutor_student/features/solve/resource_journal_store.dart';

import 'profile_journal_store_test.dart' show cloud, edit;
import 'parent_command_store_test.dart' show current, invite;
import 'support/fake_backend.dart';
import 'support/app_harness.dart';
import 'local_draft_export_section_test.dart' show HeldReadStore;

class ForeignKeyStore extends MemoryStore {
  bool readForeign = false;
  @override
  Future<List<String>> keys(String prefix) async => [
    'u/bob/resource-journal/session/private',
  ];
  @override
  Future<String?> read(String key) async {
    if (key.startsWith('u/bob/')) readForeign = true;
    return super.read(key);
  }
}

Future<ResourceCommand> tutor(MemoryStore disk, String owner) async {
  final fixtures = Fixtures.load();
  final q = Question.fromJson(fixtures.value('question_single_choice'));
  final session = StudySession.fromJson(fixtures.value('session_created'));
  const aid = 'local-attempt';
  final source = DraftStore(disk, owner).forAttempt(aid);
  await source.claimScope(q.id);
  await source.saveWorkspaceContext(
    q.id,
    DraftWorkspaceContext(
      workspaceId: aid,
      question: q,
      trustedSessionId: session.id,
      sessionBody: SessionCreate(
        questionId: q.id,
        origin: SessionOrigin.practice,
        expectedQuestionVersion: q.version,
      ).toJson(),
    ),
  );
  await source.writeActive(
    q.id,
    ActiveRef(sessionId: session.id, attemptId: aid),
  );
  return ResourceJournalStore(disk, owner).prepareTutor(
    source: source,
    questionId: q.id,
    sessionId: session.id,
    body: const TutorAction(
      action: TutorActionType.requestHint,
      confirmEndIndependent: false,
    ),
  );
}

Future<void> seed(MemoryStore disk) async {
  final profile = ProfileJournalStore(disk, 'alice');
  await profile.rememberCloud(cloud(1));
  await profile.edit(ProfileEdit(edit('unsynced-name', 1).toJson()));
  await profile.prepare(
    edit('unsynced-name', 1),
    idempotencyKey: 'profile-key',
    activeEpoch: 83,
  );
  final parent = ParentCommandStore(disk, 'alice', 'student');
  await current(parent, 0);
  await parent.prepareCreate(
    const ParentInviteCreate(expectedParentInviteRevision: 0),
    key: 'invite-key',
    activeEpoch: 83,
  );
  await parent.recordResult('invite-key', invite(1));
  await tutor(disk, 'alice');
}

void main() {
  testWidgets('profile offers one combined recovery export entry', (
    tester,
  ) async {
    final h = AppHarness()..signInAs(role: 'student');
    await tester.pumpWidget(h.page(const ProfilePage()));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('profile.exportRecovery')),
      500,
      scrollable: find.byType(Scrollable).first,
    );
    expect(
      find.byKey(const ValueKey('profile.exportRecovery')),
      findsOneWidget,
    );
  });
  test('combined export keeps own unsynced commands and never writes or leaks credentials', () async {
    final disk = MemoryStore({
      'auth.token': 'private-token',
      'u/bob/profile_bundle': 'private-other-owner',
      'u/alice/parent_authorization_bundle/parent': 'private-parent-role',
    });
    await seed(disk);
    final before = Map.of(disk.data);
    disk.failWrites = true;
    final value = await exportLocalRecoveryRecords(disk, 'alice');
    expect(value['scope'], 'local_student_recovery_records');
    expect(value['owner_id'], 'alice');
    expect(value['history_complete'], false);
    expect(value['consistent_snapshot'], false);
    expect(value['profile']['edit']['display_name'], 'unsynced-name');
    expect(value['profile']['commands'].single['key'], 'profile-key');
    expect(value['authorization']['commands'].single['key'], 'invite-key');
    expect(value['authorization']['commands'].single['result']['id'], 'invite');
    expect(value['resources'].single['commands'].single['phase'], 'prepared');
    expect(
      value['resources'].single['commands'].single['body']['action'],
      'request_hint',
    );
    for (final secret in [
      'private-token',
      'private-other-owner',
      'private-parent-role',
      '23456789AB',
      'activeEpoch',
      'active_epoch',
      'checksum',
      'fingerprint',
    ]) {
      expect(jsonEncode(value), isNot(contains(secret)));
    }
    expect(disk.data, before);
  });

  test('empty snapshot creates no bundles or migrations', () async {
    final disk = MemoryStore();
    final value = await exportLocalRecoveryRecords(disk, 'alice');
    expect(value['profile'], isNull);
    expect(value['authorization'], isNull);
    expect(value['resources'], isEmpty);
    expect(disk.data, isEmpty);
  });

  test(
    'legacy profile is projected without migrating or exposing unknown fields',
    () async {
      final disk = MemoryStore({
        'u/alice/profile': jsonEncode({
          ...cloud(1).toJson(),
          'private_token': 'legacy-private-token',
        }),
      });
      final before = Map.of(disk.data);
      final value = await exportLocalRecoveryRecords(disk, 'alice');
      expect(value['profile']['legacy_profile']['user_id'], 'alice');
      expect(jsonEncode(value), isNot(contains('legacy-private-token')));
      expect(disk.data, before);
    },
  );

  test(
    'resource enumeration rejects foreign keys before reading another identity',
    () async {
      final disk = ForeignKeyStore();
      await expectLater(
        exportLocalRecoveryRecords(disk, 'alice'),
        throwsFormatException,
      );
      expect(disk.readForeign, false);
    },
  );

  test(
    'resource export rechecks source owner even with matching local checksums',
    () async {
      final disk = MemoryStore();
      final command = await tutor(disk, 'alice');
      final key = disk.data.keys.singleWhere(
        (key) => key.startsWith('u/alice/resource-journal/'),
      );
      final raw = jsonDecode(disk.data[key]!) as Map;
      final c = raw['history'][command.intentId] as Map;
      c['source']['owner'] = 'bob';
      c.remove('checksum');
      c['checksum'] = journalHash(c);
      raw.remove('checksum');
      raw['checksum'] = journalHash(raw);
      disk.data[key] = jsonEncode(raw);
      final before = Map.of(disk.data);
      await expectLater(
        exportLocalRecoveryRecords(disk, 'alice'),
        throwsFormatException,
      );
      expect(disk.data, before);
    },
  );

  test('authorization exports current links and revoke receipt without parent identities', () async {
    final disk = MemoryStore();
    await seed(disk);
    final s = ParentCommandStore(disk, 'alice', 'student');
    await s.acknowledgeStoredResult('invite-key');
    final link = ParentLink(
      id: 'link',
      parentId: 'private-parent-id',
      parentLabel: 'private-parent-label',
      consentAt: DateTime.utc(2026),
      linkedAt: DateTime.utc(2026),
      authorizationRevision: 1,
    );
    await s.rememberCurrent(
      ParentLinks(links: [link], parentInviteRevision: 1),
      generation: await s.beginRefresh(),
    );
    await s.prepareRevoke(
      'link',
      const ParentLinkRevoke(expectedAuthorizationRevision: 1),
      key: 'revoke-key',
      activeEpoch: 91,
    );
    await s.recordResult(
      'revoke-key',
      ParentLink.fromJson({
        ...link.toJson(),
        'authorization_revision': 2,
        'revoked_at': DateTime.utc(2026, 1, 2).toIso8601String(),
      }),
    );
    final before = Map.of(disk.data);
    final value = (await exportLocalRecoveryRecords(
      disk,
      'alice',
    ))['authorization'];
    expect(value['current']['links'].single['id'], 'link');
    expect(value['commands'].last['result']['authorization_revision'], 2);
    expect(jsonEncode(value), isNot(contains('private-parent')));
    expect(jsonEncode(value), isNot(contains('23456789AB')));
    expect(disk.data, before);
  });

  test('compacted tutor receipts and cached view remain exported without checksums', () async {
    final disk = MemoryStore();
    final first = await tutor(disk, 'alice');
    final resources = ResourceJournalStore(disk, 'alice');
    final target = ResourceTarget.session(first.source.sessionId);
    final session = StudySession.fromJson({
      ...Fixtures.load().value('session_created'),
      'id': target.id,
      'question_id': first.source.questionId,
      'question_version': first.source.questionVersion,
      'last_event_seq': 0,
    });
    final known = await resources.recordResult(
      target,
      intentId: first.intentId,
      expectedGeneration: first.generation,
      result: TutorStep(session: session, events: []).toJson(),
    );
    final ticket = await resources.beginRefresh(
      target,
      intentId: known.intentId,
      expectedGeneration: known.generation,
    );
    await resources.ackTutor(
      ticket,
      latestSession: session,
      events: ResourceEventRefresh(target.id)
        ..addPage(const TutorEventPage(items: [], lastSeq: 0)),
    );
    final source = DraftStore(disk, 'alice').forAttempt(first.source.attemptId);
    await source.claimScope(first.source.questionId);
    final second = await resources.prepareTutor(
      source: source,
      questionId: first.source.questionId,
      sessionId: target.id,
      body: const TutorAction(action: TutorActionType.requestHint),
    );
    final before = Map.of(disk.data);
    final resource = (await exportLocalRecoveryRecords(
      disk,
      'alice',
    ))['resources'].single;
    expect(resource['commands'].length, 2);
    expect(resource['commands'].first['compacted_receipt'], true);
    expect(resource['current_intent_id'], second.intentId);
    expect(resource['view']['session']['id'], target.id);
    expect(jsonEncode(resource), isNot(contains('checksum')));
    expect(disk.data, before);
  });

  testWidgets(
    'combined export works offline and preserves data when save is cancelled or fails',
    (tester) async {
      final h = AppHarness()
        ..signInAs(role: 'student', userId: 'student', token: 'private-token');
      await ProfileJournalStore(
        h.store,
        'student',
      ).edit(ProfileEdit({'display_name': '本机修改'}));
      h.backend.offline = true;
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection.recovery(
              save: (bytes) async {
                final value = jsonDecode(utf8.decode(bytes)) as Map;
                expect(value['scope'], 'local_student_recovery_records');
                expect(value['owner_id'], 'student');
                expect(value['profile']['edit']['display_name'], '本机修改');
                expect(value['exported_at'], isNotNull);
                expect(utf8.decode(bytes), isNot(contains('private-token')));
                if (++saves == 1) return '已取消保存';
                throw StateError('private-save-error');
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final before = Map.of(h.store.data);
      await tester.tap(find.byKey(const ValueKey('profile.exportRecovery')));
      await tester.pumpAndSettle();
      expect(find.text('已取消保存'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('profile.exportRecovery')));
      await tester.pumpAndSettle();
      expect(saves, 2);
      expect(find.textContaining('导出失败，原恢复记录未改动'), findsOneWidget);
      expect(find.textContaining('private-'), findsNothing);
      expect(h.store.data, before);
    },
  );

  for (final switchBack in [false, true]) {
    testWidgets(
      'recovery export discards old auth session (switch back $switchBack)',
      (tester) async {
        final disk = HeldReadStore()..readKey = 'u/student/profile_bundle';
        final h = AppHarness(store: disk)
          ..signInAs(role: 'student', userId: 'student');
        disk.data.addAll({
          'auth.other.userId': 'parent',
          'auth.other.role': 'parent',
          'auth.other.token': 'parent-token',
        });
        await ProfileJournalStore(
          disk,
          'student',
        ).edit(ProfileEdit({'display_name': '本机修改'}));
        var saves = 0;
        await tester.pumpWidget(
          h.page(
            Scaffold(
              body: StudentDataExportSection.recovery(
                save: (_) async {
                  saves++;
                  return 'saved';
                },
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        disk.hold = true;
        await tester.tap(find.byKey(const ValueKey('profile.exportRecovery')));
        await tester.pump();
        expect(disk.started.isCompleted, true);
        final container = ProviderScope.containerOf(
          tester.element(find.byType(StudentDataExportSection)),
        );
        await container.read(authProvider.notifier).switchTo(LocalRole.parent);
        if (switchBack) {
          await container
              .read(authProvider.notifier)
              .switchTo(LocalRole.student);
        }
        disk.release.complete();
        await tester.pumpAndSettle();
        expect(saves, 0);
      },
    );
  }

  testWidgets('empty recovery export does not save or create records', (
    tester,
  ) async {
    final h = AppHarness()..signInAs(role: 'student');
    var saves = 0;
    await tester.pumpWidget(
      h.page(
        Scaffold(
          body: StudentDataExportSection.recovery(
            save: (_) async {
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
    expect(saves, 0);
    expect(find.textContaining('没有现存恢复记录'), findsOneWidget);
    expect(h.store.data, before);
  });

  testWidgets('parents never receive the student recovery export', (
    tester,
  ) async {
    final h = AppHarness()..signInAs(role: 'parent');
    await tester.pumpWidget(
      h.page(const Scaffold(body: StudentDataExportSection.recovery())),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('profile.exportRecovery')), findsNothing);
  });

  testWidgets('corrupt recovery data never reaches save or raw error text', (
    tester,
  ) async {
    final h = AppHarness()..signInAs(role: 'student', userId: 'student');
    h.store.data['u/student/profile_bundle'] = '{private-corruption';
    var saves = 0;
    await tester.pumpWidget(
      h.page(
        Scaffold(
          body: StudentDataExportSection.recovery(
            save: (_) async {
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
    expect(saves, 0);
    expect(find.textContaining('导出失败'), findsOneWidget);
    expect(find.textContaining('private-corruption'), findsNothing);
    expect(h.store.data, before);
  });

  testWidgets('profile load failure retains the combined recovery export', (
    tester,
  ) async {
    final h = AppHarness()..signInAs(role: 'student');
    h.backend.failNextOn(r'/profile$', 503, 'service_unavailable');
    await tester.pumpWidget(h.page(const ProfilePage()));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('profile.exportRecovery')),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    expect(
      find.byKey(const ValueKey('profile.exportRecovery')),
      findsOneWidget,
    );
  });

  for (final kind in [
    'profile',
    'authorization',
    'resource',
    'profile_owner',
    'authorization_owner',
    'resource_owner',
  ]) {
    test('damaged $kind fails whole export while preserving bytes', () async {
      final disk = MemoryStore();
      await seed(disk);
      final key = kind.startsWith('profile')
          ? 'u/alice/profile_bundle'
          : kind.startsWith('authorization')
          ? 'u/alice/parent_authorization_bundle/student'
          : disk.data.keys.singleWhere(
              (key) => key.startsWith('u/alice/resource-journal/'),
            );
      if (kind.endsWith('_owner')) {
        final value = jsonDecode(disk.data[key]!) as Map;
        value['owner'] = 'bob';
        if (kind == 'resource_owner') {
          value.remove('checksum');
          value['checksum'] = journalHash(value);
        }
        disk.data[key] = jsonEncode(value);
      } else {
        disk.data[key] = '{}';
      }
      final before = Map.of(disk.data);
      await expectLater(
        exportLocalRecoveryRecords(disk, 'alice'),
        throwsFormatException,
      );
      expect(disk.data, before);
    });
  }

  test(
    'combined record limit fails whole export and does not trim journals',
    () async {
      final disk = MemoryStore();
      await seed(disk);
      final before = Map.of(disk.data);
      await expectLater(
        exportLocalRecoveryRecords(disk, 'alice', limit: 3),
        throwsStateError,
      );
      expect(disk.data, before);
    },
  );
}
