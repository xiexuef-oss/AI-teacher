import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/features/profile/paper_qr.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('reads the opaque token from a rendered paper pack QR', () async {
    final bytes = await File('test/fixtures/paper-page-qr.png').readAsBytes();
    expect(await readPaperQrs(bytes), ['490a26ed8f244ada918ff56da8ce890a']);
  });

  test('finds two distinct paper tokens in a separated-page photo', () async {
    final bytes = await File('test/fixtures/paper-mixed-qr.png').readAsBytes();
    expect(
      await readPaperQrs(bytes),
      unorderedEquals([
        '490a26ed8f244ada918ff56da8ce890a',
        '6e775168a8e747498d06180d758d482e',
      ]),
    );
  });

  for (final covered in [false, true]) {
    test('tilted paper QR with lower page covered=$covered', () async {
      final bytes = await File('test/fixtures/paper-page-qr.png').readAsBytes();
      final codec = await ui.instantiateImageCodec(bytes);
      final source = (await codec.getNextFrame()).image;
      final width = source.width + 300;
      final height = source.height + 300;
      final recorder = ui.PictureRecorder();
      final canvas = ui.Canvas(recorder);
      canvas.drawColor(const ui.Color(0xffffffff), ui.BlendMode.src);
      canvas.translate(width / 2, height / 2);
      canvas.rotate(0.12);
      canvas.drawImage(
        source,
        ui.Offset(-source.width / 2, -source.height / 2),
        ui.Paint(),
      );
      if (covered) {
        canvas.drawRect(
          ui.Rect.fromLTWH(
            -source.width / 2,
            0,
            source.width.toDouble(),
            source.height / 2,
          ),
          ui.Paint()..color = const ui.Color(0xffeeeeee),
        );
      }
      final picture = recorder.endRecording();
      final tilted = await picture.toImage(width, height);
      try {
        final png = (await tilted.toByteData(format: ui.ImageByteFormat.png))!;
        expect(
          await readPaperQrs(png.buffer.asUint8List()),
          covered ? isEmpty : ['490a26ed8f244ada918ff56da8ce890a'],
        );
      } finally {
        tilted.dispose();
        picture.dispose();
        source.dispose();
        codec.dispose();
      }
    });
  }
}
