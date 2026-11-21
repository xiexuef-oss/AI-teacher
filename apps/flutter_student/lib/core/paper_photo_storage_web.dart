import 'dart:async';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

import 'storage.dart';

KeyValueStore paperPhotoStorage(KeyValueStore fallback) =>
    _IndexedPaperPhotoStorage(fallback);

class _IndexedPaperPhotoStorage implements KeyValueStore {
  _IndexedPaperPhotoStorage(this._fallback);

  final KeyValueStore _fallback;
  static const _name = 'paper-photos';
  Future<web.IDBDatabase>? _database;

  Future<web.IDBDatabase> _open() {
    final ready = Completer<web.IDBDatabase>();
    final request = web.window.indexedDB.open('tutor-paper-drafts', 1);
    request.onupgradeneeded = ((web.Event _) {
      (request.result as web.IDBDatabase).createObjectStore(_name);
    }).toJS;
    request.onsuccess = ((web.Event _) {
      ready.complete(request.result as web.IDBDatabase);
    }).toJS;
    request.onerror = ((web.Event _) {
      ready.completeError(StateError('无法打开本机照片存储'));
    }).toJS;
    return ready.future;
  }

  Future<JSAny?> _run(
    String mode,
    web.IDBRequest Function(web.IDBObjectStore) operation,
  ) async {
    final database = await (_database ??= _open());
    final transaction = database.transaction(_name.toJS, mode);
    final result = Completer<JSAny?>();
    final request = operation(transaction.objectStore(_name));
    transaction.oncomplete = ((web.Event _) {
      result.complete(request.result);
    }).toJS;
    transaction.onabort = ((web.Event _) {
      result.completeError(StateError('本机照片存储操作失败'));
    }).toJS;
    return result.future;
  }

  @override
  Future<String?> read(String key) async {
    final result = await _run('readonly', (store) => store.get(key.toJS));
    if (result == null) return _fallback.read(key);
    return (result as JSString).toDart;
  }

  @override
  Future<void> write(String key, String value) async {
    await _run('readwrite', (store) => store.put(value.toJS, key.toJS));
  }

  @override
  Future<void> delete(String key) async {
    await _fallback.delete(key);
    await _run('readwrite', (store) => store.delete(key.toJS));
  }

  @override
  Future<List<String>> keys(String prefix) async {
    final range = web.IDBKeyRange.bound(prefix.toJS, '$prefix\uffff'.toJS);
    final result = await _run('readonly', (store) => store.getAllKeys(range));
    return {
      ...await _fallback.keys(prefix),
      for (final key in (result as JSArray<JSString>).toDart) key.toDart,
    }.toList()..sort();
  }
}
