import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

/// Session-only, bounded image rendering. No URLs or persistent image cache.
class QuestionAttachments extends StatelessWidget {
  const QuestionAttachments({
    super.key,
    required this.attachments,
    required this.load,
  });

  final List<QuestionAttachment> attachments;
  final Future<MediaContent> Function(String mediaId) load;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      for (var i = 0; i < attachments.length; i++)
        _Attachment(
          key: ValueKey('$i:${attachments[i].kind}:${attachments[i].mediaId}'),
          attachment: attachments[i],
          load: load,
        ),
    ],
  );
}

class _Attachment extends StatefulWidget {
  const _Attachment({super.key, required this.attachment, required this.load});
  final QuestionAttachment attachment;
  final Future<MediaContent> Function(String) load;

  @override
  State<_Attachment> createState() => _AttachmentState();
}

class _AttachmentState extends State<_Attachment> {
  ui.Image? _image;
  String? _error;
  int _generation = 0;
  String get _alt =>
      widget.attachment.alt.trim().isEmpty ? '附件暂无文字说明' : widget.attachment.alt;
  bool get _hasImage =>
      widget.attachment.kind == 'image' && widget.attachment.mediaId != null;

  @override
  void initState() {
    super.initState();
    if (_hasImage) _load();
  }

  Future<void> _load() async {
    final generation = ++_generation;
    setState(() => _error = null);
    ui.Image? image;
    try {
      final media = await widget.load(widget.attachment.mediaId!);
      if (!mounted || generation != _generation) return;
      if (media.mediaId != widget.attachment.mediaId) {
        throw const FormatException('identity');
      }
      image = await _decode(media);
      if (!mounted || generation != _generation) {
        image.dispose();
        return;
      }
      setState(() {
        _image?.dispose();
        _image = image;
      });
    } catch (error) {
      image?.dispose();
      if (!mounted || generation != _generation) return;
      setState(
        () => _error = error is FormatException
            ? '图片已失效或格式不支持'
            : '图片暂不可用，离线时请联网后重试',
      );
    }
  }

  @override
  void dispose() {
    _generation++;
    _image?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 8),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(_alt),
        if (_hasImage && _image != null)
          Semantics(
            image: true,
            label: _alt,
            child: ExcludeSemantics(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 512),
                child: RawImage(image: _image, fit: BoxFit.contain),
              ),
            ),
          )
        else if (_hasImage && _error == null)
          const Text('图片加载中…')
        else if (_hasImage) ...[
          Text(_error!, semanticsLabel: _error),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(onPressed: _load, child: const Text('重试图片')),
          ),
        ],
      ],
    ),
  );
}

Future<ui.Image> _decode(MediaContent media) async {
  if (!const {'image/png', 'image/jpeg', 'image/webp'}.contains(media.mime) ||
      media.contentBase64.length > 22369624 ||
      !RegExp(r'^[A-Za-z0-9+/]*={0,2}$').hasMatch(media.contentBase64)) {
    throw const FormatException('format or size');
  }
  final bytes = base64Decode(media.contentBase64);
  if (bytes.isEmpty ||
      bytes.length > 16 * 1024 * 1024 ||
      !_signature(bytes, media.mime)) {
    throw const FormatException('size or signature');
  }
  ui.ImmutableBuffer? buffer;
  ui.ImageDescriptor? descriptor;
  ui.Codec? codec;
  try {
    buffer = await ui.ImmutableBuffer.fromUint8List(bytes);
    descriptor = await ui.ImageDescriptor.encoded(buffer);
    if (descriptor.width <= 0 ||
        descriptor.height <= 0 ||
        descriptor.width * descriptor.height > 20000000) {
      throw const FormatException('pixel limit');
    }
    final scale = math.min(
      1.0,
      1024 / math.max(descriptor.width, descriptor.height),
    );
    codec = await descriptor.instantiateCodec(
      targetWidth: math.max(1, (descriptor.width * scale).floor()),
      targetHeight: math.max(1, (descriptor.height * scale).floor()),
    );
    if (codec.frameCount != 1) throw const FormatException('animated');
    return (await codec.getNextFrame()).image;
  } catch (_) {
    throw const FormatException('invalid image');
  } finally {
    codec?.dispose();
    descriptor?.dispose();
    buffer?.dispose();
  }
}

bool _signature(Uint8List bytes, String mime) {
  bool starts(List<int> prefix) =>
      bytes.length >= prefix.length &&
      List.generate(
        prefix.length,
        (i) => bytes[i] == prefix[i],
      ).every((v) => v);
  return switch (mime) {
    'image/png' => starts([137, 80, 78, 71, 13, 10, 26, 10]),
    'image/jpeg' => starts([255, 216, 255]),
    'image/webp' =>
      starts([82, 73, 70, 70]) &&
          bytes.length >= 12 &&
          ascii.decode(bytes.sublist(8, 12), allowInvalid: true) == 'WEBP',
    _ => false,
  };
}
