import 'dart:math';

final Random _random = Random.secure();
int _counter = 0;

/// 服务端只接受 8~128 位的字母、数字和 `. _ : -`（`Idempotency-Key`）。
final RegExp _unsafeKeyChar = RegExp(r'[^A-Za-z0-9._:-]');

/// 生成一个幂等键。每次用户动作固定一个键，网络失败后重试时复用同一个，
/// 这样服务端不会把重试当成新的动作。键由字母、数字和 `-` 组成，长度远大于下限 8。
///
/// [prefix] 只是给人看的标签：不合格的字符换成 `_`，最多取 24 位，所以不管传什么都不会生成服务端不接受的键。
/// **不要把用户输入或任何机密（比如邀请码）放进去**——键会出现在请求头和服务端日志里。
String newIdempotencyKey(String prefix) {
  final label = prefix.replaceAll(_unsafeKeyChar, '_');
  final stamp = DateTime.now().microsecondsSinceEpoch.toRadixString(36);
  final salt = _random.nextInt(1 << 31).toRadixString(36);
  _counter += 1;
  return '${label.length > 24 ? label.substring(0, 24) : label}-$stamp-$salt-${_counter.toRadixString(36)}';
}

/// 按名字保存"尚未成功的动作"的幂等键：同一个动作没成功之前重试复用同一个键，成功后丢弃。
class PendingKeys {
  final Map<String, String> _keys = {};

  /// [action] 区分"哪一个动作"，只在内存里用；动作名里带用户输入（比如邀请码）时，
  /// 用 [label] 给键起一个不含它的标签。
  String keyFor(String action, {String? label}) =>
      _keys.putIfAbsent(action, () => newIdempotencyKey(label ?? action));

  void done(String action) => _keys.remove(action);

  bool has(String action) => _keys.containsKey(action);
}
