import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:zxing2/qrcode.dart';

Future<List<String>> readPaperQrs(Uint8List bytes) async {
  final buffer = await ui.ImmutableBuffer.fromUint8List(bytes);
  try {
    final descriptor = await ui.ImageDescriptor.encoded(buffer);
    try {
      if (descriptor.width * descriptor.height > 24000000) return [];
      final portrait = descriptor.height > descriptor.width;
      final codec = await descriptor.instantiateCodec(
        targetWidth: !portrait && descriptor.width > 2200 ? 2200 : null,
        targetHeight: portrait && descriptor.height > 2200 ? 2200 : null,
      );
      try {
        final image = (await codec.getNextFrame()).image;
        try {
          final rgba = await image.toByteData();
          if (rgba == null) return [];
          return await compute(_decode, (
            image.width,
            image.height,
            rgba.buffer.asUint8List(rgba.offsetInBytes, rgba.lengthInBytes),
          ));
        } finally {
          image.dispose();
        }
      } finally {
        codec.dispose();
      }
    } finally {
      descriptor.dispose();
    }
  } finally {
    buffer.dispose();
  }
}

List<String> _decode((int, int, Uint8List) image) {
  final (width, height, rgba) = image;
  final pixels = Int32List(width * height);
  for (var i = 0; i < pixels.length; i++) {
    final offset = i * 4;
    pixels[i] =
        (rgba[offset] << 16) | (rgba[offset + 1] << 8) | rgba[offset + 2];
  }
  final source = RGBLuminanceSource(width, height, pixels);
  final tokens = <String>{};
  void find(LuminanceSource region) {
    try {
      final token = QRCodeReader()
          .decode(BinaryBitmap(HybridBinarizer(region)))
          .text;
      if (RegExp(r'^[0-9a-f]{32}$').hasMatch(token)) tokens.add(token);
    } on ReaderException {
      // A region can contain no readable code.
    }
  }

  find(source);
  // ponytail: bounded overlapping crops catch separated pages; dense or
  // overlapping codes need a dedicated multi-code detector.
  if (width >= 100 && height >= 100) {
    final w = width * 2 ~/ 3;
    final h = height * 2 ~/ 3;
    for (final x in [0, width - w]) {
      find(source.crop(x, 0, w, height));
      for (final y in [0, height - h]) {
        find(source.crop(x, y, w, h));
      }
    }
    for (final y in [0, height - h]) {
      find(source.crop(0, y, width, h));
    }
  }
  return tokens.toList();
}
