import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/profile/profile_page.dart';
import 'package:tutor_student/features/profile/student_data_export_section.dart';
import 'package:tutor_student/features/scan/scan_command_store.dart';

import 'local_draft_export_section_test.dart' show HeldReadStore;
import 'scan_command_store_test.dart' show ready;
import 'support/app_harness.dart';

const exportKey = ValueKey('profile.exportScans');

void main() {
  test('scan export keeps all saved workspaces and pending intent without secrets or mutation', () async {
    final disk = MemoryStore({'auth.token': 'private-token'});
    final store = ScanWorkspaceStore(disk, 'alice');
    await ready(store);
    await store.edit('local-a', stem: '旧图片文字', expressions: '');
    await store.prepare(
      'local-a',
      'confirm',
      const ScanConfirm(stemText: '旧图片文字', expressions: []),
      key: 'confirm-key',
      activeEpoch: 1,
    );
    await store.markUnavailable('confirm-key');
    await store.createWorkspace('local-b');
    await store.edit('local-b', stem: '尚未上传的文字', expressions: 'x+1');
    final other = ScanWorkspaceStore(disk, 'bob');
    await other.createWorkspace('other');
    await other.edit('other', stem: 'private-other-student', expressions: '');
    final bundle = jsonDecode(disk.data[store.key]!) as Map;
    bundle['workspaces'][0]['commands'][0]['result']['upload_url'] =
        'https://self-authored.invalid/?signature=private-upload-access';
    bundle['workspaces'][0]['commands'][0]['result']['expires_at'] =
        DateTime.utc(2020).toIso8601String();
    disk.data[store.key] = jsonEncode(bundle);
    final before = Map.of(disk.data);

    final result = await ScanWorkspaceStore(disk, 'alice').exportSnapshot();
    expect(result['scope'], 'local_scan_records');
    expect(result['format_version'], 1);
    expect(result['owner_id'], 'alice');
    expect(result['active_workspace_id'], 'local-b');
    final workspaces = result['workspaces'] as List;
    expect(workspaces.length, 2);
    expect(workspaces[0]['stem_text'], '旧图片文字');
    expect(workspaces[0]['commands'].last['phase'], 'unavailable');
    expect(workspaces[0]['commands'].last['key'], 'confirm-key');
    expect(workspaces[0]['commands'].last['body']['stem_text'], '旧图片文字');
    expect(workspaces[0]['commands'][0]['result']['media_id'], 'media-a');
    expect(workspaces[0]['commands'][1]['body'], isNull);
    expect(workspaces[1]['stem_text'], '尚未上传的文字');
    expect(workspaces[1]['expression_text'], 'x+1');
    final raw = jsonEncode(result);
    for (final secret in [
      'private-token',
      'private-other-student',
      'private-upload-access',
      'upload_url',
      'content_base64',
      'wireFingerprint',
      'activeEpoch',
    ]) {
      expect(raw, isNot(contains(secret)));
    }
    expect(disk.data, before);
    workspaces[0]['stem_text'] = 'changed export copy';
    expect((await store.read())!.workspace('local-a').stem, '旧图片文字');
  });

  test(
    'empty scan export does not create a workspace or scan bundle',
    () async {
      final disk = MemoryStore();
      final result = await ScanWorkspaceStore(disk, 'alice').exportSnapshot();
      expect(result['workspaces'], isEmpty);
      expect(result['active_workspace_id'], isNull);
      expect(disk.data, isEmpty);
    },
  );

  test('legacy scan export preserves text and references without writing migration or old retry keys', () async {
    final disk = MemoryStore({
      'scan.alice.draft':
          '{"version":1,"stem":"旧草稿","expressions":"x",'
          '"scan_id":"old-scan","media_id":"old-media","had_image":true,'
          '"picker_pending":false,"keys":{"confirm":"obsolete-key"}}',
    });
    final before = Map.of(disk.data);
    final value = await ScanWorkspaceStore(disk, 'alice').exportSnapshot();
    final workspace = (value['workspaces'] as List).single;
    expect(workspace['stem_text'], '旧草稿');
    expect(workspace['legacy_scan_id'], 'old-scan');
    expect(workspace['legacy_media_id'], 'old-media');
    expect(workspace['commands'], isEmpty);
    expect(jsonEncode(value), isNot(contains('obsolete-key')));
    expect(disk.data, before);
  });

  for (final damage in ['owner', 'version', 'unknown', 'receipt']) {
    test(
      'invalid scan export fails whole file and preserves original ($damage)',
      () async {
        final disk = MemoryStore();
        final store = ScanWorkspaceStore(disk, 'alice');
        await ready(store);
        final value = jsonDecode(disk.data[store.key]!) as Map;
        switch (damage) {
          case 'owner':
            value['owner'] = 'bob';
          case 'version':
            value['v'] = 99;
          case 'unknown':
            value['private_token'] = 'do-not-export';
          case 'receipt':
            value['workspaces'][0]['commands'][0]['result']['private_token'] =
                'do-not-export';
        }
        disk.data[store.key] = jsonEncode(value);
        final before = Map.of(disk.data);
        await expectLater(store.exportSnapshot(), throwsFormatException);
        expect(disk.data, before);
      },
    );
  }

  testWidgets(
    'local scan export works offline and supports cancelled and failed saves without changes',
    (tester) async {
      final h = AppHarness()
        ..signInAs(role: 'student', userId: 'student', token: 'private-token');
      final store = ScanWorkspaceStore(h.store, 'student');
      await store.createWorkspace('local-a');
      await store.edit('local-a', stem: '未同步的拍题文字', expressions: 'x');
      h.backend.offline = true;
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection.scans(
              save: (bytes) async {
                final value = jsonDecode(utf8.decode(bytes)) as Map;
                expect(value['owner_id'], 'student');
                expect(value['scope'], 'local_scan_records');
                expect(value['workspaces'][0]['stem_text'], '未同步的拍题文字');
                expect(value['exported_at'], isNotNull);
                expect(utf8.decode(bytes), isNot(contains('private-token')));
                if (++saves == 1) return '已取消保存';
                throw StateError('private-platform-error');
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final before = Map.of(h.store.data);
      expect(find.textContaining('不含原图'), findsOneWidget);
      await tester.tap(find.byKey(exportKey));
      await tester.pumpAndSettle();
      expect(find.text('已取消保存'), findsOneWidget);
      await tester.tap(find.byKey(exportKey));
      await tester.pumpAndSettle();
      expect(saves, 2);
      expect(find.textContaining('导出失败，原拍题记录未改动'), findsOneWidget);
      expect(find.textContaining('private-'), findsNothing);
      expect(h.store.data, before);
    },
  );

  for (final switchBack in [false, true]) {
    testWidgets(
      'scan export discards pending read after identity changes (switch back: $switchBack)',
      (tester) async {
        final disk = HeldReadStore()
          ..readKey = 'u/student/scan_workspace_bundle';
        final h = AppHarness(store: disk)
          ..signInAs(role: 'student', userId: 'student');
        disk.data.addAll({
          'auth.other.userId': 'parent',
          'auth.other.role': 'parent',
          'auth.other.token': 'parent-token',
        });
        await ScanWorkspaceStore(disk, 'student').createWorkspace('local-a');
        var saves = 0;
        await tester.pumpWidget(
          h.page(
            Scaffold(
              body: StudentDataExportSection.scans(
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
        await tester.tap(find.byKey(exportKey));
        await tester.pump();
        expect(disk.started.isCompleted, isTrue);
        expect(
          tester.widget<OutlinedButton>(find.byKey(exportKey)).onPressed,
          isNull,
        );
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

  testWidgets(
    'corrupt scan bundle never reaches file save or exposes raw error',
    (tester) async {
      final h = AppHarness()..signInAs(role: 'student', userId: 'student');
      h.store.data['u/student/scan_workspace_bundle'] = '{private-corruption';
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection.scans(
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
      await tester.tap(find.byKey(exportKey));
      await tester.pumpAndSettle();
      expect(saves, 0);
      expect(find.textContaining('导出失败'), findsOneWidget);
      expect(find.textContaining('private-corruption'), findsNothing);
      expect(h.store.data, before);
    },
  );

  testWidgets('parent cannot see local scan export', (tester) async {
    final h = AppHarness()..signInAs(role: 'parent');
    await tester.pumpWidget(
      h.page(const Scaffold(body: StudentDataExportSection.scans())),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(exportKey), findsNothing);
  });

  testWidgets(
    'empty scan export explains no saved local records without handing off a file',
    (tester) async {
      final h = AppHarness()..signInAs(role: 'student', userId: 'student');
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection.scans(
              save: (_) async {
                saves++;
                return 'saved';
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(exportKey));
      await tester.pumpAndSettle();
      expect(saves, 0);
      expect(find.textContaining('没有已保存的拍题记录'), findsOneWidget);
      expect(
        h.store.data.containsKey('u/student/scan_workspace_bundle'),
        isFalse,
      );
    },
  );

  testWidgets('profile load failure still exposes local scan export', (
    tester,
  ) async {
    final h = AppHarness()..signInAs(role: 'student');
    h.backend.failNextOn(r'/profile$', 503, 'service_unavailable');
    await tester.pumpWidget(h.page(const ProfilePage()));
    await tester.pumpAndSettle();
    expect(find.byKey(exportKey), findsOneWidget);
  });
}
