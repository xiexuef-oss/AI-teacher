import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/theme.dart';
import 'visual_math.dart';

/// 图解配色。含义不只靠颜色：递增/递减、静止/下滑旁边都有文字。
class VisualPalette {
  const VisualPalette({
    required this.ink,
    required this.muted,
    required this.grid,
    required this.curve,
    required this.accent,
    required this.good,
    required this.warn,
    required this.surface,
  });

  factory VisualPalette.of(ColorScheme scheme) {
    final status = StatusColors(scheme);
    return VisualPalette(
      ink: scheme.onSurface,
      muted: scheme.onSurfaceVariant,
      grid: scheme.outlineVariant,
      curve: scheme.primary,
      accent: scheme.tertiary,
      good: status.success,
      warn: status.warning,
      surface: scheme.surface,
    );
  }

  final Color ink;
  final Color muted;
  final Color grid;
  final Color curve;
  final Color accent;
  final Color good;
  final Color warn;
  final Color surface;
}

// ---------------------------------------------------------------- 绘制小工具

TextPainter _text(
  String text,
  Color color,
  double size, {
  FontWeight? weight,
  double maxWidth = 240,
  TextAlign align = TextAlign.left,
}) {
  return TextPainter(
    text: TextSpan(
      text: text,
      style: TextStyle(
        color: color,
        fontSize: size,
        fontWeight: weight,
        height: 1.25,
        // 画布上的自绘文字不走主题，要单独带上中文回退字体
        fontFamilyFallback: kCjkFontFallback,
      ),
    ),
    textDirection: TextDirection.ltr,
    textAlign: align,
    maxLines: 3,
    ellipsis: '…',
    // 画布很窄时算出来的可用宽度可能是负数，排版会断言失败
  )..layout(maxWidth: math.max(maxWidth, 1));
}

/// 在 [at] 处写字；[anchor] 指明 [at] 是文字框的哪个位置（Alignment.center 即文字居中于该点）。
void _label(
  Canvas canvas,
  String text,
  Offset at,
  VisualPalette palette, {
  double size = 12,
  Color? color,
  Alignment anchor = Alignment.topLeft,
  FontWeight? weight,
  double maxWidth = 240,
  TextAlign align = TextAlign.left,
}) {
  final painter = _text(
    text,
    color ?? palette.ink,
    size,
    weight: weight,
    maxWidth: maxWidth,
    align: align,
  );
  canvas.drawParagraphLike(painter, at, anchor);
}

extension on Canvas {
  void drawParagraphLike(TextPainter painter, Offset at, Alignment anchor) {
    painter.paint(
      this,
      at -
          Offset(
            painter.width * (anchor.x + 1) / 2,
            painter.height * (anchor.y + 1) / 2,
          ),
    );
  }
}

void _dashed(
  Canvas canvas,
  Offset a,
  Offset b,
  Paint paint, {
  double dash = 6,
  double gap = 4,
}) {
  final total = (b - a).distance;
  if (total == 0) return;
  final dir = (b - a) / total;
  var drawn = 0.0;
  while (drawn < total) {
    final end = math.min(drawn + dash, total);
    canvas.drawLine(a + dir * drawn, a + dir * end, paint);
    drawn += dash + gap;
  }
}

void _arrow(
  Canvas canvas,
  Offset from,
  Offset to,
  Paint paint, {
  double head = 9,
}) {
  canvas.drawLine(from, to, paint);
  final v = to - from;
  if (v.distance < 1) return;
  final angle = math.atan2(v.dy, v.dx);
  final path = Path()
    ..moveTo(to.dx, to.dy)
    ..lineTo(
      to.dx - head * math.cos(angle - 0.4),
      to.dy - head * math.sin(angle - 0.4),
    )
    ..lineTo(
      to.dx - head * math.cos(angle + 0.4),
      to.dy - head * math.sin(angle + 0.4),
    )
    ..close();
  canvas.drawPath(path, Paint()..color = paint.color);
}

Paint _stroke(Color color, double width) => Paint()
  ..color = color
  ..style = PaintingStyle.stroke
  ..strokeWidth = width
  ..strokeCap = StrokeCap.round
  ..strokeJoin = StrokeJoin.round
  ..isAntiAlias = true;

Paint _fill(Color color) => Paint()
  ..color = color
  ..style = PaintingStyle.fill
  ..isAntiAlias = true;

/// 刻度间隔：取"好看的数"（1、2、5 × 10ⁿ），让一条轴上大约有 3–7 个刻度。
double niceStep(double span) {
  if (!span.isFinite || span <= 0) return 1;
  final raw = span / 6;
  final magnitude = math
      .pow(10, (math.log(raw) / math.ln10).floor())
      .toDouble();
  for (final m in [1, 2, 5, 10]) {
    if (raw <= m * magnitude) return m * magnitude;
  }
  return 10 * magnitude;
}

abstract class _VisualPainter extends CustomPainter {
  const _VisualPainter(this.params, this.palette);

  final Map<String, double> params;
  final VisualPalette palette;

  @override
  bool shouldRepaint(covariant _VisualPainter oldDelegate) => true;
}

// ---------------------------------------------------------------- 二次函数

class QuadraticPainter extends _VisualPainter {
  const QuadraticPainter(super.params, super.palette);

  @override
  void paint(Canvas canvas, Size size) {
    final q = quadraticOf(params);
    final plot = Rect.fromLTWH(34, 12, size.width - 50, size.height - 36);
    const xmin = -6.0;
    const xmax = 6.0;

    var lo = 0.0;
    var hi = 0.0;
    for (var i = 0; i <= 120; i++) {
      final y = q.y(xmin + (xmax - xmin) * i / 120);
      lo = math.min(lo, y);
      hi = math.max(hi, y);
    }
    final span = math.max(hi - lo, 4.0);
    lo -= span * 0.1;
    hi += span * 0.1;

    double sx(double x) => plot.left + (x - xmin) / (xmax - xmin) * plot.width;
    double sy(double y) => plot.bottom - (y - lo) / (hi - lo) * plot.height;

    canvas.save();
    canvas.clipRect(plot);

    // 单调性分区
    final h = q.axisX;
    void band(double from, double to, bool increasing) {
      final a = sx(from.clamp(xmin, xmax));
      final b = sx(to.clamp(xmin, xmax));
      if (b - a <= 0) return;
      final color = increasing ? palette.good : palette.warn;
      canvas.drawRect(
        Rect.fromLTRB(a, plot.top, b, plot.bottom),
        _fill(color.withValues(alpha: 0.09)),
      );
      if (b - a > 56) {
        _label(
          canvas,
          increasing ? '递增 ↗' : '递减 ↘',
          Offset(
            (a + b) / 2,
            q.bandLabelsOnTop ? plot.top + 6 : plot.bottom - 6,
          ),
          palette,
          size: 12,
          color: color,
          anchor: q.bandLabelsOnTop
              ? Alignment.topCenter
              : Alignment.bottomCenter,
          weight: FontWeight.w600,
        );
      }
    }

    if (h != null) {
      band(xmin, h, !q.opensUp);
      band(h, xmax, q.opensUp);
    } else if (q.b != 0) {
      band(xmin, xmax, q.b > 0);
    }

    final gridPaint = _stroke(palette.grid, 1);
    final xStep = 2.0;
    for (var x = (xmin / xStep).ceil() * xStep; x <= xmax; x += xStep) {
      canvas.drawLine(
        Offset(sx(x), plot.top),
        Offset(sx(x), plot.bottom),
        gridPaint,
      );
    }
    final yStep = niceStep(hi - lo);
    for (var y = (lo / yStep).ceil() * yStep; y <= hi; y += yStep) {
      canvas.drawLine(
        Offset(plot.left, sy(y)),
        Offset(plot.right, sy(y)),
        gridPaint,
      );
    }
    final axisPaint = _stroke(palette.muted, 1.6);
    canvas.drawLine(
      Offset(plot.left, sy(0)),
      Offset(plot.right, sy(0)),
      axisPaint,
    );
    canvas.drawLine(
      Offset(sx(0), plot.top),
      Offset(sx(0), plot.bottom),
      axisPaint,
    );

    if (h != null && h >= xmin && h <= xmax) {
      _dashed(
        canvas,
        Offset(sx(h), plot.top),
        Offset(sx(h), plot.bottom),
        _stroke(palette.accent, 1.6),
      );
    }

    final path = Path();
    for (var i = 0; i <= 240; i++) {
      final x = xmin + (xmax - xmin) * i / 240;
      final p = Offset(sx(x), sy(q.y(x)));
      i == 0 ? path.moveTo(p.dx, p.dy) : path.lineTo(p.dx, p.dy);
    }
    canvas.drawPath(path, _stroke(palette.curve, 3));
    canvas.restore();

    // 刻度
    for (var x = (xmin / xStep).ceil() * xStep; x <= xmax; x += xStep) {
      if (x == 0) continue;
      _label(
        canvas,
        fmt(x),
        Offset(sx(x), plot.bottom + 3),
        palette,
        size: 10,
        color: palette.muted,
        anchor: Alignment.topCenter,
      );
    }
    for (var y = (lo / yStep).ceil() * yStep; y <= hi; y += yStep) {
      if (y.abs() < 1e-9) continue;
      _label(
        canvas,
        fmt(y, digits: 1),
        Offset(plot.left - 4, sy(y)),
        palette,
        size: 10,
        color: palette.muted,
        anchor: Alignment.centerRight,
      );
    }

    if (h != null && h >= xmin && h <= xmax) {
      final k = q.vertexY!;
      canvas.drawCircle(Offset(sx(h), sy(k)), 5, _fill(palette.accent));
      final onLeft = h > 0;
      _label(
        canvas,
        '顶点 (${fmt(h)}, ${fmt(k)})',
        Offset(sx(h) + (onLeft ? -10 : 10), sy(k) + (q.opensUp ? 14 : -14)),
        palette,
        size: 12,
        color: palette.accent,
        anchor: onLeft ? Alignment.centerRight : Alignment.centerLeft,
        weight: FontWeight.w600,
      );
    }
  }
}

// ---------------------------------------------------------------- 和为定值的矩形

class RectanglePainter extends _VisualPainter {
  const RectanglePainter(super.params, super.palette);

  @override
  void paint(Canvas canvas, Size size) {
    final r = rectangleOf(params);
    final color = r.isSquare ? palette.good : palette.curve;

    // 左：矩形
    final box = Rect.fromLTWH(12, 28, size.width * 0.44 - 12, size.height - 44);
    final unit = math.min(box.width, box.height) / r.sum;
    final w = r.x * unit;
    final h = r.y * unit;
    final rect = Rect.fromLTWH(box.left, box.top, w, h);
    canvas.drawRect(rect, _fill(color.withValues(alpha: 0.18)));
    canvas.drawRect(rect, _stroke(color, 2.4));
    _label(
      canvas,
      'x = ${fmt(r.x)}',
      Offset(rect.center.dx, rect.top - 4),
      palette,
      size: 12,
      anchor: Alignment.bottomCenter,
      weight: FontWeight.w600,
    );
    _label(
      canvas,
      'y = ${fmt(r.y)}',
      Offset(rect.right + 6, rect.center.dy),
      palette,
      size: 12,
      anchor: Alignment.centerLeft,
      weight: FontWeight.w600,
    );
    if (w > 54 && h > 30) {
      _label(
        canvas,
        '面积 ${fmt(r.area)}',
        rect.center,
        palette,
        size: 13,
        anchor: Alignment.center,
        color: color,
        weight: FontWeight.w700,
      );
    }
    if (r.isSquare) {
      _label(
        canvas,
        '正方形：面积最大',
        Offset(box.left, size.height - 6),
        palette,
        size: 12,
        anchor: Alignment.bottomLeft,
        color: palette.good,
        weight: FontWeight.w700,
      );
    }

    // 右：面积随 x 变化
    final plot = Rect.fromLTWH(
      size.width * 0.52 + 28,
      18,
      size.width * 0.48 - 44,
      size.height - 46,
    );
    double sx(double x) => plot.left + x / r.sum * plot.width;
    double sy(double a) => plot.bottom - a / (r.maxArea * 1.1) * plot.height;
    final axis = _stroke(palette.muted, 1.4);
    canvas.drawLine(
      Offset(plot.left, plot.bottom),
      Offset(plot.right, plot.bottom),
      axis,
    );
    canvas.drawLine(
      Offset(plot.left, plot.top),
      Offset(plot.left, plot.bottom),
      axis,
    );
    _dashed(
      canvas,
      Offset(plot.left, sy(r.maxArea)),
      Offset(plot.right, sy(r.maxArea)),
      _stroke(palette.accent, 1.4),
    );
    _label(
      canvas,
      '最大 ${fmt(r.maxArea)}',
      Offset(plot.right, sy(r.maxArea) - 3),
      palette,
      size: 11,
      color: palette.accent,
      anchor: Alignment.bottomRight,
    );
    final curve = Path();
    for (var i = 0; i <= 80; i++) {
      final x = r.sum * i / 80;
      final p = Offset(sx(x), sy(x * (r.sum - x)));
      i == 0 ? curve.moveTo(p.dx, p.dy) : curve.lineTo(p.dx, p.dy);
    }
    canvas.drawPath(curve, _stroke(palette.curve, 2.6));
    final marker = Offset(sx(r.x), sy(r.area));
    canvas.drawCircle(marker, 6, _fill(color));
    _label(
      canvas,
      'x',
      Offset(plot.right, plot.bottom + 3),
      palette,
      size: 11,
      color: palette.muted,
      anchor: Alignment.topRight,
    );
    _label(
      canvas,
      '面积',
      Offset(plot.left - 4, plot.top),
      palette,
      size: 11,
      color: palette.muted,
      anchor: Alignment.topRight,
    );
  }
}

// ---------------------------------------------------------------- 数轴区间

class NumberLinePainter extends _VisualPainter {
  const NumberLinePainter(super.params, super.palette);

  @override
  void paint(Canvas canvas, Size size) {
    final lo = params['min'] ?? -5;
    final hi = params['max'] ?? 5;
    if (!(hi > lo)) return;
    final x0 = 28.0;
    final x1 = size.width - 28;
    final y = size.height * 0.42;
    double sx(double v) => x0 + (v.clamp(lo, hi) - lo) / (hi - lo) * (x1 - x0);

    final axis = _stroke(palette.muted, 2);
    _arrow(canvas, Offset(x0 - 12, y), Offset(x1 + 12, y), axis, head: 10);
    final step = (hi - lo) <= 12 ? 1.0 : ((hi - lo) <= 24 ? 2.0 : 5.0);
    for (var v = (lo / step).ceil() * step; v <= hi; v += step) {
      canvas.drawLine(Offset(sx(v), y - 5), Offset(sx(v), y + 5), axis);
      _label(
        canvas,
        fmt(v),
        Offset(sx(v), y + 9),
        palette,
        size: 11,
        color: palette.muted,
        anchor: Alignment.topCenter,
      );
    }

    final leftUnbounded = (params['left_unbounded'] ?? 0) >= 0.5;
    final rightUnbounded = (params['right_unbounded'] ?? 0) >= 0.5;
    final left = params['left'] ?? 0;
    final right = params['right'] ?? 0;
    final text = intervalText(params);

    if (text == '空集') {
      _label(
        canvas,
        '左端点比右端点大：这一段什么也没有（空集）',
        Offset(size.width / 2, y - 28),
        palette,
        size: 13,
        color: palette.warn,
        anchor: Alignment.bottomCenter,
        weight: FontWeight.w600,
        maxWidth: size.width - 24,
      );
      return;
    }

    final a = leftUnbounded ? x0 - 12 : sx(left);
    final b = rightUnbounded ? x1 + 12 : sx(right);
    canvas.drawLine(Offset(a, y), Offset(b, y), _stroke(palette.curve, 7));
    if (leftUnbounded) {
      _arrow(
        canvas,
        Offset(a + 6, y - 14),
        Offset(a - 4, y - 14),
        _stroke(palette.curve, 3),
      );
    }
    if (rightUnbounded) {
      _arrow(
        canvas,
        Offset(b - 6, y - 14),
        Offset(b + 4, y - 14),
        _stroke(palette.curve, 3),
      );
    }

    void endpoint(double x, bool closed) {
      final c = Offset(x, y);
      if (closed) {
        canvas.drawCircle(c, 8, _fill(palette.curve));
      } else {
        canvas.drawCircle(c, 8, _fill(palette.surface));
        canvas.drawCircle(c, 8, _stroke(palette.curve, 3));
      }
    }

    if (!leftUnbounded) endpoint(sx(left), (params['left_closed'] ?? 0) >= 0.5);
    if (!rightUnbounded) {
      endpoint(sx(right), (params['right_closed'] ?? 0) >= 0.5);
    }

    _label(
      canvas,
      '区间 $text',
      Offset(size.width / 2, size.height - 8),
      palette,
      size: 14,
      anchor: Alignment.bottomCenter,
      color: palette.curve,
      weight: FontWeight.w700,
      maxWidth: size.width - 24,
    );
    _label(
      canvas,
      '实心点：包含端点　空心点：不含端点',
      Offset(size.width / 2, 8),
      palette,
      size: 11,
      color: palette.muted,
      anchor: Alignment.topCenter,
      maxWidth: size.width - 24,
    );
  }
}

// ---------------------------------------------------------------- 斜面受力

class ForceDiagramPainter extends _VisualPainter {
  const ForceDiagramPainter(super.params, super.palette);

  @override
  void paint(Canvas canvas, Size size) {
    final f = forcesOf(params);
    final theta = f.angleRad;
    final sinT = math.sin(theta);
    final cosT = math.cos(theta);

    final bottom = size.height - 26;
    final left = 22.0;
    final maxRun = size.width * 0.6;
    final maxRise = size.height - 92;
    final run = sinT < 1e-6
        ? maxRun
        : math.min(maxRun, maxRise / math.tan(theta).clamp(0.05, 100));
    final a = Offset(left, bottom);
    final b = Offset(left + run, bottom);
    final c = Offset(left + run, bottom - run * math.tan(theta));
    final slope = Path()
      ..moveTo(a.dx, a.dy)
      ..lineTo(b.dx, b.dy)
      ..lineTo(c.dx, c.dy)
      ..close();
    canvas.drawPath(slope, _fill(palette.grid.withValues(alpha: 0.35)));
    canvas.drawPath(slope, _stroke(palette.muted, 2));

    final u = Offset(cosT, -sinT); // 沿斜面向上
    final n = Offset(-sinT, -cosT); // 垂直斜面向外
    final surface = (c - a).distance;
    final p = a + u * (surface * 0.5);
    final center = p + n * 13;

    canvas.save();
    canvas.translate(p.dx, p.dy);
    canvas.rotate(-theta);
    final block = RRect.fromRectAndRadius(
      const Rect.fromLTWH(-20, -26, 40, 26),
      const Radius.circular(3),
    );
    canvas.drawRRect(block, _fill(palette.accent.withValues(alpha: 0.30)));
    canvas.drawRRect(block, _stroke(palette.accent, 2));
    canvas.restore();

    if (theta > 0.02) {
      final arc = Rect.fromCircle(center: a, radius: 34);
      canvas.drawArc(arc, 0, -theta, false, _stroke(palette.muted, 1.6));
      _label(
        canvas,
        'θ = ${fmt(f.angleRad * 180 / math.pi, digits: 0)}°',
        a + const Offset(40, -4),
        palette,
        size: 12,
        anchor: Alignment.bottomLeft,
        color: palette.muted,
      );
    }

    final scale = 66 / math.max(f.weight, 1e-9);
    void force(
      Offset dir,
      double value,
      String name,
      Color color, {
      bool dashed = false,
      Alignment at = Alignment.center,
    }) {
      if (value < 1e-6) return;
      final end = center + dir * (value * scale);
      final paint = _stroke(color, dashed ? 1.8 : 2.8);
      if (dashed) {
        _dashed(canvas, center, end, paint);
      } else {
        _arrow(canvas, center, end, paint);
      }
      _label(
        canvas,
        '$name ${fmt(value, digits: 1)} N',
        end + dir * 6,
        palette,
        size: 11,
        color: color,
        anchor: Alignment(-dir.dx.sign.toDouble(), -dir.dy.sign.toDouble()),
        weight: FontWeight.w600,
        maxWidth: 110,
      );
    }

    force(const Offset(0, 1), f.weight, 'mg', palette.ink);
    force(n, f.normal, 'N', palette.curve);
    force(u, f.friction, 'f', palette.warn);
    force(-u, f.alongSlope, 'mg sinθ', palette.muted, dashed: true);
    force(-n, f.normal, 'mg cosθ', palette.muted, dashed: true);

    final status = f.sliding
        ? '沿斜面下滑，加速度 a = ${fmt(f.acceleration)} m/s²'
        : '保持静止（静摩擦力 f = mg sinθ）';
    _label(
      canvas,
      status,
      Offset(size.width - 10, 8),
      palette,
      size: 13,
      anchor: Alignment.topRight,
      color: f.sliding ? palette.warn : palette.good,
      weight: FontWeight.w700,
      maxWidth: size.width * 0.5,
      align: TextAlign.right,
    );
    _label(
      canvas,
      'mg sinθ = ${fmt(f.alongSlope, digits: 1)} N\n最大静摩擦力 ≈ μmg cosθ = ${fmt(f.maxStaticFriction, digits: 1)} N',
      Offset(size.width - 10, size.height - 8),
      palette,
      size: 11,
      anchor: Alignment.bottomRight,
      color: palette.muted,
      maxWidth: size.width * 0.4,
      align: TextAlign.right,
    );
  }
}

// ---------------------------------------------------------------- v–t 图

class MotionChartPainter extends _VisualPainter {
  const MotionChartPainter(super.params, super.palette);

  @override
  void paint(Canvas canvas, Size size) {
    final m = motionOf(params);
    final plot = Rect.fromLTWH(44, 16, size.width - 62, size.height - 44);
    var lo = math.min(0.0, math.min(m.v0, m.endVelocity));
    var hi = math.max(0.0, math.max(m.v0, m.endVelocity));
    final span = math.max(hi - lo, 2.0);
    lo -= span * 0.12;
    hi += span * 0.12;
    double sx(double t) => plot.left + t / m.tMax * plot.width;
    double sy(double v) => plot.bottom - (v - lo) / (hi - lo) * plot.height;

    final gridPaint = _stroke(palette.grid, 1);
    final vStep = niceStep(hi - lo);
    for (var v = (lo / vStep).ceil() * vStep; v <= hi; v += vStep) {
      canvas.drawLine(
        Offset(plot.left, sy(v)),
        Offset(plot.right, sy(v)),
        gridPaint,
      );
      _label(
        canvas,
        fmt(v, digits: 1),
        Offset(plot.left - 5, sy(v)),
        palette,
        size: 10,
        color: palette.muted,
        anchor: Alignment.centerRight,
      );
    }
    final tStep = niceStep(m.tMax);
    for (var t = 0.0; t <= m.tMax + 1e-9; t += tStep) {
      canvas.drawLine(
        Offset(sx(t), plot.top),
        Offset(sx(t), plot.bottom),
        gridPaint,
      );
      _label(
        canvas,
        fmt(t),
        Offset(sx(t), plot.bottom + 4),
        palette,
        size: 10,
        color: palette.muted,
        anchor: Alignment.topCenter,
      );
    }

    void area(double t0, double t1, Color color) {
      if (t1 - t0 <= 1e-9) return;
      final path = Path()
        ..moveTo(sx(t0), sy(0))
        ..lineTo(sx(t0), sy(m.v(t0)))
        ..lineTo(sx(t1), sy(m.v(t1)))
        ..lineTo(sx(t1), sy(0))
        ..close();
      canvas.drawPath(path, _fill(color.withValues(alpha: 0.22)));
    }

    final stop = m.stopTime;
    if (stop == null) {
      area(
        0,
        m.tMax,
        (m.v0 + m.endVelocity) >= 0 ? palette.good : palette.warn,
      );
    } else {
      area(0, stop, m.v0 >= 0 ? palette.good : palette.warn);
      area(stop, m.tMax, m.endVelocity >= 0 ? palette.good : palette.warn);
    }

    final axis = _stroke(palette.muted, 1.8);
    canvas.drawLine(Offset(plot.left, sy(0)), Offset(plot.right, sy(0)), axis);
    canvas.drawLine(
      Offset(plot.left, plot.top),
      Offset(plot.left, plot.bottom),
      axis,
    );
    canvas.drawLine(
      Offset(sx(0), sy(m.v0)),
      Offset(sx(m.tMax), sy(m.endVelocity)),
      _stroke(palette.curve, 3.2),
    );
    canvas.drawCircle(Offset(sx(0), sy(m.v0)), 4.5, _fill(palette.curve));
    canvas.drawCircle(
      Offset(sx(m.tMax), sy(m.endVelocity)),
      4.5,
      _fill(palette.curve),
    );

    _label(
      canvas,
      'v (m/s)',
      Offset(plot.left, plot.top - 2),
      palette,
      size: 11,
      color: palette.muted,
      anchor: Alignment.bottomLeft,
    );
    _label(
      canvas,
      't (s)',
      Offset(plot.right, plot.bottom + 4),
      palette,
      size: 11,
      color: palette.muted,
      anchor: Alignment.topRight,
    );
    _label(
      canvas,
      '斜率 = a = ${fmt(m.a)} m/s²　v₀ = ${fmt(m.v0)} m/s　v = ${fmt(m.endVelocity)} m/s',
      Offset(plot.left + 8, plot.top + 6),
      palette,
      size: 12,
      anchor: Alignment.topLeft,
      color: palette.curve,
      weight: FontWeight.w600,
      maxWidth: plot.width - 16,
    );
    _label(
      canvas,
      '图线下的面积（有正负）= 位移 x = ${fmt(m.displacement)} m',
      Offset(plot.right - 8, plot.bottom - 6),
      palette,
      size: 12,
      anchor: Alignment.bottomRight,
      color: palette.ink,
      weight: FontWeight.w600,
      maxWidth: plot.width - 16,
      align: TextAlign.right,
    );
  }
}

// ---------------------------------------------------------------- 化学计量换算

class ChemicalFlowPainter extends _VisualPainter {
  const ChemicalFlowPainter(super.params, super.palette);

  @override
  void paint(Canvas canvas, Size size) {
    final f = flowOf(params);
    final boxes = [
      ('已知物 A', '质量\n${fmt(f.massA)} g'),
      ('物质的量 n(A)', '${fmt(f.molesA, digits: 3)} mol'),
      ('物质的量 n(B)', '${fmt(f.molesB, digits: 3)} mol'),
      ('所求物 B', '质量\n${fmt(f.massB)} g'),
    ];
    final arrows = [
      '÷ M(A)\n${fmt(f.molarMassA)} g/mol',
      '× 计量数比\n${fmt(f.coefB, digits: 0)}/${fmt(f.coefA, digits: 0)}',
      '× M(B)\n${fmt(f.molarMassB)} g/mol',
    ];
    final gap = math.min(54.0, size.width * 0.1);
    const margin = 12.0;
    final boxWidth = math.max((size.width - margin * 2 - gap * 3) / 4, 8.0);
    final boxHeight = math.min(86.0, size.height * 0.52);
    final top = (size.height - boxHeight) / 2 + 6;
    final fontSize = boxWidth < 70 ? 10.0 : 12.0;

    for (var i = 0; i < 4; i++) {
      final left = margin + i * (boxWidth + gap);
      final rect = RRect.fromRectAndRadius(
        Rect.fromLTWH(left, top, boxWidth, boxHeight),
        const Radius.circular(12),
      );
      final highlight = i == 3
          ? palette.good
          : (i == 0 ? palette.accent : palette.curve);
      canvas.drawRRect(rect, _fill(highlight.withValues(alpha: 0.12)));
      canvas.drawRRect(rect, _stroke(highlight, 2));
      _label(
        canvas,
        boxes[i].$1,
        Offset(rect.center.dx, rect.top + 8),
        palette,
        size: fontSize - 1,
        anchor: Alignment.topCenter,
        color: palette.muted,
        maxWidth: boxWidth - 8,
        align: TextAlign.center,
      );
      _label(
        canvas,
        boxes[i].$2,
        Offset(rect.center.dx, rect.center.dy + 8),
        palette,
        size: fontSize + 2,
        anchor: Alignment.center,
        weight: FontWeight.w700,
        maxWidth: boxWidth - 8,
        align: TextAlign.center,
      );
      if (i < 3) {
        final y = top + boxHeight / 2;
        _arrow(
          canvas,
          Offset(rect.right + 6, y),
          Offset(rect.right + gap - 6, y),
          _stroke(palette.muted, 2),
        );
        _label(
          canvas,
          arrows[i],
          Offset(rect.right + gap / 2, y - 8),
          palette,
          size: fontSize - 1,
          anchor: Alignment.bottomCenter,
          color: palette.muted,
          maxWidth: gap + 20,
          align: TextAlign.center,
        );
      }
    }
    _label(
      canvas,
      '质量 → 物质的量 → 按化学计量数之比换算 → 质量',
      Offset(size.width / 2, size.height - 8),
      palette,
      size: 12,
      anchor: Alignment.bottomCenter,
      color: palette.muted,
      maxWidth: size.width - 24,
      align: TextAlign.center,
    );
  }
}

CustomPainter painterFor(
  String templateId,
  Map<String, double> params,
  VisualPalette palette,
) {
  return switch (templateId) {
    'quadratic_graph' => QuadraticPainter(params, palette),
    'rectangle_area' => RectanglePainter(params, palette),
    'number_line' => NumberLinePainter(params, palette),
    'force_diagram' => ForceDiagramPainter(params, palette),
    'motion_chart' => MotionChartPainter(params, palette),
    'chemical_flow' => ChemicalFlowPainter(params, palette),
    _ => throw ArgumentError('没有注册的图解模板：$templateId'),
  };
}

/// 给读屏用户的文字摘要（图本身读不出来）。
String describeVisual(String templateId, Map<String, double> p) {
  switch (templateId) {
    case 'quadratic_graph':
      final q = quadraticOf(p);
      return q.isQuadratic
          ? '二次函数图像，开口${q.opensUp ? '向上' : '向下'}，对称轴 x = ${fmt(q.axisX!)}，顶点纵坐标 ${fmt(q.vertexY!)}。${q.increasingText}。'
          : '一次函数图像。${q.increasingText}。';
    case 'rectangle_area':
      final r = rectangleOf(p);
      return '两边之和为 ${fmt(r.sum)} 的矩形，边长 ${fmt(r.x)} 和 ${fmt(r.y)}，面积 ${fmt(r.area)}，最大面积 ${fmt(r.maxArea)}。';
    case 'number_line':
      return '数轴上标出的区间 ${intervalText(p)}。';
    case 'force_diagram':
      final f = forcesOf(p);
      return '斜面上的物块，重力 ${fmt(f.weight, digits: 1)} 牛，沿斜面分力 ${fmt(f.alongSlope, digits: 1)} 牛，${f.sliding ? '下滑，加速度 ${fmt(f.acceleration)} 米每二次方秒' : '保持静止'}。';
    case 'motion_chart':
      final m = motionOf(p);
      return '速度时间图，初速度 ${fmt(m.v0)}，加速度 ${fmt(m.a)}，位移 ${fmt(m.displacement)} 米。';
    case 'chemical_flow':
      final f = flowOf(p);
      return '化学计量换算：已知物 ${fmt(f.massA)} 克，物质的量 ${fmt(f.molesA, digits: 3)} 摩尔，所求物质量 ${fmt(f.massB)} 克。';
    default:
      return '图解';
  }
}
