import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'ink_export.dart';

/// Generation and system handoff are serialized; closing drops the PNG reference.
class InkExportDialog extends StatefulWidget {
  const InkExportDialog({
    super.key,
    required this.generate,
    this.save = saveInkPng,
    this.share = shareInkPng,
    this.preview = true,
  });
  final Future<Uint8List> Function() generate;
  final Future<String> Function(Uint8List) save;
  final Future<String> Function(Uint8List, Rect) share;
  final bool preview;
  @override
  State<InkExportDialog> createState() => _InkExportDialogState();
}

class _InkExportDialogState extends State<InkExportDialog> {
  Uint8List? _png;
  bool _busy = true;
  String _status = '正在生成图片…';
  @override
  void initState() {
    super.initState();
    _generate();
  }

  Future<void> _generate() async {
    setState(() {
      _busy = true;
      _status = '正在生成图片…';
    });
    try {
      final png = await widget.generate();
      if (mounted) {
        setState(() {
          _png = png;
          _status = '图片仅在本机生成。保存或分享由你选择。';
        });
      }
    } catch (_) {
      if (mounted) setState(() => _status = '图片生成失败，请重试。当前草稿没有被清空。');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _run(Future<String> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _status = '正在打开系统窗口…';
    });
    try {
      final status = await action();
      if (mounted) setState(() => _status = status);
    } catch (_) {
      if (mounted) setState(() => _status = '操作失败，请重试。当前草稿没有被清空。');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    final png = _png;
    if (png != null && widget.preview) {
      MemoryImage(png).evict();
    }
    _png = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !_busy,
    child: AlertDialog(
      title: const Text('草稿图片'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_png != null && widget.preview)
                Image.memory(
                  _png!,
                  key: const ValueKey('ink.export.preview'),
                  fit: BoxFit.contain,
                ),
              if (_busy) const LinearProgressIndicator(),
              const SizedBox(height: 12),
              Text(_status, key: const ValueKey('ink.export.status')),
            ],
          ),
        ),
      ),
      actions: [
        if (_png == null && !_busy)
          TextButton(onPressed: _generate, child: const Text('重试生成')),
        TextButton(
          key: const ValueKey('ink.export.save'),
          onPressed: _busy || _png == null
              ? null
              : () => _run(() => widget.save(_png!)),
          child: const Text('保存文件'),
        ),
        Builder(
          builder: (context) => TextButton(
            key: const ValueKey('ink.export.share'),
            onPressed: _busy || _png == null
                ? null
                : () {
                    final box = context.findRenderObject()! as RenderBox;
                    final origin = box.localToGlobal(Offset.zero) & box.size;
                    _run(() => widget.share(_png!, origin));
                  },
            child: const Text('系统分享'),
          ),
        ),
        FilledButton(
          onPressed: _busy ? null : () => Navigator.pop(context),
          child: const Text('好的'),
        ),
      ],
    ),
  );
}
