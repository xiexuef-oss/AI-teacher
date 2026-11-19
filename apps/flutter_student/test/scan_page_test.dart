import 'package:flutter/material.dart';

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/features/scan/scan_page.dart';
import 'package:tutor_student/features/scan/scan_draft.dart';
import 'package:tutor_student/features/scan/scan_command_store.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

Future<ScanWorkspace> _active(AppHarness h) async {
  final b = (await ScanWorkspaceStore(h.store, 'scan-user').read())!;
  return b.workspace(b.activeWorkspaceId!);
}

void main() {
  testWidgets('a unique match waits for the student to start practice', (
    tester,
  ) async {
    final h = AppHarness();
    h.signInAs(role: 'student', userId: 'matched-student');
    h.backend.installScanFlow(questionId: 'existing-question');
    await ScanDraftStore(h.store, 'matched-student').save(
      ScanDraft()
        ..stem = 'manually confirmed'
        ..scanId = 'scan-test',
    );
    final legacyKey =
        'scan.${Uri.encodeComponent(h.store.data['auth.userId']!)}.draft';
    final legacyRaw = h.store.data[legacyKey];
    await tester.pumpWidget(h.page(const ScanPage()));
    await tester.pumpAndSettle();
    expect(find.textContaining('选图组件和系统可能保留临时缓存'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const ValueKey('scan.observe')));
    await tester.tap(find.byKey(const ValueKey('scan.observe')));
    await tester.pumpAndSettle();
    final confirm = find.text('确认题干并匹配已有题目');
    await tester.ensureVisible(confirm);
    await tester.tap(confirm);
    await tester.pumpAndSettle();
    expect(h.store.data[legacyKey], legacyRaw);
    expect(find.text('开始练习'), findsOneWidget);
    expect(
      h.backend.requests.where((r) => r.uri.path.endsWith('/sessions')),
      isEmpty,
    );
  });
  testWidgets(
    '501 and retry preserve local input and idempotency without starting a session',
    (tester) async {
      final h = AppHarness();
      h.signInAs(role: 'student', userId: 'scan-user');
      h.backend.installScanFlow();
      final d = ScanDraft()
        ..stem = 'manual stem'
        ..expressions = 'x^2'
        ..scanId = 'scan-test';
      await ScanDraftStore(h.store, 'scan-user').save(d);
      final legacyKey =
          'scan.${Uri.encodeComponent(h.store.data['auth.userId']!)}.draft';
      final legacyRaw = h.store.data[legacyKey];
      await tester.pumpWidget(h.page(const ScanPage()));
      await tester.pumpAndSettle();
      h.backend.failNextOn('/scans/scan-test/confirm', 501, 'not_implemented');
      await tester.ensureVisible(find.byKey(const ValueKey('scan.observe')));
      await tester.tap(find.byKey(const ValueKey('scan.observe')));
      await tester.pumpAndSettle();
      final confirm = find.text('确认题干并匹配已有题目');
      await tester.ensureVisible(confirm);
      await tester.ensureVisible(confirm);
      await tester.tap(confirm);
      await tester.pumpAndSettle();
      await tester.drag(find.byType(Scrollable).first, const Offset(0, 1200));
      await tester.pumpAndSettle();

      expect(find.textContaining('服务未启用'), findsOneWidget);
      final first = h.backend.requests.lastWhere(
        (r) => r.uri.path.endsWith('/confirm'),
      );
      expect(jsonDecode(first.body!)['stem_text'], 'manual stem');
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('scan.retry')),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.byKey(const ValueKey('scan.retry')));
      await tester.pumpAndSettle();
      final second = h.backend.requests.lastWhere(
        (r) => r.uri.path.endsWith('/confirm'),
      );
      expect(
        second.headers['Idempotency-Key'],
        first.headers['Idempotency-Key'],
      );
      expect(h.store.data[legacyKey], legacyRaw);
      expect((await _active(h)).stem, 'manual stem');
      expect(
        h.backend.requests.where((r) => r.uri.path.endsWith('/sessions')),
        isEmpty,
      );
      expect(find.text('开始练习'), findsNothing);
    },
  );
  testWidgets('expired scans keep edited text on this device', (tester) async {
    final h = AppHarness();
    h.signInAs(role: 'student', userId: 'scan-user');
    h.backend.installScanFlow();
    await ScanDraftStore(h.store, 'scan-user').save(
      ScanDraft()
        ..stem = 'retained'
        ..scanId = 'scan-test',
    );
    final legacyKey =
        'scan.${Uri.encodeComponent(h.store.data['auth.userId']!)}.draft';
    final legacyRaw = h.store.data[legacyKey];
    await tester.pumpWidget(h.page(const ScanPage()));
    await tester.pumpAndSettle();
    h.backend.failNextOn('/scans/scan-test/confirm', 404, 'not_found');
    await tester.ensureVisible(find.byKey(const ValueKey('scan.observe')));
    await tester.tap(find.byKey(const ValueKey('scan.observe')));
    await tester.pumpAndSettle();
    final button = find.text('确认题干并匹配已有题目');
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();
    await tester.drag(find.byType(Scrollable).first, const Offset(0, 1200));
    await tester.pumpAndSettle();
    expect(find.textContaining('已到期'), findsOneWidget);
    expect(h.store.data[legacyKey], legacyRaw);
    expect((await _active(h)).stem, 'retained');
  });
}
