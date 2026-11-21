import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/features/profile/school_material_candidate_editor.dart';
import 'package:tutor_student/features/profile/school_material_section.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

void main() {
  for (final size in [phone, tabletPortrait, tabletLandscape]) {
    testWidgets('teacher fields fit at 1.5x on $size', (tester) async {
      useSize(tester, size);
      final harness = AppHarness();
      const owner = 'school-layout-owner';
      harness.signInAs(role: 'student', userId: owner);
      await tester.pumpWidget(
        harness.page(
          ProviderScope(
            overrides: [userIdProvider.overrideWithValue(owner)],
            child: Scaffold(
              body: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: SchoolMaterialCandidateEditor(
                  owner: owner,
                  job: 'layout-job',
                  revision: 'a' * 64,
                  candidates: const [
                    SchoolMaterialCandidate(
                      text: '请核对题面和原件中的作答区域。',
                      locations: [
                        SchoolMaterialCandidateLocation(page: 20, block: 1),
                      ],
                      warnings: [],
                    ),
                  ],
                  onConfirmed: () {},
                  onSelectRegion: (_, _) async => null,
                ),
              ),
            ),
          ),
          textScale: 1.5,
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('教师批注与原件分数'));
      await tester.pumpAndSettle();
      final marks = find.widgetWithText(TextField, '教师批注');
      final score = find.widgetWithText(TextField, '教师评分');
      final maximum = find.widgetWithText(TextField, '原件满分');
      for (final field in [marks, score, maximum]) {
        await tester.ensureVisible(field);
        expect(field.hitTestable(), findsOneWidget);
        final bounds = tester.getRect(field);
        expect(bounds.left, greaterThanOrEqualTo(0));
        expect(bounds.right, lessThanOrEqualTo(size.width));
      }
      expect(
        tester.getRect(marks).bottom,
        lessThanOrEqualTo(tester.getRect(score).top),
      );
      expect(
        tester.getRect(score).bottom,
        lessThanOrEqualTo(tester.getRect(maximum).top),
      );
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('failed task lets the same PDF start a fresh upload', (
    tester,
  ) async {
    final harness = AppHarness();
    const owner = 'school-failed-owner';
    const job = '03fb9db8-aed3-44d2-a605-56a9debe29c9';
    final bytes = Uint8List.fromList(utf8.encode('%PDF-fixture'));
    harness.signInAs(role: 'student', userId: owner);
    harness.store.data['u/$owner/school-material-latest'] = jsonEncode({
      'job': job,
      'key': 'old-material-key',
      'mime': 'application/pdf',
      'digest': sha256.convert(bytes).toString(),
    });
    harness.backend.on(
      'GET',
      '/learning/jobs/$job',
      (_) => okResponse({'id': job, 'status': 'failed', 'attempts': 3}),
    );
    String? reserveKey;
    harness.backend.on('POST', '/school-materials/uploads', (request) {
      reserveKey = request.headers['Idempotency-Key'];
      return errorResponse(503, 'service_unavailable');
    });
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          ...harness.overrides,
          userIdProvider.overrideWithValue(owner),
          schoolMaterialPickerProvider.overrideWithValue(
            () async =>
                XFile.fromData(bytes, path: 'sample.pdf', name: 'sample.pdf'),
          ),
        ],
        child: const MaterialApp(
          home: Scaffold(body: SchoolMaterialSection(ownerId: owner)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('schoolMaterial.refresh')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('schoolMaterial.pick')));
    await tester.pumpAndSettle();
    expect(reserveKey, endsWith('-reserve'));
    expect(reserveKey, isNot('old-material-key-reserve'));
  });

  testWidgets('cancelling retries with the same key after a lost response', (
    tester,
  ) async {
    final harness = AppHarness();
    const owner = 'school-cancel-owner';
    const job = '03fb9db8-aed3-44d2-a605-56a9debe29c9';
    harness.signInAs(role: 'student', userId: owner);
    harness.store.data['u/$owner/school-material-latest'] = jsonEncode({
      'job': job,
      'key': 'local-material-key',
    });
    harness.backend.on(
      'GET',
      '/learning/jobs/$job',
      (_) => okResponse({'id': job, 'status': 'running', 'attempts': 1}),
    );
    final keys = <String?>[];
    harness.backend.on('POST', '/learning/jobs/$job/cancel', (request) {
      keys.add(request.headers['Idempotency-Key']);
      return keys.length == 1
          ? errorResponse(503, 'service_unavailable')
          : okResponse({'id': job, 'status': 'cancelled', 'attempts': 1});
    });
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          ...harness.overrides,
          userIdProvider.overrideWithValue(owner),
        ],
        child: const MaterialApp(
          home: Scaffold(body: SchoolMaterialSection(ownerId: owner)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('schoolMaterial.refresh')));
    await tester.pumpAndSettle();
    final cancel = find.text('取消材料处理');
    await tester.tap(cancel);
    await tester.pumpAndSettle();
    await tester.tap(cancel);
    await tester.pumpAndSettle();
    expect(keys, ['local-material-key-cancel', 'local-material-key-cancel']);
    expect(find.text('任务已取消。'), findsOneWidget);
    expect(cancel, findsNothing);
  });

  testWidgets('reselecting a PDF retries the same submission after reopening', (
    tester,
  ) async {
    final harness = AppHarness();
    const owner = 'school-test-owner';
    const media = '75d722ab-7d3b-4c65-986e-902edfe66fce';
    const job = '03fb9db8-aed3-44d2-a605-56a9debe29c9';
    const root = '/school-materials';
    harness.signInAs(role: 'student', userId: owner);
    final bytes = Uint8List.fromList(utf8.encode('%PDF-fixture'));
    Map<String, dynamic>? metadata;
    harness.backend.on('POST', '$root/uploads', (request) {
      metadata = harness.backend.bodyOf(request);
      expect(metadata!['mime'], 'application/pdf');
      return okResponse({
        'media_id': media,
        'max_bytes': 1024,
        'expires_at': '2099-01-01T00:00:00Z',
        'upload_method': 'PUT',
        'upload_url': '$root/uploads/$media/content',
      }, status: 201);
    });
    harness.backend.on('PUT', '$root/uploads/$media/content', (request) {
      expect(
        harness.backend.bodyOf(request)!['content_base64'],
        base64Encode(bytes),
      );
      return okResponse({
        ...metadata!,
        'media_id': media,
        'expires_at': '2099-01-01T00:00:00Z',
        'page_count': 2,
      });
    });
    final keys = <String?>[];
    harness.backend.on('POST', root, (request) {
      keys.add(request.headers['Idempotency-Key']);
      expect(harness.backend.bodyOf(request), {'media_id': media});
      return keys.length == 1
          ? errorResponse(503, 'service_unavailable')
          : okResponse({
              'id': job,
              'status': 'queued',
              'attempts': 0,
            }, status: 202);
    });
    harness.backend.on(
      'GET',
      '/learning/jobs/$job',
      (_) => okResponse({'id': job, 'status': 'succeeded', 'attempts': 1}),
    );
    var revision = 0;
    var transcript = '';
    harness.backend.on(
      'GET',
      '$root/$job/pages',
      (_) => okResponse({
        'pages': [
          {'page_number': 1, 'text': 'page text', 'needs_ocr': false},
          {
            'page_number': 2,
            'text': transcript,
            'needs_ocr': revision == 0,
            if (revision > 0) 'revision': revision,
          },
        ],
      }),
    );

    Future<void> mount() async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            ...harness.overrides,
            userIdProvider.overrideWithValue(owner),
            schoolMaterialPickerProvider.overrideWithValue(
              () async =>
                  XFile.fromData(bytes, path: 'sample.pdf', name: 'sample.pdf'),
            ),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(
                child: SchoolMaterialSection(ownerId: owner),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    final select = find.byKey(const ValueKey('schoolMaterial.pick'));
    await mount();
    harness.store.failWrites = true;
    await tester.tap(select);
    await tester.pumpAndSettle();
    expect(harness.backend.requests, isEmpty);
    harness.store.failWrites = false;
    await tester.tap(select);
    await tester.pumpAndSettle();
    expect(keys, hasLength(1));
    await tester.pumpWidget(const SizedBox());
    await mount();
    await tester.tap(select);
    await tester.pumpAndSettle();
    expect(keys.first, isNotNull);
    expect(keys, [keys.first, keys.first]);
    expect(
      harness.backend.requests.where((r) => r.method == 'PUT'),
      hasLength(1),
    );
    await tester.tap(find.byKey(const ValueKey('schoolMaterial.refresh')));
    await tester.pumpAndSettle();
    expect(find.text('page text'), findsOneWidget);
    expect(find.textContaining('待 OCR'), findsOneWidget);
    harness.backend.on(
      'GET',
      '$root/$job/pages/1/preview',
      (_) =>
          okResponse(harness.backend.fixtures.value('school_material_preview')),
    );
    await tester.tap(find.text('预览原件第 1 页'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    expect(find.text('原件第 1 页'), findsOneWidget);
    final viewer = find.byType(InteractiveViewer);
    final image = tester
        .widget<Image>(
          find.descendant(of: viewer, matching: find.byType(Image)),
        )
        .image;
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    expect(viewer, findsNothing);
    expect(PaintingBinding.instance.imageCache.containsKey(image), isFalse);
    final edit = find.text('校正第 2 页');
    await tester.tap(edit);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    await tester.enterText(find.byType(TextFormField), 'local text');
    await tester.pump();
    expect(
      harness.store.data.values.any((value) => value.contains('local text')),
      isTrue,
    );
    revision = 1;
    transcript = 'cloud text';
    harness.backend.on('PUT', '$root/$job/pages/2/correction', (request) {
      final body = harness.backend.bodyOf(request)!;
      if (body['expected_revision'] != revision) {
        return errorResponse(409, 'school_material_revision_conflict');
      }
      transcript = body['text'] as String;
      revision++;
      return okResponse({'page_number': 2, 'revision': revision});
    });
    await tester.tap(find.text('保存校正'));
    await tester.pumpAndSettle();
    expect(find.text('页面已更新，本机转写已保留。'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await mount();
    await tester.tap(find.byKey(const ValueKey('schoolMaterial.refresh')));
    await tester.pumpAndSettle();
    await tester.tap(edit);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    expect(find.text('local text'), findsOneWidget);
    await tester.tap(find.text('保留本机转写'));
    await tester.pump();
    await tester.tap(find.text('保存校正'));
    await tester.pumpAndSettle();
    expect(revision, 2);
    expect(find.text('local text'), findsOneWidget);
    final sourceRevision = 'a' * 64;
    List<dynamic>? confirmedItems;
    harness.backend.on(
      'GET',
      '$root/$job/candidates',
      (_) => okResponse({
        'source_revision': sourceRevision,
        'confirmed_items': ?confirmedItems,
        'items': [
          {
            'text': transcript,
            'locations': [
              {'page': 2, 'block': 1},
            ],
            'warnings': ['Check boundary'],
          },
        ],
      }),
    );
    harness.backend.on('PUT', '$root/$job/confirmation', (request) {
      final body = harness.backend.bodyOf(request)!;
      expect(body['source_revision'], sourceRevision);
      confirmedItems = body['items'] as List;
      return okResponse({
        'source_revision': sourceRevision,
        'item_count': confirmedItems!.length,
      });
    });
    await tester.tap(find.text('查看分题候选'));
    await tester.pumpAndSettle();
    final location = find.text('第 2 页第 1 行');
    await tester.ensureVisible(location);
    await tester.tap(location);
    await tester.pumpAndSettle();
    expect(find.text('Check boundary'), findsOneWidget);
    final field = find.widgetWithText(TextField, '题目 1');
    await tester.ensureVisible(field);
    final controller = tester.widget<TextField>(field).controller!;
    controller.selection = const TextSelection.collapsed(offset: 5);
    final split = find.text('从光标处拆题').first;
    await tester.ensureVisible(split);
    await tester.tap(split);
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, '题目 2'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await mount();
    await tester.tap(find.byKey(const ValueKey('schoolMaterial.refresh')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('查看分题候选'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, '题目 2'), findsOneWidget);
    final merge = find.text('与下一题合并');
    await tester.ensureVisible(merge);
    await tester.tap(merge);
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, '题目 2'), findsNothing);
    harness.backend.on(
      'GET',
      '$root/$job/pages/2/preview',
      (_) =>
          okResponse(harness.backend.fixtures.value('school_material_preview')),
    );
    final regionButton = find.text('框选原件区域');
    await tester.ensureVisible(regionButton);
    await tester.tap(regionButton);
    await tester.pumpAndSettle();
    await tester.tap(find.text('第 2 页').last);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    await tester.tap(find.byType(DropdownButton<String>));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    await tester.tap(find.text('教师批注').last);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    final canvas = find.byKey(const ValueKey('schoolMaterial.regionCanvas'));
    final rect = tester.getRect(canvas);
    await tester.dragFrom(
      rect.topLeft + Offset(rect.width * .2, rect.height * .2),
      Offset(rect.width * .4, rect.height * .4),
    );
    await tester.pump();
    await tester.tap(find.text('保留区域'));
    await tester.pumpAndSettle();
    expect(find.text('第 2 页 教师批注'), findsOneWidget);
    final teacher = find.text('教师批注与原件分数');
    await tester.ensureVisible(teacher);
    await tester.tap(teacher);
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, '教师批注'), '核对负号');
    await tester.enterText(find.widgetWithText(TextField, '教师评分'), '2.5');
    await tester.enterText(find.widgetWithText(TextField, '原件满分'), '2');
    await tester.pumpAndSettle();
    expect(find.text('教师评分不能超过原件满分'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, '原件满分'), '');
    await tester.pumpAndSettle();
    await tester.pumpWidget(const SizedBox());
    await mount();
    await tester.tap(find.byKey(const ValueKey('schoolMaterial.refresh')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('查看分题候选'));
    await tester.pumpAndSettle();
    expect(find.text('核对负号'), findsOneWidget);
    expect(find.text('第 2 页 教师批注'), findsOneWidget);
    final confirm = find.text('确认分题');
    await tester.ensureVisible(confirm);
    await tester.tap(confirm);
    await tester.pumpAndSettle();
    final saved = confirmedItems!.single as Map<String, dynamic>;
    final region = (saved['regions'] as List).single as Map<String, dynamic>;
    expect(region['page'], 2);
    expect(region['kind'], 'teacher_mark');
    expect(region['left'], closeTo(.2, .02));
    expect(region['top'], closeTo(.2, .02));
    expect(region['right'], closeTo(.6, .02));
    expect(region['bottom'], closeTo(.6, .02));
    expect(confirmedItems, [
      {
        'text': 'local\ntext',
        'pages': [2],
        'teacher_marks': '核对负号',
        'teacher_score': 2.5,
        'regions': [region],
      },
    ]);
    expect(find.text('已确认分题'), findsOneWidget);
    expect(find.text('核对负号'), findsOneWidget);
    expect(find.text('教师评分 2.5'), findsOneWidget);
    final readback = find.text('查看第 2 页框选');
    await tester.ensureVisible(readback);
    await tester.tap(readback);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    expect(find.text('原件第 2 页'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.bySemanticsLabel('教师批注'),
      ),
      findsOneWidget,
    );
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    expect(
      harness.store.data.values.any((value) => value.contains('local text')),
      isFalse,
    );
  });
}
