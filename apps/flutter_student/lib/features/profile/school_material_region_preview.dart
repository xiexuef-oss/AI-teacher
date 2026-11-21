import 'dart:typed_data';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

const schoolMaterialRegionLabels = {
  'stem': '题面',
  'answer': '学生作答',
  'teacher_mark': '教师批注',
};

class SchoolMaterialRegionPreview extends StatefulWidget {
  const SchoolMaterialRegionPreview({
    super.key,
    required this.page,
    required this.image,
    required this.regions,
    required this.selectRegion,
  });

  final int page;
  final MemoryImage image;
  final List<SchoolMaterialRegion> regions;
  final bool selectRegion;

  @override
  State<SchoolMaterialRegionPreview> createState() => _RegionPreviewState();
}

class _RegionPreviewState extends State<SchoolMaterialRegionPreview> {
  Offset? _start;
  Rect? _selection;
  String _kind = 'stem';

  Size get _sourceSize {
    final bytes = widget.image.bytes;
    if (bytes.length < 24) return Size.zero;
    final header = ByteData.sublistView(bytes);
    if (header.getUint32(0) != 0x89504e47 ||
        header.getUint32(4) != 0x0d0a1a0a) {
      return Size.zero;
    }
    return Size(
      header.getUint32(16).toDouble(),
      header.getUint32(20).toDouble(),
    );
  }

  Offset _normalized(Offset position, Size canvas) => Offset(
    (position.dx / canvas.width).clamp(0.0, 1.0),
    (position.dy / canvas.height).clamp(0.0, 1.0),
  );

  Widget _canvas(Size size) {
    final primary = Theme.of(context).colorScheme.primary;
    Widget box(Rect region, {String? label}) => Positioned.fromRect(
      rect: Rect.fromLTRB(
        region.left * size.width,
        region.top * size.height,
        region.right * size.width,
        region.bottom * size.height,
      ),
      child: IgnorePointer(
        child: DecoratedBox(
          decoration: BoxDecoration(
            border: Border.all(color: primary, width: 2),
          ),
          child: label == null ? null : Semantics(label: label),
        ),
      ),
    );

    final canvas = SizedBox.fromSize(
      size: size,
      child: Stack(
        fit: StackFit.expand,
        children: [
          Image(image: widget.image, fit: BoxFit.fill),
          for (final region in widget.regions.where(
            (r) => r.page == widget.page,
          ))
            box(
              Rect.fromLTRB(
                region.left,
                region.top,
                region.right,
                region.bottom,
              ),
              label: schoolMaterialRegionLabels[region.kind],
            ),
          if (_selection case final selection?) box(selection),
        ],
      ),
    );
    if (!widget.selectRegion) return InteractiveViewer(child: canvas);
    return GestureDetector(
      key: const ValueKey('schoolMaterial.regionCanvas'),
      dragStartBehavior: DragStartBehavior.down,
      onPanStart: (event) => setState(() {
        _start = _normalized(event.localPosition, size);
        _selection = null;
      }),
      onPanUpdate: (event) => setState(() {
        _selection = Rect.fromPoints(
          _start!,
          _normalized(event.localPosition, size),
        );
      }),
      onPanCancel: () => setState(() => _selection = null),
      child: canvas,
    );
  }

  @override
  Widget build(BuildContext context) {
    final selection = _selection;
    final source = _sourceSize;
    return AlertDialog(
      title: Text('原件第 ${widget.page} 页'),
      content: SizedBox(
        width: 560,
        height: 420,
        child: Column(
          children: [
            if (widget.selectRegion) ...[
              DropdownButton<String>(
                value: _kind,
                onChanged: (kind) => setState(() => _kind = kind!),
                items: [
                  for (final entry in schoolMaterialRegionLabels.entries)
                    DropdownMenuItem(
                      value: entry.key,
                      child: Text(entry.value),
                    ),
                ],
              ),
              const Text('在原件上拖动，框住所选区域。'),
            ],
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  if (source.isEmpty) {
                    return const Center(child: Text('无法显示原件预览。'));
                  }
                  final fit = applyBoxFit(
                    BoxFit.contain,
                    source,
                    constraints.biggest,
                  );
                  if (fit.destination.isEmpty) return const SizedBox.shrink();
                  return Center(child: _canvas(fit.destination));
                },
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('关闭'),
        ),
        if (widget.selectRegion)
          FilledButton(
            onPressed: selection == null || selection.isEmpty
                ? null
                : () {
                    Navigator.pop(
                      context,
                      SchoolMaterialRegion(
                        page: widget.page,
                        kind: _kind,
                        left: selection.left,
                        top: selection.top,
                        right: selection.right,
                        bottom: selection.bottom,
                      ),
                    );
                  },
            child: const Text('保留区域'),
          ),
      ],
    );
  }
}
