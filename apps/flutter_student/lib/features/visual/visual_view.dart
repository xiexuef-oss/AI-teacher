import 'package:flutter/material.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/math_text.dart';
import '../../core/widgets.dart';
import 'painters.dart';
import 'visual_math.dart';

/// 可调参数的教学图解。
///
/// 只认 [visualTemplates] 里注册过的模板：参数一律经注册表补齐、收进边界；拖动滑块时图形
/// 立即重画，不请求网络，更不会去问模型。模板不认识时显示审核过的文字说明，不会白屏。
class VisualView extends StatefulWidget {
  const VisualView({
    super.key,
    required this.templateId,
    this.params = const {},
    this.caption,
    this.staticFallback,
  });

  final String templateId;
  final Map<String, double> params;
  final String? caption;
  final String? staticFallback;

  @override
  State<VisualView> createState() => _VisualViewState();
}

class _VisualViewState extends State<VisualView> {
  VisualTemplateSpec? get _spec => visualTemplates[widget.templateId];

  late Map<String, double> _initial = _normalized();
  late Map<String, double> _values = Map.of(_initial);

  Map<String, double> _normalized() => _spec?.normalize(widget.params) ?? {};

  @override
  void didUpdateWidget(VisualView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.templateId != widget.templateId ||
        !_sameParams(oldWidget.params, widget.params)) {
      _initial = _normalized();
      _values = Map.of(_initial);
    }
  }

  bool _sameParams(Map<String, double> a, Map<String, double> b) =>
      a.length == b.length && a.entries.every((e) => b[e.key] == e.value);

  @override
  Widget build(BuildContext context) {
    final spec = _spec;
    if (spec == null) return _fallback(context);

    final theme = Theme.of(context);
    final palette = VisualPalette.of(theme.colorScheme);
    final adjustable = spec.params.where((p) => p.adjustable).toList();
    final showDescription = const {
      'chemical_process',
      'triangle_schematic',
      'circle_schematic',
    }.contains(spec.id);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(spec.title, style: theme.textTheme.titleSmall),
            ),
            TextButton.icon(
              key: const ValueKey('visual.reset'),
              onPressed: () => setState(() => _values = Map.of(_initial)),
              icon: const Icon(Icons.restart_alt),
              label: const Text('重置'),
            ),
          ],
        ),
        if (widget.caption != null && widget.caption!.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: MathText(widget.caption!, style: theme.textTheme.bodyMedium),
          ),
        if (showDescription)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(describeVisual(spec.id, _values)),
          ),
        Semantics(
          label: describeVisual(spec.id, _values),
          image: true,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: theme.colorScheme.surface,
                border: Border.all(color: theme.colorScheme.outlineVariant),
                borderRadius: BorderRadius.circular(12),
              ),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 300),
                child: AspectRatio(
                  aspectRatio: 16 / 9,
                  child: CustomPaint(
                    key: const ValueKey('visual.canvas'),
                    painter: painterFor(spec.id, _values, palette),
                    size: Size.infinite,
                  ),
                ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        for (final param in adjustable) _control(context, param),
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(
            '拖动滑块，图形立即变化；这些计算都在本机完成，不需要联网。',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ),
        Theme(
          data: theme.copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            key: const ValueKey('visual.text'),
            tilePadding: EdgeInsets.zero,
            title: const Text('文字说明'),
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(
                    showDescription
                        ? '${describeVisual(spec.id, _values)}\n${widget.staticFallback ?? spec.staticFallback}'
                        : widget.staticFallback ?? spec.staticFallback,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _control(BuildContext context, VisualParamSpec param) {
    final value = _values[param.name] ?? param.defaultValue;
    final isFlag = param.integer && param.min == 0 && param.max == 1;
    if (isFlag) {
      return SwitchListTile(
        key: ValueKey('visual.switch.${param.name}'),
        contentPadding: EdgeInsets.zero,
        title: Text(param.label),
        value: value >= 0.5,
        onChanged: (on) =>
            setState(() => _values = {..._values, param.name: on ? 1.0 : 0.0}),
      );
    }
    final divisions = ((param.max - param.min) / param.step).round().clamp(
      1,
      1000,
    );
    return Row(
      children: [
        SizedBox(
          width: 168,
          child: Text(
            param.label,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
        ),
        Expanded(
          child: Slider(
            key: ValueKey('visual.slider.${param.name}'),
            value: value.clamp(param.min, param.max),
            min: param.min,
            max: param.max,
            divisions: divisions,
            label: fmt(value),
            semanticFormatterCallback: (v) => '${param.label} ${fmt(v)}',
            onChanged: (v) => setState(
              () => _values = {..._values, param.name: param.clamp(v)},
            ),
          ),
        ),
        SizedBox(
          width: 52,
          child: Text(
            fmt(value),
            textAlign: TextAlign.end,
            style: const TextStyle(
              fontFeatures: [FontFeature.tabularFigures()],
            ),
          ),
        ),
      ],
    );
  }

  Widget _fallback(BuildContext context) {
    return Column(
      key: const ValueKey('visual.fallback'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Callout(
          tone: Tone.warning,
          child: Text('这个版本的应用还不认识这种图解，先看下面的文字说明。'),
        ),
        const SizedBox(height: 8),
        if (widget.caption != null && widget.caption!.isNotEmpty) ...[
          MathText(widget.caption!),
          const SizedBox(height: 8),
        ],
        Text(
          (widget.staticFallback ?? '').isEmpty
              ? '（没有可显示的文字说明）'
              : widget.staticFallback!,
          style: Theme.of(context).textTheme.bodyLarge,
        ),
      ],
    );
  }
}
