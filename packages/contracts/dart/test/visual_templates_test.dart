import 'dart:convert';
import 'dart:io';

import 'package:test/test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

void main() {
  test('模板表与 packages/visual_templates/registry.json 一致', () {
    final registry = jsonDecode(
            File('../../visual_templates/registry.json').readAsStringSync())
        as Map<String, dynamic>;
    final templates = registry['templates'] as Map<String, dynamic>;
    expect(visualTemplates.keys.toSet(), templates.keys.toSet());
    expect(visualTemplates.keys.toSet(), {
      'quadratic_graph',
      'rectangle_area',
      'number_line',
      'force_diagram',
      'motion_chart',
      'chemical_flow',
    });
    for (final entry in templates.entries) {
      final spec = visualTemplates[entry.key]!;
      final params =
          (entry.value as Map<String, dynamic>)['params'] as List<dynamic>;
      expect(spec.params.map((p) => p.name),
          params.map((p) => (p as Map)['name']));
      expect(spec.staticFallback, (entry.value as Map)['static_fallback']);
      for (var i = 0; i < params.length; i++) {
        final json = params[i] as Map<String, dynamic>;
        expect(spec.params[i].min, (json['min'] as num).toDouble());
        expect(spec.params[i].max, (json['max'] as num).toDouble());
        expect(
            spec.params[i].defaultValue, (json['default'] as num).toDouble());
        expect(spec.params[i].integer, json['integer']);
        expect(spec.params[i].adjustable, json['adjustable']);
      }
    }
  });

  group('normalize', () {
    final quadratic = visualTemplates['quadratic_graph']!;

    test('没给的参数用默认值，按注册顺序返回', () {
      expect(
          quadratic
              .normalize({'a': 2})
              .entries
              .map((e) => '${e.key}=${e.value}'),
          ['a=2.0', 'b=0.0', 'c=0.0']);
    });

    test('越界的收进边界', () {
      expect(quadratic.normalize({'a': 99, 'b': -99})['a'], 5);
      expect(quadratic.normalize({'a': 99, 'b': -99})['b'], -10);
    });

    test('不认识的参数丢弃', () {
      expect(quadratic.normalize({'zoom': 3}).containsKey('zoom'), isFalse);
    });

    test('NaN 与无穷退回默认值', () {
      expect(quadratic.normalize({'a': double.nan})['a'], 1);
      expect(quadratic.normalize({'a': double.infinity})['a'], 1);
    });

    test('整数参数取整', () {
      final flow = visualTemplates['chemical_flow']!;
      expect(flow.normalize({'coef_a': 2.6})['coef_a'], 3);
    });
  });
}
