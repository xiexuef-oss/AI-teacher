import 'package:shared_preferences/shared_preferences.dart';

/// 本地键值存储。草稿、缓存的题目、登录凭据都放在这里。
///
/// 本切片用 shared_preferences（每个键单独、整体写入）。笔迹很长时它不是最合适的载体——
/// 改用 SQLite 或 Isar 的时机见 docs/ADR-007。
abstract interface class KeyValueStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
  Future<List<String>> keys(String prefix);
}

class SharedPrefsStore implements KeyValueStore {
  SharedPrefsStore(this._prefs);

  final SharedPreferences _prefs;

  static Future<SharedPrefsStore> open() async =>
      SharedPrefsStore(await SharedPreferences.getInstance());

  @override
  Future<String?> read(String key) async => _prefs.getString(key);

  @override
  Future<void> write(String key, String value) async {
    final saved = await _prefs.setString(key, value);
    if (!saved) throw StateError('本地存储写入失败：$key');
  }

  @override
  Future<void> delete(String key) async {
    await _prefs.remove(key);
  }

  @override
  Future<List<String>> keys(String prefix) async =>
      _prefs.getKeys().where((k) => k.startsWith(prefix)).toList()..sort();
}

/// 内存实现，用于测试。
class MemoryStore implements KeyValueStore {
  MemoryStore([Map<String, String>? initial]) : data = {...?initial};

  final Map<String, String> data;

  /// 测试里模拟存储写入失败。
  bool failWrites = false;

  @override
  Future<String?> read(String key) async => data[key];

  @override
  Future<void> write(String key, String value) async {
    if (failWrites) throw StateError('模拟的写入失败');
    data[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    data.remove(key);
  }

  @override
  Future<List<String>> keys(String prefix) async =>
      data.keys.where((k) => k.startsWith(prefix)).toList()..sort();
}
