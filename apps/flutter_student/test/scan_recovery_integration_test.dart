import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:image_picker/image_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/scan/scan_page.dart';
import 'package:tutor_student/features/scan/scan_draft.dart';
import 'package:tutor_student/features/scan/scan_command_store.dart';

import 'support/fake_backend.dart';

class _LostConfirm implements ApiTransport {
  final backend = FakeBackend()
    ..installAppBasics()
    ..installScanFlow();
  final writes = <Seen>[];
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    if (uri.path.endsWith('/confirm')) {
      writes.add((method: method, uri: uri, headers: headers, body: body));
      throw ApiException.network('response lost');
    }
    return backend.send(method: method, uri: uri, headers: headers, body: body);
  }
}

class _PickerAuth extends AuthController {
  @override
  Future<AuthSession> build() async =>
      const AuthSession(userId: 'A', token: 'token-A');
  void switchB() =>
      state = const AsyncData(AuthSession(userId: 'B', token: 'token-B'));
}

class _HeldPicker extends ImagePicker {
  final started = Completer<void>();
  final result = Completer<XFile?>();
  @override
  Future<XFile?> pickImage({
    required ImageSource source,
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    CameraDevice preferredCameraDevice = CameraDevice.rear,
    bool requestFullMetadata = true,
  }) async {
    started.complete();
    return result.future;
  }

  @override
  Future<LostDataResponse> retrieveLostData() async => LostDataResponse.empty();
}

class _HeldConfirm extends _LostConfirm {
  final started = Completer<void>();
  final result = Completer<RawResponse>();
  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    if (uri.path.endsWith('/confirm')) {
      writes.add((method: method, uri: uri, headers: headers, body: body));
      started.complete();
      return result.future;
    }
    return super.send(method: method, uri: uri, headers: headers, body: body);
  }
}

void main() {
  testWidgets(
    'acked content survives page reconstruction and continues createScan without original image',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final disk = MemoryStore({
        'auth.token': 'token-A',
        'auth.userId': 'A',
        'auth.role': 'student',
      });
      final journal = ScanWorkspaceStore(disk, 'A');
      final digest = sha256.convert([1, 2, 3, 4]).toString();
      final expiry = DateTime.utc(2026, 12);
      await journal.createWorkspace('local-resume');
      await journal.prepare(
        'local-resume',
        'upload',
        MediaUploadRequest(
          purpose: 'scan',
          mime: 'image/png',
          sizeBytes: 4,
          sha256: digest,
        ),
        key: 'resume-upload',
        activeEpoch: 1,
      );
      await journal.recordResult(
        'resume-upload',
        MediaUpload(
          mediaId: 'scan-media',
          uploadUrl: '/api/v1/scans/uploads/scan-media/content',
          uploadMethod: 'PUT',
          expiresAt: expiry,
          maxBytes: 5242880,
        ),
      );
      await journal.acknowledgeStoredResult('resume-upload');
      await journal.prepare(
        'local-resume',
        'content',
        const MediaBlobUpload(contentBase64: 'AQIDBA=='),
        key: 'resume-content',
        activeEpoch: 1,
      );
      await journal.recordResult(
        'resume-content',
        MediaAssetInfo(
          mediaId: 'scan-media',
          mime: 'image/png',
          sizeBytes: 4,
          sha256: digest,
          expiresAt: expiry,
        ),
      );
      await journal.acknowledgeStoredResult('resume-content');
      final transport = _LostConfirm();
      Widget app() => ProviderScope(
        overrides: [
          keyValueStoreProvider.overrideWithValue(disk),
          apiTransportProvider.overrideWithValue(transport),
        ],
        child: const MaterialApp(home: ScanPage()),
      );
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      final upload = find.byKey(const ValueKey('scan.upload'));
      expect(tester.widget<FilledButton>(upload).onPressed, isNotNull);
      expect(find.byType(Image).evaluate().length, 0);
      await tester.tap(upload);
      await tester.pumpAndSettle();
      final writes = transport.backend.requests
          .where((r) => r.method != 'GET')
          .toList();
      expect(writes.length, 1);
      expect(writes.single.method, 'POST');
      expect(writes.single.uri.path, '/api/v1/scans');
      expect(find.byKey(const ValueKey('scan.start')).evaluate().length, 0);
      expect(
        (await journal.read())!.workspace('local-resume').scanId,
        'scan-test',
      );
      expect(disk.data.values.join(), isNot(contains('AQIDBA==')));
    },
  );

  testWidgets(
    'confirm A receipt keeps unpersisted edit B and its failed-save notice',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final disk = MemoryStore({
        'auth.token': 'token-A',
        'auth.userId': 'A',
        'auth.role': 'student',
      });
      await ScanDraftStore(disk, 'A').save(
        ScanDraft()
          ..stem = 'A'
          ..scanId = 'scan-test',
      );
      final wire = _HeldConfirm();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            keyValueStoreProvider.overrideWithValue(disk),
            apiTransportProvider.overrideWithValue(wire),
          ],
          child: const MaterialApp(home: ScanPage()),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('scan.observe')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('scan.confirm')));
      await tester.pump();
      await wire.started.future;
      disk.failWrites = true;
      await tester.enterText(find.byKey(const ValueKey('scan.stem')), 'B');
      await tester.pumpAndSettle();
      disk.failWrites = false;
      wire.result.complete(
        okResponse({
          'scan': {
            'id': 'scan-test',
            'status': 'confirmed',
            'low_confidence': true,
            'expressions': [],
          },
          'question_id': 'question-A',
          'draft_question_id': null,
        }),
      );
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextField>(find.byKey(const ValueKey('scan.stem')))
            .controller!
            .text,
        'B',
      );
      expect(find.byKey(const ValueKey('scan.start')).evaluate().length, 0);
      expect(find.textContaining('本机保存失败').evaluate().length, 1);
    },
  );

  testWidgets(
    'late picker result after account switch is never attached to the new owner',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final auth = _PickerAuth();
      final picker = _HeldPicker();
      final transport = _LostConfirm();
      final disk = MemoryStore();
      final container = ProviderContainer(
        overrides: [
          authProvider.overrideWith(() => auth),
          keyValueStoreProvider.overrideWithValue(disk),
          apiTransportProvider.overrideWithValue(transport),
          scanImagePickerProvider.overrideWithValue(picker),
        ],
      );
      addTearDown(container.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: ScanPage()),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('scan.pick')));
      await tester.pump();
      await picker.started.future;
      auth.switchB();
      for (var i = 0; i < 10; i++) {
        await tester.pump();
      }
      expect(
        find.byType(LinearProgressIndicator).evaluate().length,
        0,
        reason: tester.allWidgets
            .whereType<Text>()
            .map((w) => w.data ?? '')
            .join('|'),
      );
      final bytes = base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC',
      );
      picker.result.complete(XFile.fromData(bytes, name: 'sample.png'));
      await tester.pumpAndSettle();
      expect(find.byType(Image).evaluate().length, 0);
      expect(transport.writes, isEmpty);
      expect(disk.data.values.join(), isNot(contains(base64Encode(bytes))));
    },
  );

  testWidgets('unknown confirm A is retried unchanged after newer edit B', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final disk = MemoryStore({
      'auth.token': 'scan-token',
      'auth.userId': 'scan-owner',
      'auth.role': 'student',
    });
    await ScanDraftStore(disk, 'scan-owner').save(
      ScanDraft()
        ..stem = 'A'
        ..scanId = 'scan-test',
    );
    final transport = _LostConfirm();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          keyValueStoreProvider.overrideWithValue(disk),
          apiTransportProvider.overrideWithValue(transport),
        ],
        child: const MaterialApp(home: ScanPage()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('scan.observe')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('确认题干并匹配已有题目'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'B');
    await tester.pumpAndSettle();
    final retry = find.byKey(const ValueKey('scan.retry'));
    await tester.tap(
      retry.evaluate().isEmpty ? find.text('确认题干并匹配已有题目') : retry,
    );
    await tester.pumpAndSettle();
    expect(transport.writes.length, 2);
    expect(transport.writes.last.body, transport.writes.first.body);
    expect(
      transport.writes.last.headers['Idempotency-Key'],
      transport.writes.first.headers['Idempotency-Key'],
    );
    expect(
      tester.widget<TextField>(find.byType(TextField).first).controller!.text,
      'B',
    );
  });
}
