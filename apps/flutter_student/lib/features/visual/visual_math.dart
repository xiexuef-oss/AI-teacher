import 'dart:math' as math;

/// 图解模板背后的计算。和绘制分开，便于单独测试；数字都由参数现算，不请求任何模型。

/// 去掉多余的 0：5.0 → "5"，4.4 → "4.4"，0.125 → "0.13"。不是有限数时显示 "—"。
String fmt(double value, {int digits = 2}) {
  if (!value.isFinite) return '—';
  var text = value.toStringAsFixed(digits);
  if (text.contains('.')) {
    text = text
        .replaceFirst(RegExp(r'0+$'), '')
        .replaceFirst(RegExp(r'\.$'), '');
  }
  return text == '-0' ? '0' : text;
}

// ---------------------------------------------------------------- 二次函数

class QuadraticGeometry {
  const QuadraticGeometry(this.a, this.b, this.c);

  final double a;
  final double b;
  final double c;

  bool get isQuadratic => a != 0;
  bool get opensUp => a > 0;

  /// 对称轴 x = -b/(2a)。a = 0 时没有。
  double? get axisX => isQuadratic ? -b / (2 * a) : null;
  double? get vertexY => isQuadratic ? y(axisX!) : null;

  double y(double x) => a * x * x + b * x + c;

  /// 区间标签（递增 / 递减）放在绘图区上沿还是下沿。开口向下时顶点在最高处，
  /// 顶点标签贴着上沿，区间标签就让到下沿，免得两者叠在一起。
  bool get bandLabelsOnTop => opensUp || !isQuadratic;

  String get increasingText {
    final h = axisX;
    if (h == null) return b > 0 ? '在 R 上递增' : (b < 0 ? '在 R 上递减' : '常数函数');
    return opensUp ? '递增区间 [${fmt(h)}, +∞)' : '递增区间 (-∞, ${fmt(h)}]';
  }
}

QuadraticGeometry quadraticOf(Map<String, double> p) =>
    QuadraticGeometry(p['a'] ?? 1, p['b'] ?? 0, p['c'] ?? 0);

// ---------------------------------------------------------------- 和为定值的矩形

class RectangleValues {
  const RectangleValues(this.sum, this.x, this.y);

  final double sum;
  final double x;
  final double y;

  double get area => x * y;
  double get maxArea => (sum / 2) * (sum / 2);
  bool get isSquare => (x - y).abs() <= sum * 0.02;
}

RectangleValues rectangleOf(Map<String, double> p) {
  final sum = p['sum'] ?? 10;
  final x = sum * (p['split'] ?? 0.5);
  return RectangleValues(sum, x, sum - x);
}

// ---------------------------------------------------------------- 斜面受力

class ForceValues {
  const ForceValues({
    required this.angleRad,
    required this.mass,
    required this.mu,
    required this.g,
  });

  final double angleRad;
  final double mass;
  final double mu;
  final double g;

  double get weight => mass * g;
  double get alongSlope => weight * math.sin(angleRad);
  double get normal => weight * math.cos(angleRad);
  double get maxStaticFriction => mu * normal;

  /// 重力沿斜面的分力超过最大静摩擦力（按与滑动摩擦力相等估计）就会下滑。
  bool get sliding => alongSlope > maxStaticFriction + 1e-9;
  double get friction => sliding ? mu * normal : alongSlope;
  double get acceleration =>
      sliding ? g * (math.sin(angleRad) - mu * math.cos(angleRad)) : 0;
}

ForceValues forcesOf(Map<String, double> p) => ForceValues(
  angleRad: (p['angle_deg'] ?? 30) * math.pi / 180,
  mass: p['mass'] ?? 2,
  mu: p['mu'] ?? 0,
  g: p['g'] ?? 9.8,
);

// ---------------------------------------------------------------- 匀变速直线运动

class MotionValues {
  const MotionValues(this.v0, this.a, this.tMax);

  final double v0;
  final double a;
  final double tMax;

  double v(double t) => v0 + a * t;
  double get endVelocity => v(tMax);

  /// 图线与时间轴围成的代数面积，即位移。
  double get displacement => v0 * tMax + 0.5 * a * tMax * tMax;

  /// 速度减为 0 的时刻；加速度为 0 或不在 [0, tMax] 内时没有。
  double? get stopTime {
    if (a == 0) return null;
    final t = -v0 / a;
    return t > 0 && t < tMax ? t : null;
  }
}

MotionValues motionOf(Map<String, double> p) =>
    MotionValues(p['v0'] ?? 0, p['a'] ?? 2, p['t_max'] ?? 5);

// ---------------------------------------------------------------- 化学计量换算

class FlowValues {
  const FlowValues({
    required this.massA,
    required this.molarMassA,
    required this.coefA,
    required this.coefB,
    required this.molarMassB,
  });

  final double massA;
  final double molarMassA;
  final double coefA;
  final double coefB;
  final double molarMassB;

  double get molesA => massA / molarMassA;
  double get molesB => molesA * coefB / coefA;
  double get massB => molesB * molarMassB;
}

FlowValues flowOf(Map<String, double> p) => FlowValues(
  massA: p['mass_a'] ?? 10,
  molarMassA: p['molar_mass_a'] ?? 100,
  coefA: p['coef_a'] ?? 1,
  coefB: p['coef_b'] ?? 1,
  molarMassB: p['molar_mass_b'] ?? 44,
);

// ---------------------------------------------------------------- 数轴区间

/// 用区间记号描述数轴上标出的那一段。无限的一端总是圆括号。
String intervalText(Map<String, double> p) {
  final leftUnbounded = (p['left_unbounded'] ?? 0) >= 0.5;
  final rightUnbounded = (p['right_unbounded'] ?? 0) >= 0.5;
  final left = p['left'] ?? 0;
  final right = p['right'] ?? 0;
  if (!leftUnbounded && !rightUnbounded && left > right) return '空集';
  final leftClosed = (p['left_closed'] ?? 0) >= 0.5 && !leftUnbounded;
  final rightClosed = (p['right_closed'] ?? 0) >= 0.5 && !rightUnbounded;
  final l = leftUnbounded ? '-∞' : fmt(left, digits: 1);
  final r = rightUnbounded ? '+∞' : fmt(right, digits: 1);
  return '${leftClosed ? '[' : '('}$l, $r${rightClosed ? ']' : ')'}';
}
