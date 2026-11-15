import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../../../core/theme.dart';
import 'ink_controller.dart';
import 'ink_painter.dart';

const double _eraserPixels = 14;

/// 草稿画布：工具栏 + 竖向排列的多页草稿纸。
///
/// 书写规则：手写笔和鼠标直接书写；见过手写笔之后手指不再书写（防手掌误触），手指只用来滚动。
/// 工具栏的"移动"模式下任何输入都只滚动、不书写。
class InkCanvas extends StatefulWidget {
  const InkCanvas({super.key, required this.controller, this.readOnly = false});

  final InkController controller;
  final bool readOnly;

  @override
  State<InkCanvas> createState() => _InkCanvasState();
}

class _InkCanvasState extends State<InkCanvas> {
  bool _drawing = false;

  void _setDrawing(bool value) {
    if (_drawing != value) setState(() => _drawing = value);
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    return Semantics(
      container: true,
      label: '草稿画布。用手写笔在这里演算，笔迹会自动保存在这台设备上。',
      child: ColoredBox(
        color: Theme.of(context).colorScheme.surfaceContainerLowest,
        child: Column(
          children: [
            if (!widget.readOnly) InkToolbar(controller: controller),
            Expanded(
              child: ListenableBuilder(
                listenable: controller,
                builder: (context, _) {
                  return SingleChildScrollView(
                    // 正在书写时锁住滚动，否则手指/笔一拖就把页面带走了
                    physics: _drawing
                        ? const NeverScrollableScrollPhysics()
                        : null,
                    padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                    child: Column(
                      children: [
                        for (var i = 0; i < controller.pages.length; i++)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 12),
                            child: _PageView(
                              key: ValueKey('ink.page.$i'),
                              controller: controller,
                              index: i,
                              readOnly: widget.readOnly,
                              onDrawing: _setDrawing,
                            ),
                          ),
                        if (!widget.readOnly)
                          OutlinedButton.icon(
                            key: const ValueKey('ink.addPage'),
                            onPressed: controller.canAddPage
                                ? controller.addPage
                                : null,
                            icon: const Icon(Icons.note_add_outlined),
                            label: Text(
                              controller.canAddPage
                                  ? '再加一页'
                                  : '已经是最后一页（最多 ${controller.maxPages} 页）',
                            ),
                          ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PageView extends StatelessWidget {
  const _PageView({
    super.key,
    required this.controller,
    required this.index,
    required this.readOnly,
    required this.onDrawing,
  });

  final InkController controller;
  final int index;
  final bool readOnly;
  final ValueChanged<bool> onDrawing;

  @override
  Widget build(BuildContext context) {
    final page = controller.pages[index];
    return LayoutBuilder(
      builder: (context, box) {
        final width = box.maxWidth;
        final size = Size(width, width * page.height / page.width);
        return DecoratedBox(
          decoration: BoxDecoration(
            border: Border.all(
              color: Theme.of(context).colorScheme.outlineVariant,
            ),
            boxShadow: const [
              BoxShadow(
                color: Color(0x14000000),
                blurRadius: 6,
                offset: Offset(0, 2),
              ),
            ],
          ),
          child: SizedBox(
            width: size.width,
            height: size.height,
            child: _PageSurface(
              controller: controller,
              pageIndex: index,
              size: size,
              readOnly: readOnly,
              onDrawing: onDrawing,
            ),
          ),
        );
      },
    );
  }
}

class _PageSurface extends StatefulWidget {
  const _PageSurface({
    required this.controller,
    required this.pageIndex,
    required this.size,
    required this.readOnly,
    required this.onDrawing,
  });

  final InkController controller;
  final int pageIndex;
  final Size size;
  final bool readOnly;
  final ValueChanged<bool> onDrawing;

  @override
  State<_PageSurface> createState() => _PageSurfaceState();
}

class _PageSurfaceState extends State<_PageSurface> {
  int? _pointer;
  bool _erasing = false;
  int _startMs = 0;

  InkController get _ink => widget.controller;
  InkPage get _page => _ink.pages[widget.pageIndex];
  double get _scale => _page.width / widget.size.width;

  bool _accepts(PointerDownEvent e) {
    if (widget.readOnly || _ink.tool == InkTool.hand || _pointer != null) {
      return false;
    }
    switch (e.kind) {
      case PointerDeviceKind.stylus:
      case PointerDeviceKind.invertedStylus:
        _ink.stylusSeen = true;
        return true;
      case PointerDeviceKind.mouse:
        return (e.buttons & kPrimaryButton) != 0;
      case PointerDeviceKind.touch:
        return !_ink.stylusSeen;
      default:
        return false;
    }
  }

  double _pressure(PointerEvent e) {
    if (e.kind == PointerDeviceKind.mouse || e.pressureMax <= e.pressureMin) {
      return 0.5;
    }
    return ((e.pressure - e.pressureMin) / (e.pressureMax - e.pressureMin))
        .clamp(0.0, 1.0);
  }

  void _onDown(PointerDownEvent e) {
    if (!_accepts(e)) return;
    _pointer = e.pointer;
    _erasing =
        _ink.tool == InkTool.eraser ||
        e.kind == PointerDeviceKind.invertedStylus;
    _startMs = e.timeStamp.inMilliseconds;
    widget.onDrawing(true);
    final x = e.localPosition.dx * _scale;
    final y = e.localPosition.dy * _scale;
    if (_erasing) {
      _ink.eraseAt(widget.pageIndex, x, y, _eraserPixels * _scale);
    } else {
      _ink.beginStroke(widget.pageIndex, x, y, t: 0, pressure: _pressure(e));
    }
  }

  void _onMove(PointerMoveEvent e) {
    if (e.pointer != _pointer) return;
    final x = e.localPosition.dx * _scale;
    final y = e.localPosition.dy * _scale;
    if (_erasing) {
      _ink.eraseAt(widget.pageIndex, x, y, _eraserPixels * _scale);
    } else {
      _ink.extendStroke(
        x,
        y,
        t: e.timeStamp.inMilliseconds - _startMs,
        pressure: _pressure(e),
      );
    }
  }

  void _finish({required bool cancelled}) {
    if (_pointer == null) return;
    _pointer = null;
    if (_erasing) {
      _ink.endErase();
    } else if (cancelled) {
      _ink.cancelStroke();
    } else {
      _ink.endStroke();
    }
    widget.onDrawing(false);
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      behavior: HitTestBehavior.opaque,
      onPointerDown: _onDown,
      onPointerMove: _onMove,
      onPointerUp: (_) => _finish(cancelled: false),
      onPointerCancel: (_) => _finish(cancelled: true),
      child: RepaintBoundary(
        child: CustomPaint(
          size: widget.size,
          painter: InkPagePainter(_page, _ink),
        ),
      ),
    );
  }
}

/// 工具栏：笔、橡皮、移动；颜色；粗细；撤销、重做；清空；导出图片。
class InkToolbar extends StatelessWidget {
  const InkToolbar({super.key, required this.controller});

  final InkController controller;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final scheme = Theme.of(context).colorScheme;
        return Material(
          color: scheme.surfaceContainerLow,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            child: Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 4,
              runSpacing: 0,
              children: [
                _ToolButton(
                  keyName: 'ink.tool.pen',
                  icon: Icons.edit,
                  tooltip: '笔',
                  selected: controller.tool == InkTool.pen,
                  onPressed: () => _select(InkTool.pen),
                ),
                _ToolButton(
                  keyName: 'ink.tool.eraser',
                  icon: Icons.auto_fix_normal,
                  tooltip: '橡皮：碰到的笔画整条擦掉',
                  selected: controller.tool == InkTool.eraser,
                  onPressed: () => _select(InkTool.eraser),
                ),
                _ToolButton(
                  keyName: 'ink.tool.hand',
                  icon: Icons.pan_tool_alt_outlined,
                  tooltip: '移动：只滚动，不书写',
                  selected: controller.tool == InkTool.hand,
                  onPressed: () => _select(InkTool.hand),
                ),
                const _Gap(),
                _ColorDot(
                  keyName: 'ink.color.black',
                  hex: '#1A1A1A',
                  label: '黑色',
                  controller: controller,
                ),
                _ColorDot(
                  keyName: 'ink.color.blue',
                  hex: '#1D4ED8',
                  label: '蓝色',
                  controller: controller,
                ),
                const _Gap(),
                _WidthDot(
                  keyName: 'ink.width.thin',
                  value: 1.5,
                  label: '细',
                  controller: controller,
                ),
                _WidthDot(
                  keyName: 'ink.width.medium',
                  value: 2.5,
                  label: '中',
                  controller: controller,
                ),
                _WidthDot(
                  keyName: 'ink.width.thick',
                  value: 4.5,
                  label: '粗',
                  controller: controller,
                ),
                const _Gap(),
                _ToolButton(
                  keyName: 'ink.undo',
                  icon: Icons.undo,
                  tooltip: '撤销',
                  onPressed: controller.canUndo ? controller.undo : null,
                ),
                _ToolButton(
                  keyName: 'ink.redo',
                  icon: Icons.redo,
                  tooltip: '重做',
                  onPressed: controller.canRedo ? controller.redo : null,
                ),
                _ToolButton(
                  keyName: 'ink.clear',
                  icon: Icons.delete_sweep_outlined,
                  tooltip: '清空草稿',
                  onPressed: controller.hasInk
                      ? () => _confirmClear(context)
                      : null,
                ),
                _ToolButton(
                  keyName: 'ink.export',
                  icon: Icons.image_outlined,
                  tooltip: '导出为图片',
                  onPressed: controller.hasInk ? () => _export(context) : null,
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _select(InkTool tool) => controller.selectTool(tool);

  Future<void> _confirmClear(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('清空草稿？'),
        content: const Text('所有页面上的笔迹都会被擦掉。清空之后还可以点“撤销”找回。'),
        actions: [
          TextButton(
            key: const ValueKey('ink.clear.cancel'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            key: const ValueKey('ink.clear.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('清空'),
          ),
        ],
      ),
    );
    if (ok == true) controller.clearAll();
  }

  Future<void> _export(BuildContext context) async {
    final png = await renderInkPng(controller.pages);
    if (!context.mounted) return;
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('草稿图片'),
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Image.memory(
                  png,
                  key: const ValueKey('ink.export.preview'),
                  fit: BoxFit.contain,
                ),
                const SizedBox(height: 12),
                Text(
                  '图片已生成（${png.length ~/ 1024} KB）。保存到相册、分享给老师需要接入系统的保存与分享能力，当前版本只提供预览。',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('好的'),
          ),
        ],
      ),
    );
  }
}

class _Gap extends StatelessWidget {
  const _Gap();

  @override
  Widget build(BuildContext context) => const SizedBox(width: 8);
}

class _ToolButton extends StatelessWidget {
  const _ToolButton({
    required this.keyName,
    required this.icon,
    required this.tooltip,
    required this.onPressed,
    this.selected = false,
  });

  final String keyName;
  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      key: ValueKey(keyName),
      isSelected: selected,
      onPressed: onPressed,
      tooltip: tooltip,
      icon: Icon(icon),
      style: IconButton.styleFrom(
        minimumSize: const Size(AppTheme.minTarget, AppTheme.minTarget),
      ),
    );
  }
}

class _ColorDot extends StatelessWidget {
  const _ColorDot({
    required this.keyName,
    required this.hex,
    required this.label,
    required this.controller,
  });

  final String keyName;
  final String hex;
  final String label;
  final InkController controller;

  @override
  Widget build(BuildContext context) {
    final selected = controller.color == hex;
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      selected: selected,
      label: '笔迹颜色：$label',
      child: InkResponse(
        key: ValueKey(keyName),
        onTap: () => controller.selectColor(hex),
        radius: 28,
        child: SizedBox(
          width: AppTheme.minTarget,
          height: AppTheme.minTarget,
          child: Center(
            child: Container(
              width: 28,
              height: 28,
              decoration: BoxDecoration(
                color: parseHexColor(hex),
                shape: BoxShape.circle,
                border: Border.all(
                  color: selected ? scheme.primary : scheme.outline,
                  width: selected ? 3 : 1,
                ),
              ),
              child: selected
                  ? const Icon(Icons.check, size: 16, color: Colors.white)
                  : null,
            ),
          ),
        ),
      ),
    );
  }
}

class _WidthDot extends StatelessWidget {
  const _WidthDot({
    required this.keyName,
    required this.value,
    required this.label,
    required this.controller,
  });

  final String keyName;
  final double value;
  final String label;
  final InkController controller;

  @override
  Widget build(BuildContext context) {
    final selected = controller.width == value;
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      selected: selected,
      label: '笔画粗细：$label',
      child: InkResponse(
        key: ValueKey(keyName),
        onTap: () => controller.selectWidth(value),
        radius: 28,
        child: SizedBox(
          width: AppTheme.minTarget,
          height: AppTheme.minTarget,
          child: Center(
            child: Container(
              width: 8 + value * 3,
              height: 8 + value * 3,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: selected ? scheme.primary : scheme.outline,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
