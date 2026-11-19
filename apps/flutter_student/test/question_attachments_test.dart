import 'dart:async';
import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/features/solve/question_attachments.dart';

const png =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=';
QuestionAttachment attachment(String id) =>
    QuestionAttachment(kind: 'image', mediaId: id, alt: '图示$id');
MediaContent media(String id, {String mime = 'image/png', String data = png}) =>
    MediaContent(mediaId: id, mime: mime, contentBase64: data);
Widget host(
  List<QuestionAttachment> attachments,
  Future<MediaContent> Function(String) load,
) => MaterialApp(
  home: Scaffold(
    body: SingleChildScrollView(
      child: QuestionAttachments(attachments: attachments, load: load),
    ),
  ),
);

Future<String> validPng() async {
  final recorder = ui.PictureRecorder();
  Canvas(recorder).drawColor(Colors.blue, BlendMode.src);
  final picture = recorder.endRecording();
  final image = await picture.toImage(2, 2);
  final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
  final result = base64Encode(bytes!.buffer.asUint8List());
  image.dispose();
  picture.dispose();
  return result;
}

void main() {
  testWidgets('non-image and absent media display alt without loading', (
    tester,
  ) async {
    var calls = 0;
    await tester.pumpWidget(
      host(
        const [
          QuestionAttachment(kind: 'table', mediaId: 'x', alt: '数据表'),
          QuestionAttachment(kind: 'image', alt: '无图'),
        ],
        (_) async {
          calls++;
          throw StateError('unexpected');
        },
      ),
    );
    expect(find.text('数据表'), findsOneWidget);
    expect(find.text('无图'), findsOneWidget);
    expect(calls, 0);
  });
  testWidgets('attachments load independently and retry offline failures', (
    tester,
  ) async {
    final waiting = Completer<MediaContent>();
    var tries = 0;
    await tester.pumpWidget(
      host([attachment('a'), attachment('b')], (id) {
        if (id == 'a') return waiting.future;
        tries++;
        return Future.error(StateError('offline'));
      }),
    );
    await tester.pump();
    expect(find.text('图片加载中…'), findsOneWidget);
    expect(find.textContaining('离线'), findsOneWidget);
    await tester.tap(find.text('重试图片'));
    await tester.pump();
    expect(tries, 2);
    await tester.pumpWidget(const SizedBox());
    waiting.complete(media('a'));
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'rejects scripts, mismatched ids, oversized data and invalid signatures',
    (tester) async {
      for (final invalid in [
        media('a', mime: 'image/svg+xml', data: '<script/>'),
        media('wrong'),
        media('a', data: 'A' * 22369625),
        media('a', data: base64Encode([1, 2, 3])),
      ]) {
        await tester.pumpWidget(const SizedBox());
        await tester.pumpWidget(host([attachment('a')], (_) async => invalid));
        await tester.pumpAndSettle();
        expect(find.text('图片已失效或格式不支持'), findsOneWidget);
        expect(find.byType(RawImage), findsNothing);
      }
    },
  );
  testWidgets('replacement ignores late media and renders current image', (
    tester,
  ) async {
    final old = Completer<MediaContent>();
    late String replacement;
    await tester.runAsync(() async {
      replacement = await validPng();
    });
    await tester.pumpWidget(host([attachment('old')], (_) => old.future));
    await tester.pumpWidget(
      host([attachment('new')], (_) async => media('new', data: replacement)),
    );
    await tester.runAsync(() async {
      await Future<void>.delayed(const Duration(milliseconds: 100));
    });
    await tester.pumpAndSettle();
    old.complete(media('old'));
    await tester.pumpAndSettle();
    expect(find.text('图示old'), findsNothing);
    expect(find.byType(RawImage), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'large source image is downsampled to 1024 and has alt semantics',
    (tester) async {
      late String data;
      await tester.runAsync(() async {
        final recorder = ui.PictureRecorder();
        Canvas(recorder).drawColor(Colors.blue, BlendMode.src);
        final picture = recorder.endRecording();
        final image = await picture.toImage(2048, 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        data = base64Encode(bytes!.buffer.asUint8List());
        image.dispose();
        picture.dispose();
      });
      await tester.pumpWidget(
        host([attachment('a')], (_) async => media('a', data: data)),
      );
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 100));
      });
      await tester.pumpAndSettle();
      expect(tester.widget<RawImage>(find.byType(RawImage)).image!.width, 1024);
      expect(find.bySemanticsLabel('图示a'), findsWidgets);
    },
  );
  testWidgets('narrow width and large text do not overflow', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MediaQuery(
            data: const MediaQueryData(textScaler: TextScaler.linear(3)),
            child: SizedBox(
              width: 120,
              child: SingleChildScrollView(
                child: QuestionAttachments(
                  attachments: [attachment('a')],
                  load: (_) async => throw StateError('offline'),
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
