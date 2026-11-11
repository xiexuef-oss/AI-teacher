import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/core/math_text.dart';
import 'package:tutor_student/core/widgets.dart';

void main() {
  group('splitMath', () {
    test('普通文字和行内公式交替', () {
      final parts = splitMath(r'已知 $x>0$，则 $x+\dfrac{4}{x}$ 的最小值为');
      expect(parts.map((s) => (s.isMath, s.text)), [
        (false, '已知 '),
        (true, 'x>0'),
        (false, '，则 '),
        (true, r'x+\dfrac{4}{x}'),
        (false, ' 的最小值为'),
      ]);
    });

    test('没有公式时整段都是文字', () {
      expect(splitMath('只有文字').map((s) => s.isMath), [false]);
      expect(splitMath(''), isEmpty);
    });

    test('不配对的 \$ 当作普通文字', () {
      final parts = splitMath(r'价格是 $5 元');
      expect(parts.every((s) => !s.isMath), isTrue);
      expect(parts.map((s) => s.text).join(), r'价格是 $5 元');
    });

    test('公式在开头或结尾', () {
      expect(splitMath(r'$a$').map((s) => (s.isMath, s.text)), [(true, 'a')]);
      expect(splitMath(r'$a$ 和 $b$').length, 3);
    });
  });

  group('MathText', () {
    Widget host(Widget child, {double width = 400, double scale = 1}) =>
        MaterialApp(
          home: Scaffold(
            body: MediaQuery(
              data: MediaQueryData(textScaler: TextScaler.linear(scale)),
              child: SizedBox(width: width, child: child),
            ),
          ),
        );

    testWidgets('含公式的文字渲染出公式部件', (tester) async {
      await tester.pumpWidget(
        host(const MathText(r'函数 $f(x)=x^2-2x-3$ 的单调递增区间')),
      );
      expect(find.byType(Math), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('没有公式时就是普通 Text', (tester) async {
      await tester.pumpWidget(host(const MathText('只有文字')));
      expect(find.byType(Math), findsNothing);
      expect(find.text('只有文字'), findsOneWidget);
    });

    testWidgets('解析不了的公式：原样显示源码，不抛异常、不白屏', (tester) async {
      await tester.pumpWidget(
        host(const MathText(r'坏公式 $\notacommand{x}$ 后面')),
      );
      expect(tester.takeException(), isNull);
      expect(find.textContaining('notacommand'), findsOneWidget);
    });

    testWidgets('放大字体：普通文字和公式一起放大，比例一致', (tester) async {
      Future<double> widthAt(double scale) async {
        await tester.pumpWidget(
          host(
            const Align(
              alignment: Alignment.topLeft,
              child: MathText(
                r'文字文字文字文字 $x^2+1$ 文字文字文字文字',
                style: TextStyle(fontSize: 20),
              ),
            ),
            width: 900,
            scale: scale,
          ),
        );
        return tester.getSize(find.byType(MathText)).width;
      }

      final normal = await widthAt(1.0);
      final large = await widthAt(1.5);
      // 只放大公式、不放大旁边的文字时，比值会明显小于 1.5
      expect(large / normal, closeTo(1.5, 0.08));
    });

    testWidgets('窄屏 + 放大字体：比可用宽度还宽的公式等比缩小，不溢出', (tester) async {
      await tester.pumpWidget(
        host(
          const MathText(
            r'$a_1+a_2+a_3+a_4+a_5+a_6+a_7+a_8+a_9+a_{10}+a_{11}+a_{12}+a_{13}+a_{14}$',
            style: TextStyle(fontSize: 22),
          ),
          width: 220,
          scale: 1.5,
        ),
      );
      expect(tester.takeException(), isNull);
      expect(
        tester.getSize(find.byType(MathText)).width,
        lessThanOrEqualTo(220),
      );
    });
  });

  group('InfoChip 里的公式', () {
    Widget host(Widget child) => MaterialApp(
      home: Scaffold(body: SizedBox(width: 400, child: child)),
    );

    testWidgets('标签里的行内公式也要渲染（浏览器联调发现过显示源码）', (tester) async {
      await tester.pumpWidget(
        host(const InfoChip(r'配方或用 $x=-\dfrac{b}{2a}$ 求对称轴')),
      );
      expect(find.byType(Math), findsOneWidget);
      expect(find.textContaining(r'\dfrac'), findsNothing);
      expect(find.textContaining(r'$'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('普通标签不变：还是一个 Text', (tester) async {
      await tester.pumpWidget(host(const InfoChip('四川')));
      expect(find.byType(Math), findsNothing);
      expect(find.text('四川'), findsOneWidget);
    });
  });

  test('解析检查不是摆设：不认识的命令、没闭合的括号都会被识别出来', () {
    expect(canRenderTex(r'\dfrac{a}{b}'), isTrue);
    expect(canRenderTex(r'\notacommand{x}'), isFalse);
    expect(canRenderTex(r'\frac{a}{'), isFalse);
  });

  test('样题里出现的每一段 LaTeX，渲染器都能解析（否则学生会看到源码）', () {
    final file = File('test/fixtures/math_snippets.json');
    expect(
      file.existsSync(),
      isTrue,
      reason: '先运行 uv run python tools/export_dart_fixtures.py',
    );
    final snippets = (jsonDecode(file.readAsStringSync()) as List<dynamic>)
        .cast<String>();

    expect(snippets.length, greaterThan(50));
    final failed = [
      for (final s in snippets)
        if (!canRenderTex(s)) s,
    ];
    expect(failed, isEmpty, reason: '这些公式渲染器解析不了：\n${failed.join('\n')}');
  });
}
