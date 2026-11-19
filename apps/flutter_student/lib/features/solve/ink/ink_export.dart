import 'dart:ui';

import 'package:flutter/foundation.dart';
import 'package:file_saver/file_saver.dart';
import 'package:share_plus/share_plus.dart';

import '../../../core/file_export.dart';

String _name() => 'ink-${DateTime.now().microsecondsSinceEpoch}';

Future<String> saveInkPng(Uint8List png) =>
    saveDataFile(png, name: _name(), extension: 'png', mimeType: MimeType.png);

Future<String> shareInkPng(Uint8List png, Rect origin) async {
  final result = await SharePlus.instance.share(
    ShareParams(
      files: [XFile.fromData(png, mimeType: 'image/png')],
      fileNameOverrides: ['${_name()}.png'],
      sharePositionOrigin: origin,
      downloadFallbackEnabled: true,
    ),
  );
  return switch (result.status) {
    ShareResultStatus.dismissed => '已取消分享',
    ShareResultStatus.success => '系统已处理分享请求。',
    ShareResultStatus.unavailable => '已交给系统或浏览器处理，请确认结果。',
  };
}
