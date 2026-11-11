import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

enum InkTool { pen, eraser, hand }

/// 一条笔画。points 是扁平数组，每 4 个数为一个采样点：x、y（页面逻辑坐标）、
/// t（距笔画起点的毫秒数）、p（压力 0~1，取不到时为 0.5）——与契约里的 Stroke 一致。
class InkStroke {
  InkStroke({required this.color, required this.width, List<double>? points})
    : points = points ?? <double>[];

  final String color;
  final double width;
  final List<double> points;

  int get pointCount => points.length ~/ 4;

  Stroke toContract() =>
      Stroke(color: color, width: width, points: List.of(points));
}

class InkPage {
  InkPage({required this.width, required this.height, List<InkStroke>? strokes})
    : strokes = strokes ?? <InkStroke>[];

  final double width;
  final double height;
  List<InkStroke> strokes;
}

class _Edit {
  _Edit(this.page, this.before, this.after);

  final int page;
  final List<InkStroke> before;
  final List<InkStroke> after;
}

final RegExp _colorPattern = RegExp(r'^#[0-9A-Fa-f]{6}$');

/// 草稿画布的数据与操作（笔、橡皮、撤销/重做、清空、多页）。
///
/// 与界面无关，所以可以脱离 Widget 做单元测试。每一步"完成"的操作（一条笔画结束、
/// 一次擦除结束、撤销、重做、清空、加页）调用一次 [onCommit]，用来触发本地保存；
/// 书写过程中的每个点不触发。
class InkController extends ChangeNotifier {
  InkController({
    this.onCommit,
    this.maxPages = 20,
    this.maxStrokesPerPage = 3000,
    this.maxPointsPerStroke = 8000,
    this.maxHistory = 100,
  }) : pages = [InkPage(width: pageWidth, height: pageHeight)];

  /// 页面逻辑坐标系的大小。笔迹按这个坐标存，所以改变面板宽度不会让笔迹错位。
  static const double pageWidth = 1000;
  static const double pageHeight = 1400;
  static const double minWidth = 0.5;
  static const double maxWidth = 24;

  /// 相邻采样点小于这个距离（页面坐标）就不记录。
  static const double _minStep = 0.6;

  VoidCallback? onCommit;
  final int maxPages;
  final int maxStrokesPerPage;
  final int maxPointsPerStroke;
  final int maxHistory;

  final List<InkPage> pages;

  InkTool tool = InkTool.pen;
  String color = '#1A1A1A';
  double width = 2.5;

  /// 见到过手写笔之后，手指不再书写（防止手掌误触）。
  bool stylusSeen = false;

  final List<_Edit> _undo = [];
  final List<_Edit> _redo = [];

  InkStroke? _active;
  int _activePage = 0;
  int _lastT = 0;

  List<InkStroke>? _eraseBefore;
  int _erasePage = 0;

  void selectTool(InkTool value) {
    if (tool == value) return;
    tool = value;
    notifyListeners();
  }

  /// 颜色必须是 `#RRGGBB`（契约的约束）；不合规的值忽略。
  void selectColor(String hex) {
    if (!_colorPattern.hasMatch(hex) || color == hex) return;
    color = hex;
    notifyListeners();
  }

  void selectWidth(double value) {
    final bounded = value.clamp(minWidth, maxWidth).toDouble();
    if (width == bounded) return;
    width = bounded;
    notifyListeners();
  }

  bool get canUndo => _undo.isNotEmpty;
  bool get canRedo => _redo.isNotEmpty;
  bool get canAddPage => pages.length < maxPages;
  bool get hasInk => pages.any((p) => p.strokes.isNotEmpty);
  bool get isDrawing => _active != null;

  void _commit() {
    notifyListeners();
    onCommit?.call();
  }

  void _record(int page, List<InkStroke> before, List<InkStroke> after) {
    _undo.add(_Edit(page, before, after));
    if (_undo.length > maxHistory) _undo.removeAt(0);
    _redo.clear();
  }

  // ---- 笔 ----

  bool beginStroke(
    int page,
    double x,
    double y, {
    int t = 0,
    double pressure = 0.5,
  }) {
    if (_active != null) cancelStroke();
    final target = pages[page];
    if (target.strokes.length >= maxStrokesPerPage) return false;
    final stroke = InkStroke(
      color: color,
      width: width.clamp(minWidth, maxWidth).toDouble(),
    );
    _addPoint(stroke, x, y, 0, pressure);
    _active = stroke;
    _activePage = page;
    _lastT = 0;
    // 先放进页面，这样画的过程中画布直接看得到；结束时再记入历史
    target.strokes = [...target.strokes, stroke];
    notifyListeners();
    return true;
  }

  void extendStroke(double x, double y, {int t = 0, double pressure = 0.5}) {
    final stroke = _active;
    if (stroke == null) return;
    if (stroke.pointCount >= maxPointsPerStroke) return;
    final n = stroke.points.length;
    final dx = x - stroke.points[n - 4];
    final dy = y - stroke.points[n - 3];
    if (math.sqrt(dx * dx + dy * dy) < _minStep) return;
    _lastT = math.max(_lastT, t);
    _addPoint(stroke, x, y, _lastT, pressure);
    notifyListeners();
  }

  void endStroke() {
    final stroke = _active;
    if (stroke == null) return;
    final page = pages[_activePage];
    _active = null;
    final after = page.strokes;
    final before = after.sublist(0, after.length - 1);
    _record(_activePage, before, List.of(after));
    _commit();
  }

  void cancelStroke() {
    final stroke = _active;
    if (stroke == null) return;
    final page = pages[_activePage];
    page.strokes = page.strokes.where((s) => !identical(s, stroke)).toList();
    _active = null;
    notifyListeners();
  }

  void _addPoint(InkStroke stroke, double x, double y, int t, double pressure) {
    stroke.points.addAll([
      x,
      y,
      t.toDouble(),
      pressure.isFinite ? pressure.clamp(0, 1).toDouble() : 0.5,
    ]);
  }

  // ---- 橡皮 ----

  /// 擦掉碰到 (x, y) 附近 [radius]（页面坐标）的笔画。一次拖动里多次调用，
  /// 在 [endErase] 时合成一条历史记录。
  void eraseAt(int page, double x, double y, double radius) {
    final strokes = pages[page].strokes;
    final kept = strokes.where((s) => !_hits(s, x, y, radius)).toList();
    if (kept.length == strokes.length) return;
    if (_eraseBefore == null || _erasePage != page) {
      _eraseBefore = strokes;
      _erasePage = page;
    }
    pages[page].strokes = kept;
    notifyListeners();
  }

  void endErase() {
    final before = _eraseBefore;
    if (before == null) return;
    _eraseBefore = null;
    _record(_erasePage, before, List.of(pages[_erasePage].strokes));
    _commit();
  }

  static bool _hits(InkStroke stroke, double x, double y, double radius) {
    final reach = radius + stroke.width / 2;
    final p = stroke.points;
    if (stroke.pointCount == 1) {
      return math.sqrt(math.pow(p[0] - x, 2) + math.pow(p[1] - y, 2)) <= reach;
    }
    for (var i = 0; i + 7 < p.length; i += 4) {
      if (_segmentDistance(x, y, p[i], p[i + 1], p[i + 4], p[i + 5]) <= reach) {
        return true;
      }
    }
    return false;
  }

  static double _segmentDistance(
    double px,
    double py,
    double ax,
    double ay,
    double bx,
    double by,
  ) {
    final dx = bx - ax;
    final dy = by - ay;
    final lengthSquared = dx * dx + dy * dy;
    var t = lengthSquared == 0
        ? 0.0
        : ((px - ax) * dx + (py - ay) * dy) / lengthSquared;
    t = t.clamp(0.0, 1.0);
    final cx = ax + t * dx;
    final cy = ay + t * dy;
    return math.sqrt(math.pow(px - cx, 2) + math.pow(py - cy, 2));
  }

  // ---- 历史 ----

  void undo() {
    if (_undo.isEmpty) return;
    final edit = _undo.removeLast();
    pages[edit.page].strokes = List.of(edit.before);
    _redo.add(edit);
    _commit();
  }

  void redo() {
    if (_redo.isEmpty) return;
    final edit = _redo.removeLast();
    pages[edit.page].strokes = List.of(edit.after);
    _undo.add(edit);
    _commit();
  }

  void clearPage(int page) {
    final before = pages[page].strokes;
    if (before.isEmpty) return;
    pages[page].strokes = [];
    _record(page, before, const []);
    _commit();
  }

  void clearAll() {
    for (var i = 0; i < pages.length; i++) {
      clearPage(i);
    }
  }

  void addPage() {
    if (!canAddPage) return;
    pages.add(InkPage(width: pageWidth, height: pageHeight));
    _commit();
  }

  // ---- 与契约互转 ----

  StrokeDoc toContract() => StrokeDoc(
    version: 1,
    pages: [
      for (final page in pages)
        StrokePage(
          width: page.width,
          height: page.height,
          strokes: [for (final s in page.strokes) s.toContract()],
        ),
    ],
  );

  /// 用一份文档替换当前内容（不带历史、不算提交）。不合规的笔画直接丢弃。
  void loadContract(StrokeDoc? doc) {
    pages.clear();
    _undo.clear();
    _redo.clear();
    _active = null;
    _eraseBefore = null;
    for (final page in doc?.pages.take(maxPages) ?? const <StrokePage>[]) {
      pages.add(
        InkPage(
          width: page.width,
          height: page.height,
          strokes: [
            for (final s in page.strokes.take(maxStrokesPerPage))
              if (_colorPattern.hasMatch(s.color) &&
                  s.points.isNotEmpty &&
                  s.points.length % 4 == 0 &&
                  s.points.length ~/ 4 <= maxPointsPerStroke)
                InkStroke(
                  color: s.color,
                  width: s.width.clamp(minWidth, maxWidth).toDouble(),
                  points: List.of(s.points),
                ),
          ],
        ),
      );
    }
    if (pages.isEmpty) pages.add(InkPage(width: pageWidth, height: pageHeight));
    notifyListeners();
  }
}
