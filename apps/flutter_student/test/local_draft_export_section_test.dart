import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/profile/student_data_export_section.dart';
import 'package:tutor_student/features/profile/profile_page.dart';
import 'package:tutor_student/features/solve/draft_store.dart';

import 'local_draft_export_test.dart' show sample;
import 'support/app_harness.dart';
import 'support/fake_backend.dart';

class HeldReadStore extends MemoryStore {
  bool hold = false;
  String readKey = 'u/student/draft/q1';
  final started = Completer<void>();
  final release = Completer<void>();

  @override
  Future<String?> read(String key) async {
    if (hold && key == readKey) {
      if (!started.isCompleted) started.complete();
      await release.future;
    }
    return super.read(key);
  }
}

class HeldExportBackend extends FakeBackend {
  String exportPath = '/profile/learning-export';
  final started = Completer<void>();
  final release = Completer<void>();

  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    final result = await super.send(
      method: method,
      uri: uri,
      headers: headers,
      body: body,
    );
    if (uri.path.endsWith(exportPath)) {
      started.complete();
      await release.future;
    }
    return result;
  }
}

void main() {
  for (final switchBack in [false, true]) {
    testWidgets(
      'server response after identity switch is discarded (switch back: $switchBack)',
      (tester) async {
        final backend = HeldExportBackend();
        final h = AppHarness(backend: backend)
          ..signInAs(role: 'student', userId: 'student');
        h.store.data.addAll({
          'auth.other.userId': 'parent',
          'auth.other.role': 'parent',
          'auth.other.token': 'parent-token',
        });
        backend.on('GET', '/profile/learning-export', (_) {
          final data = backend.fixtures.value('student_learning_export');
          (data['profile'] as Map)['user_id'] = 'student';
          return okResponse(data);
        });
        var saves = 0;
        await tester.pumpWidget(
          h.page(
            Scaffold(
              body: StudentDataExportSection(
                server: true,
                save: (_) async {
                  saves++;
                  return 'saved';
                },
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        final button = find.byKey(
          const ValueKey('profile.exportLearningRecords'),
        );
        await tester.tap(button);
        await tester.pump();
        expect(backend.started.isCompleted, isTrue);
        expect(tester.widget<OutlinedButton>(button).onPressed, isNull);
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
    'server learning export uses generated response and rejects another owner',
    (tester) async {
      final h = AppHarness()..signInAs(role: 'student', userId: 'student');
      var responseOwner = 'student';
      h.backend.on('GET', '/profile/learning-export', (_) {
        final data = h.backend.fixtures.value('student_learning_export');
        (data['profile'] as Map)['user_id'] = responseOwner;
        return okResponse(data);
      });
      var saves = 0;
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: StudentDataExportSection(
              server: true,
              save: (bytes) async {
                final data = jsonDecode(utf8.decode(bytes)) as Map;
                expect(data['scope'], 'server_learning_records');
                expect(data['profile']['user_id'], 'student');
                expect(
                  data['parent_access_records']['history_complete'],
                  false,
                );
                expect(data['parent_access_records']['links'], isNotEmpty);
                expect(data['parent_access_records']['invites'], isNotEmpty);
                expect(data['stored_scan_records'], isNotEmpty);
                expect(
                  data['stored_scan_records'][0]['scan']['stem_text'],
                  isNotEmpty,
                );
                saves++;
                return '已取消保存';
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('历史不完整'), findsOneWidget);
      expect(find.textContaining('未提供拍题字段不代表从未拍题'), findsOneWidget);
      final button = find.byKey(
        const ValueKey('profile.exportLearningRecords'),
      );
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(saves, 1);
      responseOwner = 'different-student';
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(saves, 1);
      expect(find.textContaining('导出失败'), findsOneWidget);
    },
  );

  testWidgets('profile failure keeps local export accessible', (tester) async {
    final h = AppHarness()..signInAs(role: 'student', userId: 'student');
    h.backend.failNextOn(r'/profile$', 503, 'service_unavailable');
    await tester.pumpWidget(h.page(const ProfilePage()));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('profile.exportDrafts')), findsOneWidget);
  });

  testWidgets('exports content JSON and supports cancelled/failed save retry', (
    tester,
  ) async {
    final h = AppHarness()
      ..signInAs(role: 'student', userId: 'student', token: 'SECRET');
    await DraftStore(h.store, 'student').writeDraft(sample());
    final before = Map<String, String>.of(h.store.data);
    var calls = 0;
    await tester.pumpWidget(
      h.page(
        Scaffold(
          body: StudentDataExportSection(
            save: (bytes) async {
              final data = jsonDecode(utf8.decode(bytes)) as Map;
              expect(data['scope'], 'local_exercise_drafts');
              expect(data['owner_id'], 'student');
              expect((data['drafts'] as List).single['answer']['selected'], [
                'A',
              ]);
              expect(utf8.decode(bytes), isNot(contains('SECRET')));
              if (++calls == 1) return '已取消保存';
              throw StateError('SECRET-PLATFORM-ERROR');
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final button = find.byKey(const ValueKey('profile.exportDrafts'));
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(find.text('已取消保存'), findsOneWidget);
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(find.textContaining('导出失败，原草稿未改动'), findsOneWidget);
    expect(find.textContaining('SECRET'), findsNothing);
    expect(h.store.data, before);
  });

  testWidgets('parent never sees a draft export entry', (tester) async {
    final h = AppHarness()..signInAs(role: 'parent');
    await tester.pumpWidget(
      h.page(const Scaffold(body: StudentDataExportSection())),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('profile.exportDrafts')), findsNothing);
  });

  for (final switchBack in [false, true]) {
    testWidgets(
      'identity changes before handoff cancel export (switch back: $switchBack)',
      (tester) async {
        final disk = HeldReadStore();
        final h = AppHarness(store: disk)
          ..signInAs(role: 'student', userId: 'student');
        disk.data.addAll({
          'auth.other.userId': 'parent',
          'auth.other.role': 'parent',
          'auth.other.token': 'parent-token',
        });
        await DraftStore(disk, 'student').writeDraft(sample());
        var saves = 0;
        await tester.pumpWidget(
          h.page(
            Scaffold(
              body: StudentDataExportSection(
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
        await tester.tap(find.byKey(const ValueKey('profile.exportDrafts')));
        await tester.pump();
        expect(disk.started.isCompleted, isTrue);
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
        expect(disk.data['u/student/draft/q1'], isNotNull);
      },
    );
  }
}
