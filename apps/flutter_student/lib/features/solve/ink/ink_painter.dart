import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'ink_controller.dart';

/// 草稿纸始终是浅色：笔迹的颜色（黑、蓝）有意义，深色主题下也要看得清。
const Color paperColor = Color(0xFFFBFAF5);
const Color _ruleColor = Color(0x16000000);
const double _ruleSpacing = 70;

Color parseHexColor(String hex) {
  final value = int.tryParse(hex.substring(1), radix: 16) ?? 0x1A1A1A;
  return Color(0xFF000000 | value);
}

/// 画一页草稿。画布显示和导出图片共用这一个函数，所以导出的就是看到的。
void paintInkPage(Canvas canvas, Size size, InkPage page, {bool ruled = true}) {
  canvas.drawRect(Offset.zero & size, Paint()..color = paperColor);
  canvas.save();
  canvas.scale(size.width / page.width);
  if (ruled) {
    final rule = Paint()
      ..color = _ruleColor
      ..strokeWidth = 1;
    for (var y = _ruleSpacing; y < page.height; y += _ruleSpacing) {
      canvas.drawLine(Offset(0, y), Offset(page.width, y), rule);
    }
  }
  for (final stroke in page.strokes) {
    _paintStroke(canvas, stroke);
  }
  canvas.restore();
}

void _paintStroke(Canvas canvas, InkStroke stroke) {
  final p = stroke.points;
  final n = stroke.pointCount;
  if (n == 0) return;
  final paint = Paint()
    ..color = parseHexColor(stroke.color)
    ..strokeWidth = stroke.width
    ..strokeCap = StrokeCap.round
    ..strokeJoin = StrokeJoin.round
    ..isAntiAlias = true;
  if (n == 1) {
    canvas.drawCircle(
      Offset(p[0], p[1]),
      stroke.width / 2,
      paint..style = PaintingStyle.fill,
    );
    return;
  }
  paint.style = PaintingStyle.stroke;
  final path = Path()..moveTo(p[0], p[1]);
  for (var i = 1; i < n - 1; i++) {
    final x = p[i * 4];
    final y = p[i * 4 + 1];
    final nx = p[(i + 1) * 4];
    final ny = p[(i + 1) * 4 + 1];
    path.quadraticBezierTo(x, y, (x + nx) / 2, (y + ny) / 2);
  }
  path.lineTo(p[(n - 1) * 4], p[(n - 1) * 4 + 1]);
  canvas.drawPath(path, paint);
}

class InkPagePainter extends CustomPainter {
  InkPagePainter(this.page, Listenable repaint) : super(repaint: repaint);

  final InkPage page;

  @override
  void paint(Canvas canvas, Size size) => paintInkPage(canvas, size, page);

  @override
  bool shouldRepaint(InkPagePainter oldDelegate) =>
      !identical(oldDelegate.page, page);
}

/// 把所有页面竖向拼成一张 PNG。[pixelWidth] 是图片宽度（像素）。
Future<Uint8List> renderInkPng(
  List<InkPage> pages, {
  double pixelWidth = 1200,
}) async {
  final heights = [for (final p in pages) pixelWidth * p.height / p.width];
  final totalHeight = heights.fold<double>(0, (a, b) => a + b);
  final recorder = ui.PictureRecorder();
  final canvas = Canvas(recorder);
  var top = 0.0;
  for (var i = 0; i < pages.length; i++) {
    canvas.save();
    canvas.translate(0, top);
    paintInkPage(canvas, Size(pixelWidth, heights[i]), pages[i]);
    canvas.restore();
    top += heights[i];
  }
  final picture = recorder.endRecording();
  final image = await picture.toImage(pixelWidth.round(), totalHeight.round());
  final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
  image.dispose();
  picture.dispose();
  return bytes!.buffer.asUint8List();
}
