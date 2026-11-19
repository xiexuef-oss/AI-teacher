import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/storage.dart';
import 'package:tutor_student/features/scan/scan_command_store.dart';

final expiry = DateTime.utc(2026, 12);
const image = MediaBlobUpload(contentBase64: 'AQIDBA==');
final digest = sha256.convert([1, 2, 3, 4]).toString();
final uploadBody = MediaUploadRequest.fromJson({
  'purpose': 'scan',
  'mime': 'image/png',
  'size_bytes': 4,
  'sha256': digest,
});
MediaUpload upload() => MediaUpload(
  mediaId: 'media-a',
  uploadUrl: '/scans/uploads/media-a/content',
  uploadMethod: 'PUT',
  expiresAt: expiry,
  maxBytes: 100,
);
Scan scan() => Scan(
  id: 'scan-a',
  status: 'ready',
  lowConfidence: true,
  expressions: [],
  mockNotice: 'mock',
);
Future<void> ready(ScanWorkspaceStore s) async {
  await s.createWorkspace('local-a');
  await s.prepare(
    'local-a',
    'upload',
    uploadBody,
    key: 'upload-key',
    activeEpoch: 1,
  );
  await s.recordResult('upload-key', upload());
  await s.acknowledgeStoredResult('upload-key');
  await s.prepare(
    'local-a',
    'content',
    image,
    key: 'content-key',
    activeEpoch: 1,
  );
  await s.recordResult(
    'content-key',
    MediaAssetInfo(
      mediaId: 'media-a',
      mime: 'image/png',
      sizeBytes: 4,
      sha256: digest,
      expiresAt: expiry,
    ),
  );
  await s.acknowledgeStoredResult('content-key');
  await s.prepare(
    'local-a',
    'create',
    const ScanCreate(mediaId: 'media-a'),
    key: 'create-key',
    activeEpoch: 1,
  );
  await s.recordResult('create-key', scan());
  await s.acknowledgeStoredResult('create-key');
}

void main() {
  test(
    'failed edits prepare result ACK preserve original persisted state',
    () async {
      final disk = MemoryStore();
      final s = ScanWorkspaceStore(disk, 'alice');
      await s.createWorkspace('local-a');
      final before = disk.data[s.key];
      disk.failWrites = true;
      await expectLater(
        s.edit('local-a', stem: 'input', expressions: ''),
        throwsStateError,
      );
      await expectLater(
        s.prepare(
          'local-a',
          'upload',
          uploadBody,
          key: 'upload-key',
          activeEpoch: 1,
        ),
        throwsStateError,
      );
      expect(disk.data[s.key], before);
      disk.failWrites = false;
      await s.prepare(
        'local-a',
        'upload',
        uploadBody,
        key: 'upload-key',
        activeEpoch: 1,
      );
      disk.failWrites = true;
      await expectLater(
        s.recordResult('upload-key', upload()),
        throwsStateError,
      );
      expect((await s.read())!.workspace('local-a').mediaId, isNull);
      disk.failWrites = false;
      await s.recordResult('upload-key', upload());
      disk.failWrites = true;
      await expectLater(
        s.acknowledgeStoredResult('upload-key'),
        throwsStateError,
      );
      expect(
        (await s.read())!.workspace('local-a').active!.phase,
        'result_known',
      );
    },
  );

  test('stale confirm body cannot acquire newer edit generation', () async {
    final s = ScanWorkspaceStore(MemoryStore(), 'alice');
    await ready(s);
    await s.edit('local-a', stem: 'B', expressions: '');
    await expectLater(
      s.prepare(
        'local-a',
        'confirm',
        const ScanConfirm(stemText: 'A', expressions: []),
        key: 'confirm-key',
        activeEpoch: 1,
      ),
      throwsStateError,
    );
  });

  test('metadata restart replays generated body without image; content requires same bytes', () async {
    final disk = MemoryStore();
    final s = ScanWorkspaceStore(disk, 'alice');
    await s.createWorkspace('local-a');
    await s.prepare(
      'local-a',
      'upload',
      uploadBody,
      key: 'upload-key',
      activeEpoch: 1,
    );
    final restored = ScanWorkspaceStore(disk, 'alice');
    expect(
      (await restored.read())!.workspace('local-a').active!.body,
      uploadBody.toJson(),
    );
    await restored.recordResult('upload-key', upload());
    await restored.acknowledgeStoredResult('upload-key');
    await restored.prepare(
      'local-a',
      'content',
      image,
      key: 'content-key',
      activeEpoch: 1,
    );
    expect(jsonEncode(disk.data).contains(image.contentBase64), isFalse);
    expect(
      (await restored.contentBody('content-key', image)).toJson(),
      image.toJson(),
    );
    await expectLater(
      restored.contentBody(
        'content-key',
        const MediaBlobUpload(contentBase64: 'BA=='),
      ),
      throwsStateError,
    );
  });
  test(
    'confirm A receipt and local ACK preserve B edit and active new workspace',
    () async {
      final disk = MemoryStore();
      final s = ScanWorkspaceStore(disk, 'alice');
      await ready(s);
      await s.edit('local-a', stem: 'A', expressions: '');
      await s.prepare(
        'local-a',
        'confirm',
        const ScanConfirm(stemText: 'A', expressions: []),
        key: 'confirm-key',
        activeEpoch: 1,
      );
      await s.edit('local-a', stem: 'B', expressions: '');
      await s.createWorkspace('local-b');
      await s.recordResult(
        'confirm-key',
        ScanConfirmation(scan: scan(), questionId: 'question-a'),
      );
      await ScanWorkspaceStore(
        disk,
        'alice',
      ).acknowledgeStoredResult('confirm-key');
      final bundle = (await s.read())!;
      expect(bundle.activeWorkspaceId, 'local-b');
      expect(bundle.workspace('local-a').stem, 'B');
      expect(
        bundle.workspace('local-a').commands.last.result!['question_id'],
        'question-a',
      );
    },
  );
  test('TTL unknown and GET observation never ACK original intent', () async {
    final s = ScanWorkspaceStore(MemoryStore(), 'alice');
    await ready(s);
    await s.edit('local-a', stem: 'A', expressions: '');
    await s.prepare(
      'local-a',
      'confirm',
      const ScanConfirm(stemText: 'A', expressions: []),
      key: 'confirm-key',
      activeEpoch: 1,
    );
    await s.observe(
      'local-a',
      scan(),
      generation: await s.beginObservation('local-a'),
    );
    expect((await s.read())!.workspace('local-a').active!.phase, 'prepared');
    await s.markUnavailable('confirm-key');
    await s.createWorkspace('local-b');
    expect((await s.read())!.workspace('local-a').active!.phase, 'unavailable');
  });
  test('v1 text migrates without old command keys and raw remains byte identical', () async {
    final disk = MemoryStore();
    final oldKey = 'scan.alice.draft';
    const raw =
        '{"version":1,"stem":"old","expressions":"x","scan_id":"old-scan","media_id":"old-media","had_image":true,"picker_pending":false,"keys":{"confirm":"old-key"}}';
    disk.data[oldKey] = raw;
    final s = ScanWorkspaceStore(disk, 'alice');
    final bundle = (await s.read())!;
    expect(bundle.workspaces.single.stem, 'old');
    expect(bundle.workspaces.single.commands, isEmpty);
    expect(bundle.workspaces.single.mediaId, isNull);
    expect(disk.data[oldKey], raw);
  });
  test(
    'unknown v1 fields block migration and do not copy potential image data',
    () async {
      final disk = MemoryStore({
        'scan.alice.draft': '{"version":1,"bytes":"sensitive"}',
      });
      final s = ScanWorkspaceStore(disk, 'alice');
      await expectLater(s.createWorkspace('new'), throwsFormatException);
      expect(disk.data.containsKey(s.key), isFalse);
    },
  );
}

