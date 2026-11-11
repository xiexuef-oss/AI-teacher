import 'dart:math';

final Random _random = Random.secure();
int _counter = 0;

/// 生成一个幂等键。每次用户动作固定一个键，网络失败后重试时复用同一个，
/// 这样服务端不会把重试当成新的动作。键由字母、数字和 `-` 组成，长度远大于下限 8。
String newIdempotencyKey(String prefix) {
  final stamp = DateTime.now().microsecondsSinceEpoch.toRadixString(36);
  final salt = _random.nextInt(1 << 31).toRadixString(36);
  _counter += 1;
  return '$prefix-$stamp-$salt-${_counter.toRadixString(36)}';
}

/// 按名字保存"尚未成功的动作"的幂等键：同一个动作没成功之前重试复用同一个键，成功后丢弃。
class PendingKeys {
  final Map<String, String> _keys = {};

  String keyFor(String action) =>
      _keys.putIfAbsent(action, () => newIdempotencyKey(action));

  void done(String action) => _keys.remove(action);

  bool has(String action) => _keys.containsKey(action);
}
