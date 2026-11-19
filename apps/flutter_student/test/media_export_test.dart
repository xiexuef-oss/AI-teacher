import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/features/profile/profile_page.dart';
import 'package:tutor_student/features/profile/student_data_export_section.dart';

import 'local_draft_export_section_test.dart' show HeldExportBackend;
import 'support/app_harness.dart';
import 'support/fake_backend.dart';

const buttonKey = ValueKey('profile.exportMedia');

Map<String, dynamic> response(AppHarness h) =>
    h.backend.fixtures.value('student_media_export')..['owner_id'] = 'student';

void main() {
  testWidgets(
    'media export hands off verified ZIP bytes and preserves records on cancel/failure',
    (tester) async {
      final h = AppHarness()..signInAs(role: 'student', userId: 'student');
      final value = response(h);
      h.backend.on('GET', '/profile/media-export', (_) => okResponse(value));
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection.media(
              save: (bytes) async {
                expect(bytes, base64Decode(value['archive_base64'] as String));
                expect(bytes.take(4), [0x50, 0x4b, 0x03, 0x04]);
                if (++saves == 1) return '已取消保存';
                throw StateError('private-platform-error');
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final before = Map.of(h.store.data);
      expect(find.textContaining('附带范围和状态清单'), findsOneWidget);
      await tester.tap(find.byKey(buttonKey));
      await tester.pumpAndSettle();
      expect(find.text('已取消保存'), findsOneWidget);
      await tester.tap(find.byKey(buttonKey));
      await tester.pumpAndSettle();
      expect(saves, 2);
      expect(find.textContaining('导出失败，原媒体未改动'), findsOneWidget);
      expect(find.textContaining('private-platform-error'), findsNothing);
      expect(h.store.data, before);
    },
  );

  for (final damage in [
    'owner',
    'size',
    'digest',
    'base64',
    'scope',
    'counts',
    'history',
    'snapshot',
    'zip',
  ]) {
    testWidgets('media export rejects invalid response before save ($damage)', (
      tester,
    ) async {
      final h = AppHarness()..signInAs(role: 'student', userId: 'student');
      final value = response(h);
      switch (damage) {
        case 'owner':
          value['owner_id'] = 'other';
        case 'size':
          value['size_bytes'] = 1;
        case 'digest':
          value['sha256'] = '0' * 64;
        case 'base64':
          value['archive_base64'] = '%%%';
        case 'scope':
          value['scope'] = 'unknown';
        case 'counts':
          value['files_count'] = value['objects_count'] + 1;
        case 'history':
          value['history_complete'] = true;
        case 'snapshot':
          value['consistent_snapshot'] = true;
        case 'zip':
          value['archive_base64'] = base64Encode([1, 2, 3, 4]);
          value['size_bytes'] = 4;
          value['sha256'] = sha256.convert([1, 2, 3, 4]).toString();
      }
      h.backend.on('GET', '/profile/media-export', (_) => okResponse(value));
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection.media(
              save: (_) async {
                saves++;
                return 'saved';
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(buttonKey));
      await tester.pumpAndSettle();
      expect(saves, 0);
      expect(find.textContaining('导出失败'), findsOneWidget);
    });
  }

  for (final switchBack in [false, true]) {
    testWidgets(
      'media response after identity switch is discarded (switch back: $switchBack)',
      (tester) async {
        final backend = HeldExportBackend()
          ..exportPath = '/profile/media-export';
        final h = AppHarness(backend: backend)
          ..signInAs(role: 'student', userId: 'student');
        h.store.data.addAll({
          'auth.other.userId': 'parent',
          'auth.other.role': 'parent',
          'auth.other.token': 'parent-token',
        });
        backend.on(
          'GET',
          '/profile/media-export',
          (_) => okResponse(response(h)),
        );
        var saves = 0;
        await tester.pumpWidget(
          h.page(
            Scaffold(
              body: StudentDataExportSection.media(
                save: (_) async {
                  saves++;
                  return 'saved';
                },
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(buttonKey));
        await tester.pump();
        expect(backend.started.isCompleted, isTrue);
        expect(
          tester.widget<OutlinedButton>(find.byKey(buttonKey)).onPressed,
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
        backend.release.complete();
        await tester.pumpAndSettle();
        expect(saves, 0);
      },
    );
  }

  testWidgets(
    'empty current media scope explains absence without file handoff',
    (tester) async {
      final h = AppHarness()..signInAs(role: 'student', userId: 'student');
      final value = response(h)
        ..['objects_count'] = 0
        ..['files_count'] = 0;
      h.backend.on('GET', '/profile/media-export', (_) => okResponse(value));
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection.media(
              save: (_) async {
                saves++;
                return 'saved';
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(buttonKey));
      await tester.pumpAndSettle();
      expect(saves, 0);
      expect(find.textContaining('当前没有仍有效的学生用途媒体'), findsOneWidget);
    },
  );

  testWidgets('media export remains available after profile failure', (
    tester,
  ) async {
    final h = AppHarness()..signInAs(role: 'student');
    h.backend.failNextOn(r'/profile$', 503, 'service_unavailable');
    await tester.pumpWidget(h.page(const ProfilePage()));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(buttonKey), 200);
    expect(find.byKey(buttonKey), findsOneWidget);
  });

  testWidgets('parent has no media export entry', (tester) async {
    final h = AppHarness()..signInAs(role: 'parent');
    await tester.pumpWidget(
      h.page(const Scaffold(body: StudentDataExportSection.media())),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(buttonKey), findsNothing);
  });
}
