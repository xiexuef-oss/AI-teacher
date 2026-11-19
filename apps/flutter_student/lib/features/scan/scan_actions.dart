import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/providers.dart';
import '../../core/idempotency.dart';
import 'scan_command_store.dart';

final scanActionsProvider = AsyncNotifierProvider<ScanActions, ScanBundle?>(
  ScanActions.new,
);

class ScanActions extends AsyncNotifier<ScanBundle?> {
  AuthSession? _auth;
  ScanWorkspaceStore? _store;
  int _epoch = 0;
  int _lease = 0;
  ScanWorkspace? get workspace {
    final bundle = state.asData?.value;
    return bundle?.activeWorkspaceId == null
        ? null
        : bundle!.workspace(bundle.activeWorkspaceId!);
  }

  bool valid(AuthSession auth, int epoch, String workspaceId, int lease) {
    if (!ref.mounted) return false;
    final current = ref.read(authProvider).asData?.value;
    return epoch == _epoch &&
        lease == _lease &&
        current?.userId == auth.userId &&
        current?.token == auth.token &&
        current?.role == LocalRole.student &&
        workspace?.id == workspaceId;
  }

  void check(AuthSession auth, int epoch, String id, int lease) {
    if (!valid(auth, epoch, id, lease)) {
      throw StateError('身份或当前图片已变化，旧操作保留在原记录');
    }
  }

  TutorApiClient api(AuthSession auth) => TutorApiClient(
    ApiCore(
      baseUrl: ref.read(apiBaseUrlProvider),
      transport: ref.read(apiTransportProvider),
      tokenProvider: () => auth.token,
    ),
  );
  @override
  Future<ScanBundle?> build() async {
    final epoch = ++_epoch;
    final auth = await ref.watch(authProvider.future);
    if (auth.role != LocalRole.student) {
      throw const WrongSession(LocalRole.student);
    }
    if (!ref.mounted || epoch != _epoch) return null;
    _auth = auth;
    final store = ScanWorkspaceStore(
      ref.read(keyValueStoreProvider),
      auth.userId,
    );
    _store = store;
    var bundle = await store.read();
    if (bundle?.activeWorkspaceId == null) {
      await store.createWorkspace(newIdempotencyKey('scan-workspace'));
      bundle = await store.read();
    }
    return bundle;
  }

  Future<void> publish(
    ScanWorkspaceStore store,
    AuthSession auth,
    int epoch,
  ) async {
    final bundle = await store.read();
    if (!ref.mounted || epoch != _epoch) return;
    final now = ref.read(authProvider).asData?.value;
    if (now?.userId == auth.userId &&
        now?.token == auth.token &&
        now?.role == LocalRole.student) {
      state = AsyncData(bundle);
    }
  }

  Future<void> newWorkspace() async {
    final auth = _auth!;
    final epoch = _epoch;
    final id = workspace!.id;
    final lease = _lease;
    final store = _store!;
    check(auth, epoch, id, lease);
    ++_lease;
    await store.createWorkspace(newIdempotencyKey('scan-workspace'));
    await publish(store, auth, epoch);
  }

  Future<void> edit(String stem, String expressions) async {
    final auth = _auth!;
    final epoch = _epoch;
    final id = workspace!.id;
    final lease = _lease;
    final store = _store!;
    check(auth, epoch, id, lease);
    await store.edit(id, stem: stem, expressions: expressions);
    await publish(store, auth, epoch);
  }

  bool sameImage(Uint8List bytes) {
    final uploads = workspace!.commands.where((c) => c.kind == 'upload');
    if (uploads.isEmpty) return true;
    final body = uploads.first.body!;
    return body['sha256'] == sha256.convert(bytes).toString() &&
        body['size_bytes'] == bytes.length;
  }

  Future<void> upload(String mime, Uint8List? bytes) async {
    final auth = _auth!;
    final epoch = _epoch;
    final id = workspace!.id;
    final lease = _lease;
    final store = _store!;
    check(auth, epoch, id, lease);
    if (workspace!.active != null) throw StateError('请先重试原操作或明确开始新图片');
    if (workspace!.mediaId == null) {
      if (bytes == null) throw StateError('请重新选择原图片');
      final command = await store.prepare(
        id,
        'upload',
        MediaUploadRequest(
          purpose: 'scan',
          mime: mime,
          sizeBytes: bytes.length,
          sha256: sha256.convert(bytes).toString(),
        ),
        key: newIdempotencyKey('scan-upload'),
        activeEpoch: epoch,
      );
      check(auth, epoch, id, lease);
      await send(auth, epoch, id, lease, store, command, bytes: bytes);
      check(auth, epoch, id, lease);
    }
    final contentDone = workspace!.commands.any(
      (c) => c.kind == 'content' && c.phase == 'acked',
    );
    if (!contentDone) {
      if (bytes == null || !sameImage(bytes)) {
        throw StateError('上传内容需要重选同一张原图；不同图片请明确开始新图片');
      }
      final body = MediaBlobUpload(contentBase64: base64Encode(bytes));
      final command = await store.prepare(
        id,
        'content',
        body,
        key: newIdempotencyKey('scan-content'),
        activeEpoch: epoch,
      );
      check(auth, epoch, id, lease);
      await send(auth, epoch, id, lease, store, command, bytes: bytes);
      check(auth, epoch, id, lease);
    }
    if (workspace!.scanId == null) {
      final command = await store.prepare(
        id,
        'create',
        ScanCreate(mediaId: workspace!.mediaId!),
        key: newIdempotencyKey('scan-create'),
        activeEpoch: epoch,
      );
      check(auth, epoch, id, lease);
      await send(auth, epoch, id, lease, store, command);
    }
  }

  Future<void> confirm() async {
    final auth = _auth!;
    final epoch = _epoch;
    final id = workspace!.id;
    final lease = _lease;
    final store = _store!;
    check(auth, epoch, id, lease);
    final current = workspace!;
    final body = ScanConfirm(
      stemText: current.stem,
      expressions: current.expressions.trim().isEmpty
          ? []
          : [ScanExpression(spanId: 'manual', latex: current.expressions)],
    );
    final command = await store.prepare(
      id,
      'confirm',
      body,
      key: newIdempotencyKey('scan-confirm'),
      activeEpoch: epoch,
    );
    check(auth, epoch, id, lease);
    await send(auth, epoch, id, lease, store, command);
  }

  Future<void> retry({Uint8List? bytes}) async {
    final auth = _auth!;
    final epoch = _epoch;
    final id = workspace!.id;
    final lease = _lease;
    final store = _store!;
    check(auth, epoch, id, lease);
    final command = workspace!.active;
    if (command == null) throw StateError('没有待恢复操作');
    await send(auth, epoch, id, lease, store, command, bytes: bytes);
  }

  Future<void> acknowledge() async {
    final auth = _auth!;
    final epoch = _epoch;
    final id = workspace!.id;
    final lease = _lease;
    final store = _store!;
    check(auth, epoch, id, lease);
    final command = workspace!.active;
    if (command == null) throw StateError('没有可确认的历史结果');
    await store.acknowledgeStoredResult(command.key);
    await publish(store, auth, epoch);
  }

  Future<void> observe() async {
    final auth = _auth!;
    final epoch = _epoch;
    final id = workspace!.id;
    final lease = _lease;
    final store = _store!;
    check(auth, epoch, id, lease);
    final scanId = workspace!.scanId ?? workspace!.legacyScanId;
    if (scanId == null) throw StateError('没有可查看的扫描');
    final ticket = await store.beginObservation(id);
    check(auth, epoch, id, lease);
    final result = await api(auth).getScan(scanId: scanId);
    check(auth, epoch, id, lease);
    await store.observe(id, result, generation: ticket);
    await publish(store, auth, epoch);
  }

  Future<void> send(
    AuthSession auth,
    int epoch,
    String id,
    int lease,
    ScanWorkspaceStore store,
    ScanCommand command, {
    Uint8List? bytes,
  }) async {
    check(auth, epoch, id, lease);
    await publish(store, auth, epoch);
    check(auth, epoch, id, lease);
    if (command.phase == 'result_known') {
      await store.acknowledgeStoredResult(command.key);
      await publish(store, auth, epoch);
      return;
    }
    Object result;
    try {
      switch (command.kind) {
        case 'upload':
          result = await api(auth).createScanUpload(
            body: MediaUploadRequest.fromJson(command.body!),
            idempotencyKey: command.key,
          );
        case 'content':
          if (bytes == null) throw StateError('请重选同一原图后重试原内容请求');
          final body = await store.contentBody(
            command.key,
            MediaBlobUpload(contentBase64: base64Encode(bytes)),
          );
          check(auth, epoch, id, lease);
          result = await api(auth).uploadScanContent(
            mediaId: command.path.split('/')[3],
            body: body,
            idempotencyKey: command.key,
          );
        case 'create':
          result = await api(auth).createScan(
            body: ScanCreate.fromJson(command.body!),
            idempotencyKey: command.key,
          );
        case 'confirm':
          result = await api(auth).confirmScan(
            scanId: command.path.split('/')[2],
            body: ScanConfirm.fromJson(command.body!),
            idempotencyKey: command.key,
          );
        default:
          throw StateError('未知扫描操作已保留');
      }
    } on ApiException catch (error) {
      if (error.statusCode == 404) {
        await store.markUnavailable(command.key);
      } else if ([400, 422].contains(error.statusCode) ||
          (error.statusCode == 409 && error.code != 'storage_conflict')) {
        await store.reject(command.key, code: error.code);
      }
      await publish(store, auth, epoch);
      rethrow;
    }
    try {
      await store.recordResult(command.key, result);
      await store.acknowledgeStoredResult(command.key);
    } finally {
      await publish(store, auth, epoch);
    }
  }
}
