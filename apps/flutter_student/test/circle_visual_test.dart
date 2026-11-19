import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/features/visual/painters.dart';
import 'package:tutor_student/features/visual/visual_view.dart';

import 'visual_view_test.dart' show host;

void main() {
  testWidgets(
    'rendered circle stays round, given points stay on its outline, no interior construction',
    (tester) async {
      await tester.runAsync(() async {
        const palette = VisualPalette(
          ink: Colors.black,
          muted: Colors.grey,
          grid: Colors.grey,
          curve: Colors.blue,
          accent: Colors.red,
          good: Colors.green,
          warn: Colors.orange,
          surface: Colors.white,
        );
        for (final focus in [2.0, 3.0]) {
          final recorder = ui.PictureRecorder();
          painterFor('circle_schematic', {'focus': focus}, palette)
              .paint(Canvas(recorder), const Size(300, 200));
          final picture = recorder.endRecording();
          final image = await picture.toImage(300, 200);
          final bytes = (await image.toByteData(
            format: ui.ImageByteFormat.rawRgba,
          ))!;
          List<Offset> pixels(Color color) {
            final argb = color.toARGB32();
            final result = <Offset>[];
            for (var y = 0; y < 200; y++) {
              for (var x = 0; x < 300; x++) {
                final i = (y * 300 + x) * 4;
                if (bytes.getUint8(i) == ((argb >> 16) & 255) &&
                    bytes.getUint8(i + 1) == ((argb >> 8) & 255) &&
                    bytes.getUint8(i + 2) == (argb & 255) &&
                    bytes.getUint8(i + 3) == 255) {
                  result.add(Offset(x + .5, y + .5));
                }
              }
            }
            return result;
          }

          final outline = pixels(palette.curve);
          final dot = pixels(palette.accent);
          expect(outline, isNotEmpty);
          expect(dot, isNotEmpty);
          final minX = outline.map((p) => p.dx).reduce(math.min);
          final maxX = outline.map((p) => p.dx).reduce(math.max);
          final minY = outline.map((p) => p.dy).reduce(math.min);
          final maxY = outline.map((p) => p.dy).reduce(math.max);
          expect(maxX - minX, closeTo(maxY - minY, 2));
          final center = Offset((minX + maxX) / 2, (minY + maxY) / 2);
          final radius = ((maxX - minX) + (maxY - minY)) / 4;
          final point =
              dot.fold(Offset.zero, (sum, p) => sum + p) /
              dot.length.toDouble();
          expect((point - center).distance, closeTo(radius, 2));
          expect(
            outline.every((p) => (p - center).distance >= radius - 3),
            isTrue,
          );
          image.dispose();
          picture.dispose();
        }
      });
    },
  );
  testWidgets('focus changes only the named point and can reset locally', (
    tester,
  ) async {
    await tester.pumpWidget(
      host(const VisualView(templateId: 'circle_schematic')),
    );
    final slider = find.byKey(const ValueKey('visual.slider.focus'));
    await tester.ensureVisible(slider);
    await tester.drag(slider, const Offset(160, 0));
    await tester.pumpAndSettle();
    expect(find.textContaining('当前焦点：整体'), findsNothing);
    final reset = find.byKey(const ValueKey('visual.reset'));
    await tester.ensureVisible(reset);
    await tester.tap(reset);
    await tester.pumpAndSettle();
    expect(find.textContaining('当前焦点：整体'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'circle keeps given point descriptions visible and layout controls private',
    (tester) async {
      await tester.pumpWidget(
        host(const VisualView(templateId: 'circle_schematic')),
      );
      expect(find.byKey(const ValueKey('visual.canvas')), findsOneWidget);
      expect(find.textContaining('O是圆心'), findsOneWidget);
      expect(find.textContaining('不能凭外观推断'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('visual.slider.a_position')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('visual.slider.b_position')),
        findsNothing,
      );
      expect(find.byKey(const ValueKey('visual.slider.focus')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('visual.text')));
      await tester.pumpAndSettle();
      expect(find.textContaining('不能凭外观推断'), findsNWidgets(2));
      expect(tester.takeException(), isNull);
    },
  );
}
