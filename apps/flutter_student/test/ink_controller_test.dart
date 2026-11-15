import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/features/solve/ink/ink_controller.dart';

/// 在第 [page] 页画一条从 (x0, y0) 到 (x1, y1) 的笔画。
void drawLine(
  InkController ink,
  double x0,
  double y0,
  double x1,
  double y1, {
  int page = 0,
}) {
  ink.beginStroke(page, x0, y0, t: 0, pressure: 0.5);
  ink.extendStroke((x0 + x1) / 2, (y0 + y1) / 2, t: 8, pressure: 0.6);
  ink.extendStroke(x1, y1, t: 16, pressure: 0.5);
  ink.endStroke();
}

void main() {
  late int commits;
  late InkController ink;

  setUp(() {
    commits = 0;
    ink = InkController(onCommit: () => commits += 1);
  });

  group('笔画', () {
    test('一次书写生成一条笔画，点按 x、y、时间、压力 4 个一组存放', () {
      drawLine(ink, 10, 20, 30, 40);

      final stroke = ink.pages.single.strokes.single;
      expect(stroke.pointCount, 3);
      expect(stroke.points.sublist(0, 4), [10, 20, 0, 0.5]);
      expect(stroke.points.sublist(8, 12), [30, 40, 16, 0.5]);
      expect(stroke.color, '#1A1A1A');
      expect(stroke.width, 2.5);
      expect(ink.hasInk, isTrue);
    });

    test('只在笔画结束时算一次"提交"，书写过程中的每个点不算', () {
      ink.beginStroke(0, 0, 0);
      for (var i = 1; i <= 20; i++) {
        ink.extendStroke(i * 5.0, i * 3.0, t: i * 8);
      }
      expect(commits, 0);
      ink.endStroke();
      expect(commits, 1);
    });

    test('几乎没动的点不重复记录，但终点一定在', () {
      ink.beginStroke(0, 100, 100);
      ink.extendStroke(100.1, 100.1, t: 5);
      ink.extendStroke(100.2, 100.0, t: 10);
      ink.extendStroke(140, 100, t: 20);
      ink.endStroke();

      final points = ink.pages.single.strokes.single.points;
      expect(points.length ~/ 4, 2);
      expect(points[points.length - 4], 140);
    });

    test('点一下也是一条笔画（一个点）', () {
      ink.beginStroke(0, 50, 60);
      ink.endStroke();
      expect(ink.pages.single.strokes.single.pointCount, 1);
    });

    test('颜色和粗细按设置记录，并收进契约允许的范围', () {
      ink.color = '#1D4ED8';
      ink.width = 4;
      drawLine(ink, 0, 0, 10, 10);
      ink.width = 999;
      drawLine(ink, 0, 20, 10, 30);

      final strokes = ink.pages.single.strokes;
      expect(strokes[0].color, '#1D4ED8');
      expect(strokes[0].width, 4);
      expect(strokes[1].width, 24);
    });

    test('手写笔的压力取不到时用 0.5；时间戳单调不减', () {
      ink.beginStroke(0, 0, 0, t: 10);
      ink.extendStroke(50, 50, t: 5, pressure: 0.9);
      ink.endStroke();
      final points = ink.pages.single.strokes.single.points;
      expect(points[3], 0.5);
      expect(points[6] >= points[2], isTrue);
    });

    test('笔画数达到上限后不再接受新笔画', () {
      final small = InkController(maxStrokesPerPage: 2);
      drawLine(small, 0, 0, 10, 10);
      drawLine(small, 0, 20, 10, 30);
      expect(small.beginStroke(0, 0, 40), isFalse);
      expect(small.pages.single.strokes, hasLength(2));
    });

    test('单条笔画的点数有上限', () {
      final small = InkController(maxPointsPerStroke: 5);
      small.beginStroke(0, 0, 0);
      for (var i = 1; i < 50; i++) {
        small.extendStroke(i * 10.0, 0, t: i);
      }
      small.endStroke();
      expect(small.pages.single.strokes.single.pointCount, 5);
    });

    test('取消一条笔画不留痕迹，也不算提交', () {
      ink.beginStroke(0, 0, 0);
      ink.extendStroke(30, 30);
      ink.cancelStroke();
      expect(ink.pages.single.strokes, isEmpty);
      expect(commits, 0);
      expect(ink.canUndo, isFalse);
    });
  });

  group('工具、颜色、粗细', () {
    test('切换时通知界面；设成同一个值不重复通知', () {
      var notified = 0;
      ink.addListener(() => notified += 1);

      ink.selectTool(InkTool.eraser);
      ink.selectTool(InkTool.eraser);
      ink.selectColor('#1D4ED8');
      ink.selectWidth(4.5);

      expect(notified, 3);
      expect(ink.tool, InkTool.eraser);
      expect(commits, 0, reason: '换工具不是对草稿内容的修改，不需要保存');
    });

    test('不合规的颜色和超范围的粗细被拒绝或收进范围', () {
      ink.selectColor('blue');
      ink.selectColor('#12');
      expect(ink.color, '#1A1A1A');
      ink.selectWidth(0.01);
      expect(ink.width, 0.5);
    });
  });

  group('撤销与重做', () {
    test('撤销、重做、再写新笔画会清掉重做栈', () {
      drawLine(ink, 0, 0, 10, 10);
      drawLine(ink, 0, 20, 10, 30);
      expect(ink.canUndo, isTrue);
      expect(ink.canRedo, isFalse);

      ink.undo();
      expect(ink.pages.single.strokes, hasLength(1));
      expect(ink.canRedo, isTrue);
      ink.redo();
      expect(ink.pages.single.strokes, hasLength(2));

      ink.undo();
      drawLine(ink, 0, 40, 10, 50);
      expect(ink.canRedo, isFalse);
      expect(ink.pages.single.strokes, hasLength(2));
    });

    test('没有可撤销的内容时撤销什么也不做，也不算提交', () {
      ink.undo();
      ink.redo();
      expect(commits, 0);
    });

    test('每次撤销、重做各算一次提交（需要触发保存）', () {
      drawLine(ink, 0, 0, 10, 10);
      ink.undo();
      ink.redo();
      expect(commits, 3);
    });

    test('历史有长度上限，最早的操作会被丢掉', () {
      final bounded = InkController(maxHistory: 3);
      for (var i = 0; i < 6; i++) {
        drawLine(bounded, 0, i * 20.0, 10, i * 20.0 + 10);
      }
      var undone = 0;
      while (bounded.canUndo) {
        bounded.undo();
        undone += 1;
      }
      expect(undone, 3);
      expect(bounded.pages.single.strokes, hasLength(3));
    });
  });

  group('橡皮', () {
    test('擦掉被碰到的笔画，其他笔画保留', () {
      drawLine(ink, 0, 100, 200, 100);
      drawLine(ink, 0, 300, 200, 300);

      ink.eraseAt(0, 100, 102, 10);
      ink.endErase();

      final strokes = ink.pages.single.strokes;
      expect(strokes, hasLength(1));
      expect(strokes.single.points[1], 300);
    });

    test('擦除一整次拖动可以一次撤销，顺序与位置都恢复', () {
      drawLine(ink, 0, 100, 200, 100);
      drawLine(ink, 0, 200, 200, 200);
      drawLine(ink, 0, 300, 200, 300);

      ink.eraseAt(0, 100, 100, 8);
      ink.eraseAt(0, 100, 300, 8);
      ink.endErase();
      expect(ink.pages.single.strokes, hasLength(1));

      ink.undo();
      expect(ink.pages.single.strokes.map((s) => s.points[1]), [100, 200, 300]);
      ink.redo();
      expect(ink.pages.single.strokes.map((s) => s.points[1]), [200]);
    });

    test('没擦到任何笔画时不产生历史、不算提交', () {
      drawLine(ink, 0, 100, 200, 100);
      final before = commits;
      ink.eraseAt(0, 500, 500, 10);
      ink.endErase();
      expect(commits, before);
      expect(ink.pages.single.strokes, hasLength(1));
    });

    test('笔画较粗时，碰到边缘也算擦到', () {
      ink.width = 20;
      drawLine(ink, 0, 100, 200, 100);
      ink.eraseAt(0, 100, 108, 2);
      ink.endErase();
      expect(ink.pages.single.strokes, isEmpty);
    });
  });

  group('清空与分页', () {
    test('清空当前页可以撤销', () {
      drawLine(ink, 0, 0, 10, 10);
      drawLine(ink, 0, 20, 10, 30);

      ink.clearPage(0);
      expect(ink.hasInk, isFalse);
      ink.undo();
      expect(ink.pages.single.strokes, hasLength(2));
    });

    test('空页上清空不算提交', () {
      ink.clearPage(0);
      expect(commits, 0);
    });

    test('追加页面，最多 20 页', () {
      for (var i = 0; i < 25; i++) {
        ink.addPage();
      }
      expect(ink.pages, hasLength(20));
      expect(ink.canAddPage, isFalse);
    });

    test('在不同页上书写互不影响', () {
      ink.addPage();
      drawLine(ink, 0, 0, 10, 10, page: 1);
      expect(ink.pages[0].strokes, isEmpty);
      expect(ink.pages[1].strokes, hasLength(1));
    });

    test('页面尺寸默认 1000 × 1400（页面逻辑坐标）', () {
      expect(ink.pages.single.width, InkController.pageWidth);
      expect(ink.pages.single.height, InkController.pageHeight);
    });
  });

  group('与契约互转', () {
    test('序列化后再读回，内容一致', () {
      ink.color = '#1D4ED8';
      drawLine(ink, 10, 20, 30, 40);
      ink.addPage();
      drawLine(ink, 5, 6, 7, 8, page: 1);

      final doc = ink.toContract();
      final restored = InkController()
        ..loadContract(
          StrokeDoc.fromJson(
            jsonDecode(jsonEncode(doc.toJson())) as Map<String, dynamic>,
          ),
        );

      expect(restored.pages, hasLength(2));
      expect(restored.pages[0].strokes.single.color, '#1D4ED8');
      expect(
        restored.pages[0].strokes.single.points,
        ink.pages[0].strokes.single.points,
      );
      expect(restored.pages[1].strokes.single.points[0], 5);
      expect(restored.canUndo, isFalse, reason: '读回来的内容不带历史');
    });

    test('生成的文档满足契约：版本 1、页面尺寸为正、颜色是 #RRGGBB、粗细在 0.5–24', () {
      drawLine(ink, 0, 0, 10, 10);
      final json = ink.toContract().toJson();

      expect(json['version'], 1);
      final page = (json['pages'] as List).single as Map<String, dynamic>;
      expect(page['width'], greaterThan(0));
      expect(page['height'], greaterThan(0));
      final stroke = (page['strokes'] as List).single as Map<String, dynamic>;
      expect(
        RegExp(r'^#[0-9A-Fa-f]{6}$').hasMatch(stroke['color'] as String),
        isTrue,
      );
      expect(stroke['width'], inInclusiveRange(0.5, 24));
      expect((stroke['points'] as List).length % 4, 0);
    });

    test('读入空文档得到一张空白页', () {
      ink.loadContract(null);
      expect(ink.pages, hasLength(1));
      expect(ink.hasInk, isFalse);
    });

    test('读入时丢弃不合规的笔画，而不是让界面崩溃', () {
      final doc = StrokeDoc(
        version: 1,
        pages: [
          StrokePage(
            width: 1000,
            height: 1400,
            strokes: [
              const Stroke(color: 'red', width: 2, points: [1, 2, 3, 0.5]),
              const Stroke(color: '#000000', width: 2, points: [1, 2, 3]),
              const Stroke(color: '#000000', width: 2, points: [1, 2, 3, 0.5]),
            ],
          ),
        ],
      );
      ink.loadContract(doc);
      expect(ink.pages.single.strokes, hasLength(1));
    });

    test('读入会替换现有内容并清空历史', () {
      drawLine(ink, 0, 0, 10, 10);
      ink.loadContract(null);
      expect(ink.hasInk, isFalse);
      expect(ink.canUndo, isFalse);
    });
  });
}
