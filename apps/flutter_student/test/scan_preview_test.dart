import 'dart:typed_data';

import 'package:flutter/painting.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/features/scan/scan_preview.dart';

void main() {
  testWidgets(
    'replacement and clear evict only this preview and release bytes',
    (tester) async {
      final preview = ScanPreview();
      final first = Uint8List.fromList([1, 2, 3]);
      preview.replace(first);
      final old = preview.provider!;
      final raster = (await tester.runAsync(
        () => createTestImage(width: 1, height: 1),
      ))!;
      PaintingBinding.instance.imageCache.putIfAbsent(
        old,
        () => OneFrameImageStreamCompleter(
          Future.value(ImageInfo(image: raster)),
        ),
      );
      await tester.pump();
      expect(PaintingBinding.instance.imageCache.containsKey(old), isTrue);
      preview.replace(Uint8List.fromList([4, 5, 6]));
      await tester.pump();
      expect(PaintingBinding.instance.imageCache.containsKey(old), isFalse);
      expect(preview.provider, isNot(same(old)));
      preview.clear();
      await tester.pump();
      expect(preview.bytes, isNull);
      expect(preview.provider, isNull);
    },
  );
}
