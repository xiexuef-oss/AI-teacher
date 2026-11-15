import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/theme.dart';
import 'package:tutor_student/features/visual/painters.dart';
import 'package:tutor_student/features/visual/visual_view.dart';

Widget host(
  Widget child, {
  double width = 700,
  Brightness brightness = Brightness.light,
}) => MaterialApp(
  theme: brightness == Brightness.light ? AppTheme.light() : AppTheme.dark(),
  home: Scaffold(
    body: Center(
      child: SizedBox(
        width: width,
        child: SingleChildScrollView(child: child),
      ),
    ),
  ),
);

void paintOnce(CustomPainter painter, {Size size = const Size(480, 270)}) {
  final recorder = ui.PictureRecorder();
  painter.paint(Canvas(recorder), size);
  recorder.endRecording().dispose();
}

void main() {
  final palette = VisualPalette.of(
    ColorScheme.fromSeed(seedColor: AppTheme.seed),
  );

  group('VisualView', () {
    testWidgets('带着服务端给的参数显示，并给出每个可调参数的滑块', (tester) async {
      await tester.pumpWidget(
        host(
          const VisualView(
            templateId: 'quadratic_graph',
            params: {'a': 2, 'b': -4, 'c': 1},
            caption: '拖动 a 观察开口。',
          ),
        ),
      );

      expect(find.text('二次函数图像'), findsOneWidget);
      for (final name in ['a', 'b', 'c']) {
        expect(find.byKey(ValueKey('visual.slider.$name')), findsOneWidget);
      }
      expect(find.text('2'), findsOneWidget, reason: 'a 的当前值');
      expect(find.text('拖动 a 观察开口。'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('拖动滑块后图形的参数跟着变，点"重置"回到初始值', (tester) async {
      await tester.pumpWidget(
        host(
          const VisualView(
            templateId: 'quadratic_graph',
            params: {'a': 1, 'b': 0, 'c': 0},
          ),
        ),
      );
      Slider slider() =>
          tester.widget<Slider>(find.byKey(const ValueKey('visual.slider.a')));
      expect(slider().value, 1);

      await tester.drag(
        find.byKey(const ValueKey('visual.slider.a')),
        const Offset(150, 0),
      );
      await tester.pump();
      expect(slider().value, greaterThan(1));

      await tester.tap(find.byKey(const ValueKey('visual.reset')));
      await tester.pump();
      expect(slider().value, 1);
    });

    testWidgets('超出边界的参数被收进边界，缺的参数用默认值', (tester) async {
      await tester.pumpWidget(
        host(
          const VisualView(templateId: 'quadratic_graph', params: {'a': 99}),
        ),
      );

      expect(
        tester
            .widget<Slider>(find.byKey(const ValueKey('visual.slider.a')))
            .value,
        5,
      );
      expect(
        tester
            .widget<Slider>(find.byKey(const ValueKey('visual.slider.b')))
            .value,
        0,
      );
    });

    testWidgets('不认识的模板：显示文字说明，不白屏、没有滑块', (tester) async {
      await tester.pumpWidget(
        host(
          const VisualView(
            templateId: 'hologram_3d',
            params: {'a': 1},
            caption: '看这张图',
            staticFallback: '审核过的文字说明：开口向上，对称轴 x=1。',
          ),
        ),
      );

      expect(find.byKey(const ValueKey('visual.fallback')), findsOneWidget);
      expect(find.text('审核过的文字说明：开口向上，对称轴 x=1。'), findsOneWidget);
      expect(find.byType(Slider), findsNothing);
      expect(
        find
            .byType(CustomPaint)
            .evaluate()
            .where((e) => e.widget.key == const ValueKey('visual.canvas')),
        isEmpty,
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('不认识的模板又没有文字说明时也有兜底', (tester) async {
      await tester.pumpWidget(
        host(const VisualView(templateId: 'hologram_3d')),
      );
      expect(find.text('（没有可显示的文字说明）'), findsOneWidget);
    });

    testWidgets('0/1 的参数用开关：数轴的端点开闭', (tester) async {
      await tester.pumpWidget(
        host(
          const VisualView(
            templateId: 'number_line',
            params: {
              'left': -1,
              'right': 3,
              'left_closed': 1,
              'right_closed': 0,
            },
          ),
        ),
      );
      final handle = tester.ensureSemantics();

      expect(
        find.byKey(const ValueKey('visual.switch.right_closed')),
        findsOneWidget,
      );
      expect(
        find.bySemanticsLabel(RegExp(r'数轴上标出的区间 \[-1, 3\)')),
        findsOneWidget,
      );

      await tester.tap(
        find.byKey(const ValueKey('visual.switch.right_closed')),
      );
      await tester.pump();
      expect(
        find.bySemanticsLabel(RegExp(r'数轴上标出的区间 \[-1, 3\]')),
        findsOneWidget,
      );
      handle.dispose();
    });

    testWidgets('读屏用户能拿到图的文字摘要', (tester) async {
      await tester.pumpWidget(
        host(
          const VisualView(
            templateId: 'motion_chart',
            params: {'v0': 2, 'a': 3, 't_max': 4},
          ),
        ),
      );
      final handle = tester.ensureSemantics();
      expect(find.bySemanticsLabel(RegExp(r'位移 32 米')), findsOneWidget);
      handle.dispose();
    });

    testWidgets('文字说明默认折叠，点开能看到', (tester) async {
      await tester.pumpWidget(
        host(const VisualView(templateId: 'force_diagram')),
      );
      expect(find.textContaining('mg·sinθ'), findsNothing);
      await tester.tap(find.byKey(const ValueKey('visual.text')));
      await tester.pumpAndSettle();
      expect(find.textContaining('mg·sinθ'), findsOneWidget);
    });

    for (final brightness in Brightness.values) {
      testWidgets('六个模板在${brightness.name}主题下都能画出来', (tester) async {
        for (final id in visualTemplates.keys) {
          await tester.pumpWidget(
            host(VisualView(templateId: id), brightness: brightness),
          );
          expect(
            find.byKey(const ValueKey('visual.canvas')),
            findsOneWidget,
            reason: id,
          );
          expect(tester.takeException(), isNull, reason: id);
        }
      });
    }

    testWidgets('窄面板（手机宽度）也不溢出', (tester) async {
      for (final id in visualTemplates.keys) {
        await tester.pumpWidget(host(VisualView(templateId: id), width: 320));
        expect(tester.takeException(), isNull, reason: id);
      }
    });

    testWidgets('字体放大到 1.5 倍不溢出', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: const TextScaler.linear(1.5)),
            child: child!,
          ),
          home: const Scaffold(
            body: SingleChildScrollView(
              child: VisualView(templateId: 'quadratic_graph'),
            ),
          ),
        ),
      );
      expect(tester.takeException(), isNull);
    });
  });

  group('painters：任何合法参数都不抛异常', () {
    Map<String, double> at(
      VisualTemplateSpec spec,
      double Function(VisualParamSpec) pick,
    ) => {for (final p in spec.params) p.name: pick(p)};

    for (final spec in visualTemplates.values) {
      test('${spec.id}：默认值、全最小、全最大', () {
        for (final pick in <double Function(VisualParamSpec)>[
          (p) => p.defaultValue,
          (p) => p.min,
          (p) => p.max,
        ]) {
          paintOnce(painterFor(spec.id, at(spec, pick), palette));
        }
      });

      test('${spec.id}：很小的画布也不抛异常', () {
        paintOnce(
          painterFor(spec.id, spec.normalize({}), palette),
          size: const Size(120, 70),
        );
      });
    }

    test('二次函数 a=0（退化成直线）', () {
      paintOnce(
        painterFor('quadratic_graph', {'a': 0, 'b': 3, 'c': -2}, palette),
      );
      paintOnce(
        painterFor('quadratic_graph', {'a': 0, 'b': 0, 'c': 0}, palette),
      );
    });

    test('数轴：左端点大于右端点、两端无限、端点在轴外', () {
      final base = visualTemplates['number_line']!.normalize({});
      paintOnce(
        painterFor('number_line', {...base, 'left': 4, 'right': -3}, palette),
      );
      paintOnce(
        painterFor('number_line', {
          ...base,
          'left_unbounded': 1,
          'right_unbounded': 1,
        }, palette),
      );
      paintOnce(
        painterFor('number_line', {...base, 'left': -20, 'right': 20}, palette),
      );
    });

    test('斜面：倾角 0、摩擦因数 1', () {
      final base = visualTemplates['force_diagram']!.normalize({});
      paintOnce(
        painterFor('force_diagram', {...base, 'angle_deg': 0}, palette),
      );
      paintOnce(
        painterFor('force_diagram', {
          ...base,
          'angle_deg': 60,
          'mu': 1,
        }, palette),
      );
    });

    test('v–t 图：加速度为 0、减速到反向', () {
      final base = visualTemplates['motion_chart']!.normalize({});
      paintOnce(painterFor('motion_chart', {...base, 'a': 0}, palette));
      paintOnce(
        painterFor('motion_chart', {
          ...base,
          'v0': 8,
          'a': -5,
          't_max': 10,
        }, palette),
      );
    });

    test('没有注册的模板直接报错，不会悄悄画个空图', () {
      expect(() => painterFor('free_canvas', {}, palette), throwsArgumentError);
    });
  });

  group('刻度间隔', () {
    test('大约 4–7 个刻度', () {
      for (final span in [0.5, 3, 12, 40, 250, 1300]) {
        final count = span / niceStep(span.toDouble());
        expect(count, inInclusiveRange(2.5, 10), reason: 'span=$span');
      }
    });

    test('非法跨度退回 1', () {
      expect(niceStep(0), 1);
      expect(niceStep(double.nan), 1);
      expect(niceStep(-3), 1);
    });
  });
}
