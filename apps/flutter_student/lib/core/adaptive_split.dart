import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// 断点（docs/03 §1）：不按物理像素、也不按设备品牌，只看可用宽度（逻辑像素）。
const double kExpandedBreakpoint = 900;
const double kMediumBreakpoint = 600;

enum LayoutClass {
  compact,
  medium,
  expanded;

  static LayoutClass forWidth(double width) {
    if (width >= kExpandedBreakpoint) return LayoutClass.expanded;
    if (width >= kMediumBreakpoint) return LayoutClass.medium;
    return LayoutClass.compact;
  }
}

/// 题目（左）与草稿（右）的可调整双栏。
///
/// - 宽度 ≥ 900：并排，题目 42% / 草稿 58%，中间的分隔条可以拖动，范围 35%–60%；
/// - 600–899：横屏并排（不可拖动）；竖屏上下排列；
/// - < 600：单栏，底部切换"题目 / 草稿"，两边的状态都保留（草稿画布不会因为切换丢失）。
class AdaptiveSplit extends StatefulWidget {
  const AdaptiveSplit({
    super.key,
    required this.primary,
    required this.secondary,
    this.primaryLabel = '题目',
    this.secondaryLabel = '草稿',
    this.initialFraction = defaultFraction,
  });

  static const double defaultFraction = 0.42;
  static const double minFraction = 0.35;
  static const double maxFraction = 0.60;

  final Widget primary;
  final Widget secondary;
  final String primaryLabel;
  final String secondaryLabel;
  final double initialFraction;

  @override
  State<AdaptiveSplit> createState() => _AdaptiveSplitState();
}

class _AdaptiveSplitState extends State<AdaptiveSplit> {
  late double _fraction = widget.initialFraction.clamp(
    AdaptiveSplit.minFraction,
    AdaptiveSplit.maxFraction,
  );
  int _tab = 0;

  void _setFraction(double value) {
    setState(() {
      _fraction = value.clamp(
        AdaptiveSplit.minFraction,
        AdaptiveSplit.maxFraction,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, box) {
        final layout = LayoutClass.forWidth(box.maxWidth);
        if (layout == LayoutClass.compact) return _tabs(context);
        final stacked =
            layout == LayoutClass.medium && box.maxHeight > box.maxWidth;
        if (stacked) return _column();
        return _row(box.maxWidth, draggable: layout == LayoutClass.expanded);
      },
    );
  }

  Widget _row(double width, {required bool draggable}) {
    const dividerWidth = 24.0;
    final usable = width - dividerWidth;
    final leftWidth = usable * _fraction;
    return Row(
      children: [
        SizedBox(
          key: const ValueKey('split.primary'),
          width: leftWidth,
          child: widget.primary,
        ),
        _Divider(
          enabled: draggable,
          fraction: _fraction,
          onDelta: (dx) => _setFraction(_fraction + dx / usable),
          width: dividerWidth,
        ),
        Expanded(
          key: const ValueKey('split.secondary'),
          child: widget.secondary,
        ),
      ],
    );
  }

  Widget _column() {
    return Column(
      children: [
        Expanded(
          flex: 45,
          key: const ValueKey('split.primary'),
          child: widget.primary,
        ),
        const Divider(height: 1),
        Expanded(
          flex: 55,
          key: const ValueKey('split.secondary'),
          child: widget.secondary,
        ),
      ],
    );
  }

  Widget _tabs(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          child: SizedBox(
            width: double.infinity,
            child: SegmentedButton<int>(
              key: const ValueKey('split.tabs'),
              showSelectedIcon: false,
              segments: [
                ButtonSegment(
                  value: 0,
                  label: Text(widget.primaryLabel),
                  icon: const Icon(Icons.article_outlined),
                ),
                ButtonSegment(
                  value: 1,
                  label: Text(widget.secondaryLabel),
                  icon: const Icon(Icons.edit_outlined),
                ),
              ],
              selected: {_tab},
              onSelectionChanged: (value) => setState(() => _tab = value.first),
            ),
          ),
        ),
        Expanded(
          // IndexedStack 让两边都留在树里：切到"题目"时草稿画布的状态不会丢
          child: IndexedStack(
            index: _tab,
            children: [
              KeyedSubtree(
                key: const ValueKey('split.primary'),
                child: widget.primary,
              ),
              KeyedSubtree(
                key: const ValueKey('split.secondary'),
                child: widget.secondary,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 分隔条：可见的线只有 4dp，可点击/拖动的区域是 24dp 宽、整栏高；键盘左右键微调。
class _Divider extends StatefulWidget {
  const _Divider({
    required this.enabled,
    required this.fraction,
    required this.onDelta,
    required this.width,
  });

  final bool enabled;
  final double fraction;
  final ValueChanged<double> onDelta;
  final double width;

  @override
  State<_Divider> createState() => _DividerState();
}

class _DividerState extends State<_Divider> {
  final FocusNode _focus = FocusNode(debugLabel: 'split.divider');

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.enabled;
    final fraction = widget.fraction;
    final onDelta = widget.onDelta;
    final width = widget.width;
    final scheme = Theme.of(context).colorScheme;
    final line = Center(
      child: Container(
        width: 4,
        margin: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          color: scheme.outlineVariant,
          borderRadius: BorderRadius.circular(2),
        ),
      ),
    );
    if (!enabled) {
      return SizedBox(
        key: const ValueKey('split.divider'),
        width: width,
        child: line,
      );
    }

    return Semantics(
      label: '调整题目与草稿的宽度',
      value: '题目占 ${(fraction * 100).round()}%',
      child: Focus(
        focusNode: _focus,
        onKeyEvent: (node, event) {
          if (event is! KeyDownEvent) return KeyEventResult.ignored;
          if (event.logicalKey == LogicalKeyboardKey.arrowLeft) {
            onDelta(-24);
            return KeyEventResult.handled;
          }
          if (event.logicalKey == LogicalKeyboardKey.arrowRight) {
            onDelta(24);
            return KeyEventResult.handled;
          }
          return KeyEventResult.ignored;
        },
        child: MouseRegion(
          cursor: SystemMouseCursors.resizeColumn,
          child: GestureDetector(
            key: const ValueKey('split.divider'),
            behavior: HitTestBehavior.translucent,
            onTapDown: (_) => _focus.requestFocus(),
            onHorizontalDragStart: (_) => _focus.requestFocus(),
            onHorizontalDragUpdate: (details) => onDelta(details.delta.dx),
            child: SizedBox(width: width, child: line),
          ),
        ),
      ),
    );
  }
}
