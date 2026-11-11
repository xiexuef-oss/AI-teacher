// 用不到 intl 的轻量格式化。

String two(int value) => value.toString().padLeft(2, '0');

/// "今天 08:00" / "明天 08:00" / "11月14日 08:00"（按本地时间）。
String formatWhen(DateTime when, DateTime now) {
  final local = when.toLocal();
  final today = DateTime(
    now.toLocal().year,
    now.toLocal().month,
    now.toLocal().day,
  );
  final day = DateTime(local.year, local.month, local.day);
  final diff = day.difference(today).inDays;
  final clock = '${two(local.hour)}:${two(local.minute)}';
  return switch (diff) {
    0 => '今天 $clock',
    1 => '明天 $clock',
    -1 => '昨天 $clock',
    _ => '${local.month}月${local.day}日 $clock',
  };
}

/// 0.6234 → "62%"
String percent(double rate) => '${(rate * 100).round()}%';

String difficultyLabel(int level) => '难度 $level';

/// 两个 JSON 值是否相等。数字按值比较（1 与 1.0 相同），所以在 Web 与 VM 上结论一致。
bool jsonEquals(Object? a, Object? b) {
  if (a is Map && b is Map) {
    if (a.length != b.length) return false;
    for (final key in a.keys) {
      if (!b.containsKey(key) || !jsonEquals(a[key], b[key])) return false;
    }
    return true;
  }
  if (a is List && b is List) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (!jsonEquals(a[i], b[i])) return false;
    }
    return true;
  }
  if (a is num && b is num) return a == b;
  return a == b;
}
