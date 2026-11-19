import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/features/visual/visual_math.dart';

void main() {
  test('圆示意只定位圆心和圆上不同两点，不输出推导关系', () {
    for (final a in [.05, .1, .2]) {
      for (final b in [.3, .4, .45]) {
        final layout = circleOf({'a_position': a, 'b_position': b});
        expect(layout.points.first, (0.0, 0.0));
        expect(layout.points[1], isNot(layout.points[2]));
        for (final point in layout.points.skip(1)) {
          expect(point.$1 * point.$1 + point.$2 * point.$2, closeTo(1, 1e-12));
        }
        expect(layout.description, contains('非按比例'));
        expect(layout.description, isNot(contains('OA=OB')));
      }
    }
    expect(circleOf({'focus': 3}).description, contains('当前焦点：B'));
  });
  test('固定工艺拓扑只按配置显示支路回流', () {
    final plain = processOf({});
    expect(plain.nodes, ['原料', '处理Ⅰ', '分离', '处理Ⅱ', '产物']);
    expect(plain.edges.length, 4);
    final all = processOf({'branch': 1, 'recycle': 1, 'focus': 2});
    expect(all.edges, containsAll([(2, 5), (3, 1)]));
    expect(all.focus, 2);
    expect(all.description, contains('分离到支路'));
    expect(all.description, contains('处理Ⅱ回到处理Ⅰ'));
  });
  test('三角形仅保存给定坐标与顶点焦点，不生成构造或结论', () {
    for (final x in [.2, .35, .8]) {
      for (final y in [.3, .65, .9]) {
        final triangle = triangleOf({'apex_x': x, 'height': y});
        expect(triangle.apexX, x);
        expect(triangle.height, y);
        expect(triangle.description, contains('不能凭外观推断'));
        expect(triangle.description, isNot(contains('面积')));
      }
    }
  });
  group('二次函数', () {
    test('a=1, b=-2, c=-3：对称轴 x=1，顶点 (1, -4)，开口向上', () {
      final q = quadraticOf({'a': 1, 'b': -2, 'c': -3});
      expect(q.axisX, 1);
      expect(q.vertexY, -4);
      expect(q.opensUp, isTrue);
      expect(q.y(0), -3);
    });

    test('a=-1, b=4, c=1：对称轴 x=2，顶点 (2, 5)，开口向下', () {
      final q = quadraticOf({'a': -1, 'b': 4, 'c': 1});
      expect(q.axisX, 2);
      expect(q.vertexY, 5);
      expect(q.opensUp, isFalse);
    });

    test('a=0 时退化成一次函数，没有对称轴和顶点', () {
      final q = quadraticOf({'a': 0, 'b': 2, 'c': 1});
      expect(q.axisX, isNull);
      expect(q.vertexY, isNull);
      expect(q.y(3), 7);
    });

    test('递增区间描述：开口向上时在对称轴右侧', () {
      expect(
        quadraticOf({'a': 1, 'b': -2, 'c': -3}).increasingText,
        '递增区间 [1, +∞)',
      );
      expect(
        quadraticOf({'a': -1, 'b': 4, 'c': 1}).increasingText,
        '递增区间 (-∞, 2]',
      );
    });

    test('区间标签的位置：开口向下时顶点在最高处，标签让到下沿，免得和顶点标签叠在一起', () {
      expect(quadraticOf({'a': 1, 'b': -2, 'c': -3}).bandLabelsOnTop, isTrue);
      expect(quadraticOf({'a': -1, 'b': 4, 'c': 1}).bandLabelsOnTop, isFalse);
      // 一次函数没有顶点标签，位置不变
      expect(quadraticOf({'a': 0, 'b': 2, 'c': 1}).bandLabelsOnTop, isTrue);
    });
  });

  group('和为定值的矩形', () {
    test('S=10, 比例 0.3：边长 3 和 7，面积 21，还不是正方形', () {
      final r = rectangleOf({'sum': 10, 'split': 0.3});
      expect((r.x, r.y, r.area), (3, 7, 21));
      expect(r.isSquare, isFalse);
      expect(r.maxArea, 25);
    });

    test('比例 0.5：正方形，面积取到最大值', () {
      final r = rectangleOf({'sum': 10, 'split': 0.5});
      expect(r.area, 25);
      expect(r.isSquare, isTrue);
    });
  });

  group('斜面受力', () {
    test('光滑斜面（μ=0）θ=30°, m=2, g=10：沿斜面分力 10 N，加速度 5 m/s²', () {
      final f = forcesOf({'angle_deg': 30, 'mass': 2, 'mu': 0, 'g': 10});
      expect(f.weight, 20);
      expect(f.alongSlope, closeTo(10, 1e-9));
      expect(f.normal, closeTo(20 * math.cos(math.pi / 6), 1e-9));
      expect(f.sliding, isTrue);
      expect(f.acceleration, closeTo(5, 1e-9));
      expect(f.friction, 0);
    });

    test('摩擦因数够大时物块静止：静摩擦力等于沿斜面分力，加速度为 0', () {
      final f = forcesOf({'angle_deg': 30, 'mass': 2, 'mu': 0.8, 'g': 10});
      expect(f.sliding, isFalse);
      expect(f.friction, closeTo(10, 1e-9));
      expect(f.acceleration, 0);
    });

    test('下滑时 a = g(sinθ − μcosθ)', () {
      final f = forcesOf({'angle_deg': 45, 'mass': 1, 'mu': 0.2, 'g': 10});
      final expected =
          10 * (math.sin(math.pi / 4) - 0.2 * math.cos(math.pi / 4));
      expect(f.sliding, isTrue);
      expect(f.acceleration, closeTo(expected, 1e-9));
      expect(f.friction, closeTo(0.2 * f.normal, 1e-9));
    });

    test('倾角 0：水平面，不会下滑', () {
      final f = forcesOf({'angle_deg': 0, 'mass': 1, 'mu': 0, 'g': 10});
      expect(f.alongSlope, closeTo(0, 1e-12));
      expect(f.sliding, isFalse);
    });
  });

  group('匀变速直线运动', () {
    test('v0=2, a=3, t=4：末速度 14，位移 32（与样题一致）', () {
      final m = motionOf({'v0': 2, 'a': 3, 't_max': 4});
      expect(m.endVelocity, 14);
      expect(m.displacement, 32);
    });

    test('减速到停下再反向时，位移是图线下的代数面积', () {
      final m = motionOf({'v0': 4, 'a': -2, 't_max': 4});
      expect(m.endVelocity, -4);
      expect(m.displacement, 0);
      expect(m.stopTime, 2);
    });

    test('加速度为 0 时没有停下的时刻', () {
      expect(motionOf({'v0': 3, 'a': 0, 't_max': 5}).stopTime, isNull);
    });
  });

  group('化学计量换算', () {
    test('10 g CaCO3 → CO2：n=0.1 mol，m=4.4 g（与样题一致）', () {
      final f = flowOf({
        'mass_a': 10,
        'molar_mass_a': 100,
        'coef_a': 1,
        'coef_b': 1,
        'molar_mass_b': 44,
      });
      expect(f.molesA, closeTo(0.1, 1e-12));
      expect(f.molesB, closeTo(0.1, 1e-12));
      expect(f.massB, closeTo(4.4, 1e-12));
    });

    test('计量数之比不是 1:1 时按比例换算', () {
      final f = flowOf({
        'mass_a': 4,
        'molar_mass_a': 2,
        'coef_a': 2,
        'coef_b': 1,
        'molar_mass_b': 32,
      });
      expect(f.molesA, 2);
      expect(f.molesB, 1);
      expect(f.massB, 32);
    });
  });

  group('数轴区间', () {
    Map<String, double> iv({
      double l = -1,
      double r = 3,
      double lc = 1,
      double rc = 0,
      double lu = 0,
      double ru = 0,
    }) => {
      'min': -5,
      'max': 5,
      'left': l,
      'right': r,
      'left_closed': lc,
      'right_closed': rc,
      'left_unbounded': lu,
      'right_unbounded': ru,
    };

    test('闭开区间', () => expect(intervalText(iv()), '[-1, 3)'));
    test('端点开闭互换', () => expect(intervalText(iv(lc: 0, rc: 1)), '(-1, 3]'));
    test(
      '向左无限延伸时端点写 -∞，并且总是圆括号',
      () => expect(intervalText(iv(lu: 1, lc: 1)), '(-∞, 3)'),
    );
    test('向右无限延伸', () => expect(intervalText(iv(ru: 1, rc: 1)), '[-1, +∞)'));
    test(
      '两端都无限：全体实数',
      () => expect(intervalText(iv(lu: 1, ru: 1)), '(-∞, +∞)'),
    );
    test('左端点大于右端点：空集', () => expect(intervalText(iv(l: 4, r: 1)), '空集'));
    test('小数端点保留一位', () => expect(intervalText(iv(l: 0.5, r: 2)), '[0.5, 2)'));
  });

  group('数字格式', () {
    test('去掉多余的 0', () {
      expect(fmt(5), '5');
      expect(fmt(4.4), '4.4');
      expect(fmt(4.40001), '4.4');
      expect(fmt(0.125), '0.13');
      expect(fmt(-0.001), '0');
      expect(fmt(double.nan), '—');
    });
  });
}
