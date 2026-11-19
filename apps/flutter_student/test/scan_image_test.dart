import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/features/scan/scan_image.dart';

Uint8List png({int width = 1, int height = 1}) {
  final b = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC',
  );
  ByteData.sublistView(b).setUint32(16, width);
  ByteData.sublistView(b).setUint32(20, height);
  return b;
}

void main() {
  testWidgets(
    'the accepted header uses a Web supported codec and releases its frame',
    (tester) async {
      await tester.runAsync(() async {
        final bytes = png();
        expect(inspectScanImage(bytes).width, 1);
        final codec = await ui.instantiateImageCodec(bytes);
        try {
          expect(codec.frameCount, 1);
          final frame = await codec.getNextFrame();
          expect(frame.image.width, 1);
          frame.image.dispose();
        } finally {
          codec.dispose();
        }
      });
    },
  );
  test('Web safe PNG dimensions are read before decoding', () {
    final info = inspectScanImage(png());
    expect(info.mime, 'image/png');
    expect(info.width, 1);
    expect(info.height, 1);
    expect(
      () => inspectScanImage(png(width: 4000, height: 4000)),
      throwsFormatException,
    );
  });
  test('rejects truncated, oversized and animated input', () {
    expect(
      () => inspectScanImage(Uint8List(5 * 1024 * 1024 + 1)),
      throwsFormatException,
    );
    expect(
      () => inspectScanImage(Uint8List.fromList(png().take(25).toList())),
      throwsFormatException,
    );
    expect(() => inspectScanImage(png(width: 0)), throwsFormatException);
    final animated = png();
    animated.setRange(37, 41, 'acTL'.codeUnits);
    expect(() => inspectScanImage(animated), throwsFormatException);
  });
  test('JPEG SOF validates bounds and segment truncation before decoding', () {
    Uint8List jpeg(int height) => Uint8List.fromList([
      255,
      216,
      255,
      192,
      0,
      11,
      8,
      height >> 8,
      height & 255,
      0,
      1,
      1,
      1,
      17,
      0,
      255,
      218,
      0,
      8,
      1,
      1,
      0,
      0,
      63,
      0,
      255,
      217,
    ]);
    expect(inspectScanImage(jpeg(1)).mime, 'image/jpeg');
    expect(
      () => inspectScanImage(Uint8List.fromList(jpeg(1).take(9).toList())),
      throwsFormatException,
    );
  });
}

