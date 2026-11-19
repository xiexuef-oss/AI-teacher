import 'dart:async';
import 'dart:ui' as ui;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/features/solve/ink/ink_export_dialog.dart';
import 'package:tutor_student/features/solve/ink/ink_controller.dart';
import 'package:tutor_student/features/solve/ink/ink_painter.dart';

void main() {
  testWidgets('保存取消和失败可重试', (tester) async {
    var calls = 0;
    final ink = InkController();
    ink.beginStroke(0, 10, 20, t: 0, pressure: .5);
    ink.endStroke();
    final original = List<double>.of(ink.pages.single.strokes.single.points);
    await tester.pumpWidget(
      MaterialApp(
        home: InkExportDialog(
          generate: () async => Uint8List.fromList([1]),
          preview: false,
          save: (bytes) async {
            calls++;
            if (calls == 1) return '已取消保存';
            throw StateError('private');
          },
          share: (bytes, origin) async => '已取消分享',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('ink.export.save')));
    await tester.pumpAndSettle();
    expect(find.text('已取消保存'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('ink.export.save')));
    await tester.pumpAndSettle();
    expect(find.text('操作失败，请重试。当前草稿没有被清空。'), findsOneWidget);
    expect(find.textContaining('private'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('ink.export.share')));
    await tester.pumpAndSettle();
    expect(find.text('已取消分享'), findsOneWidget);
    expect(ink.pages.single.strokes.single.points, original);
    ink.dispose();
  });

  testWidgets('生成失败可重试，系统窗口打开期间阻止重复操作', (tester) async {
    final pending = Completer<String>();
    var attempts = 0;
    var saves = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: InkExportDialog(
          preview: false,
          generate: () async {
            if (++attempts == 1) throw StateError('encode');
            return Uint8List(1);
          },
          save: (_) {
            saves++;
            return pending.future;
          },
          share: (_, origin) async => 'shared',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('图片生成失败，请重试。当前草稿没有被清空。'), findsOneWidget);
    await tester.tap(find.text('重试生成'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('ink.export.save')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('ink.export.save')));
    await tester.pump();
    expect(saves, 1);
    expect(
      tester
          .widget<TextButton>(find.byKey(const ValueKey('ink.export.share')))
          .onPressed,
      isNull,
    );
    pending.complete('文件已保存到你选择的位置。');
    await tester.pumpAndSettle();
    expect(find.text('文件已保存到你选择的位置。'), findsOneWidget);
  });
  test('拒绝空页、非法尺寸与超限长画布', () async {
    await expectLater(renderInkPng([]), throwsArgumentError);
    await expectLater(
      renderInkPng([InkPage(width: 1, height: 1)], pixelWidth: double.infinity),
      throwsArgumentError,
    );
    await expectLater(
      renderInkPng([InkPage(width: 1, height: 10000)]),
      throwsStateError,
    );
  });
  testWidgets('多页仍竖向拼接为有效PNG', (tester) async {
    await tester.runAsync(() async {
      final png = await renderInkPng([
        InkPage(width: 10, height: 20),
        InkPage(width: 10, height: 30),
      ], pixelWidth: 10);
      final codec = await ui.instantiateImageCodec(png);
      final frame = await codec.getNextFrame();
      expect(frame.image.width, 10);
      expect(frame.image.height, 50);
      frame.image.dispose();
      codec.dispose();
    });
  });

  testWidgets('20页导出保留所有页面并控制总像素和高度', (tester) async {
    await tester.runAsync(() async {
      final pages = List.generate(
        20,
        (_) => InkPage(width: 1000, height: 1400),
      );
      final width = inkExportWidth(pages);
      final height = (width * 28).round();
      expect(height, lessThanOrEqualTo(16000));
      expect(width.round() * height, lessThanOrEqualTo(24000000));
      expect(inkExportWidth(pages.take(2).toList()), 1200);
      final png = await renderInkPng(pages, pixelWidth: width);
      final codec = await ui.instantiateImageCodec(png);
      final frame = await codec.getNextFrame();
      expect(frame.image.height, height);
      expect(frame.image.width, width.round());
      frame.image.dispose();
      codec.dispose();
    });
  });
}
