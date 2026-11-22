import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/features/profile/learning_pack_section.dart';
import 'package:tutor_student/features/profile/paper_live_scanner.dart';
import 'package:tutor_student/features/scan/scan_page.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

class _PhotoPicker extends ImagePicker {
  _PhotoPicker(this.bytes);
  final Uint8List bytes;
  int selectionSize = 1;
  bool includeCorruptPhoto = false;
  (double?, double?, int?)? cameraOptions;

  @override
  Future<XFile?> pickImage({
    required ImageSource source,
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    CameraDevice preferredCameraDevice = CameraDevice.rear,
    bool requestFullMetadata = true,
  }) async {
    if (source == ImageSource.camera) {
      cameraOptions = (maxWidth, maxHeight, imageQuality);
    }
    return XFile.fromData(bytes, name: 'paper.png', mimeType: 'image/png');
  }

  @override
  Future<List<XFile>> pickMultiImage({
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    int? limit,
    bool requestFullMetadata = true,
  }) async => [
    if (includeCorruptPhoto)
      XFile.fromData(Uint8List(16), name: 'corrupt.png', mimeType: 'image/png'),
    for (var i = 0; i < selectionSize; i++)
      XFile.fromData(bytes, name: 'paper-$i.png', mimeType: 'image/png'),
  ];
}

void main() {
  testWidgets('paper field label stays above the input at large text size', (
    tester,
  ) async {
    final harness = AppHarness();
    const owner = 'student-paper-layout';
    harness.signInAs(role: 'student', userId: owner);
    useSize(tester, const Size(320, 600));
    await tester.pumpWidget(
      ProviderScope(
        overrides: harness.overrides,
        child: const MaterialApp(
          home: MediaQuery(
            data: MediaQueryData(textScaler: TextScaler.linear(2)),
            child: Scaffold(
              body: SingleChildScrollView(
                child: LearningPackSection(ownerId: owner),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    expect(
      tester.getBottomLeft(find.text('同类学校作业占用分钟')).dy,
      lessThan(tester.getTopLeft(find.byType(TextField)).dy),
    );
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'discard a scan that completes after the paper owner changes',
    (tester) async {
      final harness = AppHarness();
      const owner = 'student-paper-first';
      const nextOwner = 'student-paper-next';
      const job = '03fb9db8-aed3-44d2-a605-56a9debe29c9';
      const pagePath = '/learning/packs/page';
      final scan = Completer<String?>();
      harness.signInAs(role: 'student', userId: owner);
      harness.store.data['learning-pack.latest.$owner'] = jsonEncode({
        'job': job,
      });
      harness.backend.on(
        'GET',
        '/learning/jobs/$job',
        (_) => okResponse({
          'id': job,
          'status': 'succeeded',
          'attempts': 1,
          'pack_result': 'published',
        }),
      );
      Widget section(String student) => ProviderScope(
        key: ValueKey(student),
        overrides: [
          ...harness.overrides,
          userIdProvider.overrideWithValue(student),
          paperLiveScannerProvider.overrideWithValue((_) => scan.future),
        ],
        child: MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: LearningPackSection(ownerId: student),
            ),
          ),
        ),
      );
      useSize(tester, const Size(920, 840));
      await tester.pumpWidget(section(owner));
      await tester.pumpAndSettle();
      await tester.tap(find.text('相机扫码'));
      await tester.pump();
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      await tester.pumpWidget(section(nextOwner));
      scan.complete('490a26ed8f244ada918ff56da8ce890a');
      await tester.pumpAndSettle();
      expect(harness.backend.requestsTo('GET', pagePath), isEmpty);
      expect(find.textContaining('已定位'), findsNothing);
    },
    variant: const TargetPlatformVariant({
      TargetPlatform.android,
      TargetPlatform.iOS,
    }),
  );

  testWidgets('cancels a running paper pack with a stable retry key', (
    tester,
  ) async {
    final harness = AppHarness();
    const owner = 'student-paper-cancel';
    const job = '03fb9db8-aed3-44d2-a605-56a9debe29c9';
    harness.signInAs(role: 'student', userId: owner);
    harness.store.data['learning-pack.latest.$owner'] = jsonEncode({
      'job': job,
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
    Widget section() => ProviderScope(
      overrides: [
        ...harness.overrides,
        userIdProvider.overrideWithValue(owner),
      ],
      child: const MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: LearningPackSection(ownerId: owner),
          ),
        ),
      ),
    );
    await tester.pumpWidget(section());
    await tester.pumpAndSettle();
    await tester.tap(find.text('刷新状态'));
    await tester.pumpAndSettle();
    final cancel = find.text('取消生成');
    final download = find.widgetWithText(OutlinedButton, '下载学生版 PDF');
    expect(tester.widget<OutlinedButton>(download).onPressed, isNull);
    for (final text in ['定位印刷题目', '手动选题']) {
      final action = find.widgetWithText(OutlinedButton, text);
      expect(tester.widget<OutlinedButton>(action).onPressed, isNull);
    }
    for (var attempt = 0; attempt < 2; attempt++) {
      if (attempt == 1) {
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pumpWidget(section());
        await tester.pumpAndSettle();
        await tester.tap(find.text('刷新状态'));
        await tester.pumpAndSettle();
      }
      await tester.tap(cancel);
      await tester.pumpAndSettle();
    }
    expect(keys.first, isNotNull);
    expect(keys, [keys.first, keys.first]);
    expect(find.text('已取消'), findsOneWidget);
    expect(cancel, findsNothing);
    expect(tester.widget<OutlinedButton>(download).onPressed, isNull);
  });

  testWidgets(
    'paper photo validates the QR before upload and submits the page',
    (tester) async {
      final harness = AppHarness();
      const owner = 'student-paper-test';
      const job = '03fb9db8-aed3-44d2-a605-56a9debe29c9';
      const photoId = '75d722ab-7d3b-4c65-986e-902edfe66fce';
      final photo = File('test/fixtures/paper-page-qr.png').readAsBytesSync();
      final hash = sha256.convert(photo).toString();
      final item = {'revision': 1, 'code': '001', 'question_version_id': job};
      harness.signInAs(role: 'student', userId: owner);
      harness.store.data['learning-pack.latest.$owner'] = jsonEncode({
        'job': job,
      });
      harness.backend.on(
        'GET',
        '/learning/packs/$job/items/001',
        (_) => okResponse(item),
      );
      var published = false;
      harness.backend.on(
        'GET',
        '/learning/jobs/$job',
        (_) => okResponse({
          'id': job,
          'status': published ? 'succeeded' : 'running',
          'attempts': 1,
          if (published) 'pack_result': 'published',
        }),
      );
      var rejectPage = true;
      var scannedRevision = 1;
      final picker = _PhotoPicker(photo);
      var scannedJob = job;
      List<String>? batchJobs;
      harness.backend.on(
        'GET',
        '/learning/packs/page',
        (_) => okResponse({
          'job_id': batchJobs?.removeAt(0) ?? scannedJob,
          'item': item,
        }),
      );
      var qrVisible = false;
      var batchReads = 0;
      harness.backend.on(
        'GET',
        '/learning/packs/$job/items',
        (_) => okResponse({
          'items': [item],
        }),
      );
      harness.backend.on('GET', '/learning/packs/$job/page', (request) {
        expect(
          request.uri.queryParameters['token'],
          '490a26ed8f244ada918ff56da8ce890a',
        );
        final revision = scannedRevision;
        if (picker.selectionSize > 1) scannedRevision = 1;
        return rejectPage
            ? errorResponse(404, 'not_found')
            : okResponse({...item, 'revision': revision});
      });
      var failedUploadsRemaining = 0;
      harness.backend.on('POST', '/scans/uploads', (request) {
        expect(harness.backend.bodyOf(request)?['sha256'], hash);
        if (failedUploadsRemaining > 0) {
          failedUploadsRemaining--;
          return errorResponse(503, 'service_unavailable');
        }
        return okResponse({
          'media_id': photoId,
          'upload_url': '/scans/uploads/$photoId/content',
          'upload_method': 'PUT',
          'expires_at': '2026-11-18T00:00:00Z',
          'max_bytes': 100000,
        }, status: 201);
      });
      harness.backend.on('PUT', '/scans/uploads/$photoId/content', (request) {
        expect(
          base64Decode(
            harness.backend.bodyOf(request)!['content_base64'] as String,
          ),
          photo,
        );
        return okResponse({
          'media_id': photoId,
          'mime': 'image/png',
          'size_bytes': photo.length,
          'sha256': hash,
          'expires_at': '2026-11-18T00:00:00Z',
        });
      });
      harness.backend.on('POST', '/learning/packs/$job/items/001/returns', (
        request,
      ) {
        expect(harness.backend.bodyOf(request)?['photo_ids'], [photoId]);
        return okResponse(item, status: 201);
      });
      useSize(tester, const Size(360, 1400));
      Widget section(String student) => ProviderScope(
        key: ValueKey(student),
        overrides: [
          ...harness.overrides,
          userIdProvider.overrideWithValue(student),
          paperLiveScannerProvider.overrideWithValue(
            (_) async => '490a26ed8f244ada918ff56da8ce890a',
          ),
          scanImagePickerProvider.overrideWithValue(picker),
          paperQrReaderProvider.overrideWithValue(
            (_) async => qrVisible && (batchJobs == null || ++batchReads != 3)
                ? ['490a26ed8f244ada918ff56da8ce890a']
                : [],
          ),
        ],
        child: MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: LearningPackSection(ownerId: student),
            ),
          ),
        ),
      );
      await tester.pumpWidget(section(owner));
      await tester.pumpAndSettle();
      final refresh = find.text('刷新状态');
      final download = find.widgetWithText(OutlinedButton, '下载学生版 PDF');
      await tester.tap(refresh);
      await tester.pumpAndSettle();
      expect(tester.widget<OutlinedButton>(download).onPressed, isNull);
      published = true;
      await tester.tap(refresh);
      await tester.pumpAndSettle();
      expect(tester.widget<OutlinedButton>(download).onPressed, isNotNull);
      expect(find.text('取消生成'), findsNothing);
      await tester.tap(find.text('从照片读码'));
      await tester.pumpAndSettle();
      expect(find.textContaining('未读到纸包二维码'), findsOneWidget);
      expect(
        harness.backend.requestsTo('GET', '/learning/packs/$job/page'),
        isEmpty,
      );
      await tester.tap(find.text('手动选题'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 350));
      await tester.tap(find.text('001 号题 · 第 1 版'));
      await tester.pumpAndSettle();
      qrVisible = true;
      final add = find.text('选图添加作答页');
      await tester.tap(find.text('拍照添加作答页'));
      await tester.pumpAndSettle();
      expect(picker.cameraOptions, (3000.0, 3000.0, 90));
      expect(find.textContaining('不属于当前纸包'), findsOneWidget);
      expect(harness.backend.requestsTo('POST', '/scans/uploads'), isEmpty);
      rejectPage = false;
      scannedRevision = 2;
      await tester.tap(add);
      await tester.pumpAndSettle();
      expect(find.textContaining('对应另一道题'), findsOneWidget);
      expect(harness.backend.requestsTo('POST', '/scans/uploads'), isEmpty);
      scannedRevision = 1;
      published = false;
      await tester.tap(refresh);
      await tester.pumpAndSettle();
      expect(tester.widget<OutlinedButton>(download).onPressed, isNull);
      await tester.tap(find.text('相机扫码'));
      await tester.pumpAndSettle();
      expect(find.textContaining('已定位第 1 版纸包的 001 号题'), findsOneWidget);
      expect(tester.widget<OutlinedButton>(download).onPressed, isNotNull);
      picker.selectionSize = 2;
      picker.includeCorruptPhoto = true;
      scannedRevision = 2;
      await tester.tap(add);
      await tester.pumpAndSettle();
      expect(find.text('已添加 1 页'), findsOneWidget);
      expect(find.textContaining('照片 2：照片二维码对应另一道题'), findsOneWidget);
      expect(find.textContaining('照片 1：请选择完整的静态'), findsOneWidget);
      expect(
        harness.backend.requestsTo('POST', '/scans/uploads'),
        hasLength(1),
      );
      const ocrPath = '/learning/packs/$job/items/001/photo-ocr';
      const ocrId = '26fb9db8-aed3-44d2-a605-56a9debe29c9';
      final receipt = {
        'id': ocrId,
        'item': item,
        'photo_ids': [photoId],
      };
      final ocrKeys = <String?>[];
      var reads = 0;
      harness.backend.on('POST', ocrPath, (request) {
        ocrKeys.add(request.headers['Idempotency-Key']);
        return ocrKeys.length == 1
            ? errorResponse(503, 'service_unavailable')
            : okResponse({...receipt, 'status': 'queued'}, status: 202);
      });
      harness.backend.on(
        'GET',
        '$ocrPath/$ocrId',
        (_) => okResponse(
          ++reads == 1
              ? {...receipt, 'status': 'unavailable'}
              : {...receipt, 'status': 'needs_review', 'candidate': '候选 A'},
        ),
      );
      final recognize = find.text('识别照片文字 / 查看结果');
      await tester.ensureVisible(recognize);
      await tester.tap(recognize);
      await tester.pumpAndSettle();
      expect(ocrKeys, hasLength(1));
      await tester.ensureVisible(recognize);
      await tester.tap(recognize);
      await tester.pumpAndSettle();
      expect(ocrKeys, hasLength(2));
      expect(ocrKeys.first, isNotNull);
      expect(ocrKeys.last, ocrKeys.first);
      expect(find.text('正在识别，请稍后再点查看。'), findsOneWidget);
      await tester.ensureVisible(recognize);
      await tester.tap(recognize);
      await tester.pumpAndSettle();
      expect(find.textContaining('未获得可用转写'), findsOneWidget);
      await tester.ensureVisible(recognize);
      await tester.tap(recognize);
      await tester.pumpAndSettle();
      expect(ocrKeys, hasLength(3));
      expect(ocrKeys.last, isNot(ocrKeys.first));
      await tester.ensureVisible(recognize);
      await tester.tap(recognize);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 350));
      expect(find.text('候选 A'), findsOneWidget);
      await tester.tap(find.text('填入并校正'));
      await tester.pumpAndSettle();
      expect(find.text('候选 A'), findsOneWidget);
      expect(
        harness.backend.requestsTo(
          'POST',
          '/learning/packs/$job/items/001/returns',
        ),
        isEmpty,
      );
      await tester.enterText(
        find.descendant(
          of: find.byKey(ValueKey('纸笔作答转写')),
          matching: find.byType(TextField),
        ),
        'B',
      );
      final submit = find.text('确认并回收作答');
      await tester.ensureVisible(submit);
      await tester.tap(submit);
      await tester.pumpAndSettle();
      expect(find.text('纸笔作答已回收。'), findsOneWidget);
      scannedJob = '75d722ab-7d3b-4c65-986e-902edfe66fce';
      harness.backend.on(
        'GET',
        '/learning/packs/$scannedJob/items/001/returns',
        (_) => errorResponse(404, 'not_found'),
      );
      final scan = find.text('从照片读码');
      await tester.ensureVisible(scan);
      await tester.tap(scan);
      await tester.pumpAndSettle();
      expect(find.textContaining('已定位第 1 版纸包的 001 号题'), findsOneWidget);
      expect(
        harness.backend.requestsTo(
          'GET',
          '/learning/packs/$scannedJob/items/001/returns',
        ),
        hasLength(1),
      );
      picker.includeCorruptPhoto = false;
      picker.selectionSize = 3;
      batchJobs = [job, scannedJob];
      harness.backend.on(
        'GET',
        '/learning/packs/$scannedJob/page',
        (_) => okResponse(item),
      );
      final batch = find.text('批量归集照片');
      await tester.ensureVisible(batch);
      await tester.tap(batch);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 350));
      expect(find.text('照片 3 无码，请确认归属'), findsOneWidget);
      await tester.tap(find.text('纸包 75d722ab · 第 1 版 · 001 号题'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 350));
      expect(find.text('核对作答页归属'), findsOneWidget);
      expect(
        find.textContaining('纸包 75d722ab · 第 1 版 · 001 号题 · 2 页'),
        findsOneWidget,
      );
      expect(find.textContaining('03fb9db8'), findsWidgets);
      expect(find.textContaining('75d722ab'), findsWidgets);
      expect(
        harness.backend.requestsTo('POST', '/scans/uploads'),
        hasLength(1),
      );
      failedUploadsRemaining = 2;
      await tester.tap(find.text('加入草稿'));
      await tester.pumpAndSettle();
      expect(
        harness.backend.requestsTo('POST', '/scans/uploads'),
        hasLength(3),
      );
      expect(find.textContaining('照片 2 已保存在本机'), findsOneWidget);
      expect(
        await harness.store.keys(
          'learning-pack.latest.$owner.$scannedJob.001.pending.',
        ),
        hasLength(1),
      );
      final retry = find.text('重试上传本机照片');
      Future<void> reopenAs(String student) async {
        harness.signInAs(
          role: 'student',
          userId: student,
          token: 'paper-test-$student',
        );
        await tester.pumpWidget(section(student));
        await tester.pumpAndSettle();
        final scan = find.text('从照片读码');
        await tester.ensureVisible(scan);
        await tester.tap(scan);
        await tester.pumpAndSettle();
        await tester.ensureVisible(retry);
        await tester.tap(retry);
        await tester.pumpAndSettle();
      }

      batchJobs = null;
      picker.selectionSize = 1;
      await reopenAs('student-paper-other');
      expect(find.text('没有待上传照片。'), findsOneWidget);
      expect(
        harness.backend.requestsTo('POST', '/scans/uploads'),
        hasLength(3),
      );
      await reopenAs(owner);
      expect(find.text('已添加 1 页'), findsOneWidget);
      expect(
        harness.backend.requestsTo('POST', '/scans/uploads'),
        hasLength(4),
      );
      expect(
        await harness.store.keys(
          'learning-pack.latest.$owner.$scannedJob.001.pending.',
        ),
        isEmpty,
      );
      final pendingKey =
          'learning-pack.latest.$owner.$scannedJob.001.pending.1.$job.$hash';
      harness.store.data[pendingKey] = jsonEncode({
        'bytes': base64Encode(photo),
        'mime': 'image/png',
      });
      final remove = find.text('移除待上传照片');
      await tester.ensureVisible(remove);
      await tester.tap(remove);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 350));
      expect(find.text('移除哪张待上传照片？'), findsOneWidget);
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();
      expect(harness.store.data, contains(pendingKey));
      await tester.tap(remove);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 350));
      await tester.tap(find.text('移除本机照片 1'));
      await tester.pumpAndSettle();
      expect(harness.store.data, isNot(contains(pendingKey)));
      expect(find.text('已添加 1 页'), findsOneWidget);
      var reserveAttempts = 0;
      harness.backend.on('POST', '/scans/uploads', (_) {
        reserveAttempts++;
        if (reserveAttempts == 1) return errorResponse(422, 'unprocessable');
        return okResponse({
          'media_id': photoId,
          'upload_url': '/scans/uploads/$photoId/content',
          'upload_method': 'PUT',
          'expires_at': '2026-11-18T00:00:00Z',
          'max_bytes': 100000,
        }, status: 201);
      });
      picker.selectionSize = 2;
      await tester.ensureVisible(add);
      await tester.tap(add);
      await tester.pumpAndSettle();
      expect(reserveAttempts, 2);
      expect(find.textContaining('照片 2：这张照片已添加。'), findsOneWidget);
      final savedBatch = 'learning-pack.latest.$owner.unlocated-photos';
      expect(harness.store.data, contains(savedBatch));
      await tester.ensureVisible(batch);
      await tester.tap(batch);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 350));
      await tester.tap(find.text('移除这批照片'));
      await tester.pumpAndSettle();
      expect(harness.store.data, isNot(contains(savedBatch)));
      harness.backend.on('GET', '/learning/packs/page', (_) {
        expect(
          harness.store.data[savedBatch],
          jsonEncode([base64Encode(photo)]),
        );
        return errorResponse(503, 'service_unavailable');
      });
      picker.selectionSize = 1;
      await tester.ensureVisible(batch);
      await tester.tap(batch);
      await tester.pumpAndSettle();
      expect(harness.store.data[savedBatch], jsonEncode([base64Encode(photo)]));
      expect(find.textContaining('联网后可继续批量归集'), findsOneWidget);
      harness.backend.on(
        'GET',
        '/learning/packs/page',
        (_) => okResponse({'job_id': scannedJob, 'item': item}),
      );
      picker.selectionSize = 0;
      await tester.tap(batch);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 350));
      await tester.tap(find.text('继续归集'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 350));
      expect(find.text('核对作答页归属'), findsOneWidget);
      await tester.tap(find.text('加入草稿'));
      await tester.pumpAndSettle();
      expect(harness.store.data, isNot(contains(savedBatch)));
      expect(tester.takeException(), isNull);
      await teardownTree(tester);
    },
  );
}
