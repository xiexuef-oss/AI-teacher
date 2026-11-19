import 'dart:convert';

import '../../core/idempotency.dart';
import '../../core/storage.dart';

class ScanDraft {
  String stem = '';
  String expressions = '';
  String? scanId;
  String? mediaId;
  bool hadImage = false;
  bool pickerPending = false;
  final Map<String, String> keys = {};
  String key(String action) =>
      keys.putIfAbsent(action, () => newIdempotencyKey('scan-$action'));
  Map<String, dynamic> toJson() => {
    'version': 1,
    'stem': stem,
    'expressions': expressions,
    'scan_id': scanId,
    'media_id': mediaId,
    'had_image': hadImage,
    'picker_pending': pickerPending,
    'keys': keys,
  };
}

class _Queue {
  Future<void> tail = Future.value();
  Object? owner;
}

class ScanDraftStore {
  ScanDraftStore(this.store, String userId)
    : storageKey = 'scan.${Uri.encodeComponent(userId)}.draft' {
    _queue = (_queues[store] ??= {}).putIfAbsent(storageKey, _Queue.new);
    _queue.owner = _lease;
  }
  static final _queues = Expando<Map<String, _Queue>>();
  final KeyValueStore store;
  final String storageKey;
  final _lease = Object();
  late final _Queue _queue;
  void close() {
    if (identical(_queue.owner, _lease)) _queue.owner = null;
  }

  void _check() {
    if (!identical(_queue.owner, _lease)) throw StateError('旧页面操作已取消');
  }

  Map<String, dynamic> _decode(String raw) {
    final j = jsonDecode(raw) as Map<String, dynamic>;
    if (j['version'] != 1 ||
        j['stem'] is! String ||
        j['expressions'] is! String ||
        j['keys'] is! Map ||
        j['had_image'] is! bool ||
        j['picker_pending'] is! bool ||
        (j['scan_id'] != null && j['scan_id'] is! String) ||
        (j['media_id'] != null && j['media_id'] is! String) ||
        (j['keys'] as Map).entries.any(
          (e) => e.key is! String || e.value is! String,
        )) {
      throw StateError('拍题草稿格式无法读取，保留原始内容，请勿覆盖');
    }
    return j;
  }

  Future<void> save(ScanDraft draft) {
    final snapshot = jsonEncode(draft.toJson());
    final result = _queue.tail.catchError((Object _) {}).then((_) async {
      _check();
      final existing = await store.read(storageKey);
      if (existing != null) _decode(existing);
      _check();
      await store.write(storageKey, snapshot);
    });
    _queue.tail = result;
    return result;
  }

  Future<ScanDraft> load() async {
    await _queue.tail.catchError((Object _) {});
    _check();
    final raw = await store.read(storageKey);
    final d = ScanDraft();
    if (raw == null) return d;
    final j = _decode(raw);
    d.stem = j['stem'] as String;
    d.expressions = j['expressions'] as String;
    d.scanId = j['scan_id'] as String?;
    d.mediaId = j['media_id'] as String?;
    d.hadImage = j['had_image'] as bool;
    d.pickerPending = j['picker_pending'] as bool;
    d.keys.addAll((j['keys'] as Map<String, dynamic>).cast<String, String>());
    return d;
  }
}
