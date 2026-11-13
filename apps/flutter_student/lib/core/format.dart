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

/// 用户 ID 的前 8 位：没有称呼时拿它当名字（不显示完整的 ID）。
String shortId(String id) => id.length < 8 ? id : id.substring(0, 8);

/// "11月9日"（按本地时间）。
String monthDay(DateTime when) {
  final local = when.toLocal();
  return '${local.month}月${local.day}日';
}

/// "2026-11-09" → "11月9日"。日期没有时区，不做任何换算。
String monthDayOfIso(String date) {
  final parts = date.split('-');
  if (parts.length != 3) return date;
  return '${int.tryParse(parts[1]) ?? parts[1]}月${int.tryParse(parts[2]) ?? parts[2]}日';
}

/// "2026-11-09" 加上若干天，仍然是 "YYYY-MM-DD"。用 UTC 算，不受夏令时影响。
String addDaysToIso(String date, int days) {
  final base = DateTime.parse('${date}T00:00:00Z').add(Duration(days: days));
  return base.toIso8601String().substring(0, 10);
}

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
