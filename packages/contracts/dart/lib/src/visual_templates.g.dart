// GENERATED CODE - DO NOT MODIFY BY HAND
// 由 tools/gen_dart_contracts.py 根据 packages/visual_templates/registry.json 生成。要改动请改契约后重新生成。
// dart format off
// ignore_for_file: type=lint

/// 图解模板的一个数值参数及其边界。
class VisualParamSpec {
  const VisualParamSpec({
    required this.name,
    required this.label,
    required this.min,
    required this.max,
    required this.step,
    required this.defaultValue,
    required this.integer,
    required this.adjustable,
  });

  final String name;
  final String label;
  final double min;
  final double max;
  final double step;
  final double defaultValue;
  final bool integer;
  final bool adjustable;

  /// 把任意输入收进边界；不是有限数时退回默认值。
  double clamp(double? value) {
    if (value == null || value.isNaN || value.isInfinite) return defaultValue;
    final bounded = value < min ? min : (value > max ? max : value);
    return integer ? bounded.roundToDouble() : bounded;
  }
}

/// 一个注册过的图解模板。渲染器只认这里列出的模板和参数。
class VisualTemplateSpec {
  const VisualTemplateSpec({
    required this.id,
    required this.title,
    required this.summary,
    required this.staticFallback,
    required this.params,
  });

  final String id;
  final String title;
  final String summary;
  final String staticFallback;
  final List<VisualParamSpec> params;

  /// 按注册顺序补齐参数：没给的用默认值，越界的收进边界，不认识的丢弃。
  Map<String, double> normalize(Map<String, double> input) => {
        for (final param in params) param.name: param.clamp(input[param.name]),
      };
}

/// 图解模板白名单（docs/06 §6）。不在表里的 template_id 一律显示静态说明。
const Map<String, VisualTemplateSpec> visualTemplates = {
  'quadratic_graph': VisualTemplateSpec(
    id: 'quadratic_graph',
    title: '二次函数图像',
    summary: 'y = ax² + bx + c 的开口方向、对称轴、顶点与单调区间。',
    staticFallback: '二次函数 y = ax² + bx + c 的对称轴是 x = -b/(2a)。a > 0 时开口向上，对称轴左侧递减、右侧递增；a < 0 时相反。',
    params: [
      VisualParamSpec(name: 'a', label: '二次项系数 a', min: -5.0, max: 5.0, step: 0.1, defaultValue: 1.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'b', label: '一次项系数 b', min: -10.0, max: 10.0, step: 0.1, defaultValue: 0.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'c', label: '常数项 c', min: -10.0, max: 10.0, step: 0.1, defaultValue: 0.0, integer: false, adjustable: true),
    ],
  ),
  'rectangle_area': VisualTemplateSpec(
    id: 'rectangle_area',
    title: '和为定值的矩形面积',
    summary: '两边之和固定时，拖动分配比例观察面积何时最大，对应基本不等式的取等条件。',
    staticFallback: '两个正数的和固定为 S 时，积 xy ≤ (S/2)²，当且仅当 x = y = S/2 时取等号；对应的矩形是正方形。',
    params: [
      VisualParamSpec(name: 'sum', label: '两边之和 S', min: 2.0, max: 40.0, step: 1.0, defaultValue: 10.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'split', label: 'x 占 S 的比例', min: 0.05, max: 0.95, step: 0.01, defaultValue: 0.3, integer: false, adjustable: true),
    ],
  ),
  'number_line': VisualTemplateSpec(
    id: 'number_line',
    title: '数轴上的区间',
    summary: '在数轴上标出一个区间，区分端点的开闭与无穷方向。',
    staticFallback: '实心点表示端点包含在区间内，空心点表示不包含；箭头表示向该方向无限延伸。',
    params: [
      VisualParamSpec(name: 'min', label: '数轴左端', min: -20.0, max: 20.0, step: 1.0, defaultValue: -5.0, integer: false, adjustable: false),
      VisualParamSpec(name: 'max', label: '数轴右端', min: -20.0, max: 20.0, step: 1.0, defaultValue: 5.0, integer: false, adjustable: false),
      VisualParamSpec(name: 'left', label: '区间左端点', min: -20.0, max: 20.0, step: 0.5, defaultValue: -1.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'right', label: '区间右端点', min: -20.0, max: 20.0, step: 0.5, defaultValue: 3.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'left_closed', label: '左端点闭', min: 0.0, max: 1.0, step: 1.0, defaultValue: 1.0, integer: true, adjustable: true),
      VisualParamSpec(name: 'right_closed', label: '右端点闭', min: 0.0, max: 1.0, step: 1.0, defaultValue: 0.0, integer: true, adjustable: true),
      VisualParamSpec(name: 'left_unbounded', label: '向左无限延伸', min: 0.0, max: 1.0, step: 1.0, defaultValue: 0.0, integer: true, adjustable: true),
      VisualParamSpec(name: 'right_unbounded', label: '向右无限延伸', min: 0.0, max: 1.0, step: 1.0, defaultValue: 0.0, integer: true, adjustable: true),
    ],
  ),
  'force_diagram': VisualTemplateSpec(
    id: 'force_diagram',
    title: '斜面上物块的受力',
    summary: '斜面上物块的重力、支持力、摩擦力，以及重力沿斜面和垂直斜面的分解。',
    staticFallback: '把重力分解为沿斜面向下的 mg·sinθ 和垂直斜面的 mg·cosθ；支持力 N = mg·cosθ。当 mg·sinθ 不超过最大静摩擦力时物块静止，否则沿斜面加速下滑，a = g(sinθ − μcosθ)。',
    params: [
      VisualParamSpec(name: 'angle_deg', label: '倾角 θ（度）', min: 0.0, max: 60.0, step: 1.0, defaultValue: 30.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'mass', label: '质量 m（kg）', min: 0.5, max: 20.0, step: 0.5, defaultValue: 2.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'mu', label: '动摩擦因数 μ', min: 0.0, max: 1.0, step: 0.05, defaultValue: 0.2, integer: false, adjustable: true),
      VisualParamSpec(name: 'g', label: '重力加速度 g（m/s²）', min: 9.8, max: 10.0, step: 0.2, defaultValue: 9.8, integer: false, adjustable: true),
    ],
  ),
  'motion_chart': VisualTemplateSpec(
    id: 'motion_chart',
    title: '匀变速直线运动的 v–t 图',
    summary: '速度随时间的直线、斜率表示的加速度，以及图线与时间轴围成的面积表示的位移。',
    staticFallback: '匀变速直线运动 v = v₀ + at，v–t 图是一条直线，斜率等于加速度；图线与时间轴围成的面积等于位移 x = v₀t + ½at²。',
    params: [
      VisualParamSpec(name: 'v0', label: '初速度 v₀（m/s）', min: -20.0, max: 20.0, step: 0.5, defaultValue: 0.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'a', label: '加速度 a（m/s²）', min: -10.0, max: 10.0, step: 0.5, defaultValue: 2.0, integer: false, adjustable: true),
      VisualParamSpec(name: 't_max', label: '时间 t（s）', min: 1.0, max: 20.0, step: 1.0, defaultValue: 5.0, integer: false, adjustable: true),
    ],
  ),
  'chemical_flow': VisualTemplateSpec(
    id: 'chemical_flow',
    title: '化学计量的换算流程',
    summary: '已知物质量 → 物质的量 → 按化学计量数之比换算 → 所求物质量。',
    staticFallback: '先用 n = m / M 把已知物的质量换成物质的量，再按方程式中的化学计量数之比得到所求物的物质的量，最后用 m = n·M 换回质量。',
    params: [
      VisualParamSpec(name: 'mass_a', label: '已知物质量 m(A)（g）', min: 0.1, max: 500.0, step: 0.1, defaultValue: 10.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'molar_mass_a', label: '已知物摩尔质量 M(A)（g/mol）', min: 1.0, max: 400.0, step: 0.5, defaultValue: 100.0, integer: false, adjustable: true),
      VisualParamSpec(name: 'coef_a', label: '已知物计量数', min: 1.0, max: 10.0, step: 1.0, defaultValue: 1.0, integer: true, adjustable: true),
      VisualParamSpec(name: 'coef_b', label: '所求物计量数', min: 1.0, max: 10.0, step: 1.0, defaultValue: 1.0, integer: true, adjustable: true),
      VisualParamSpec(name: 'molar_mass_b', label: '所求物摩尔质量 M(B)（g/mol）', min: 1.0, max: 400.0, step: 0.5, defaultValue: 44.0, integer: false, adjustable: true),
    ],
  ),
};
