import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';

import '../../core/math_text.dart';

final _blockId = RegExp(
  r'^(stem|subquestion:[1-9][0-9]{0,2}:stem|option:[1-9][0-9]{0,2}|subquestion:[1-9][0-9]{0,2}:option:[1-9][0-9]{0,2}|proof:given:[1-9][0-9]{0,2}|proof:claim|hint:[1-9][0-9]{0,2}|rephrase|solution:(standard|fast):(step:[1-9][0-9]{0,2}|final_answer|condition:[1-9][0-9]{0,2}|boundary|key_point:[1-9][0-9]{0,2})|visual:(caption|static_fallback)|rubric:point:[1-9][0-9]{0,2}|reference_cell:[1-9][0-9]{0,2}:[1-9][0-9]{0,2}:[1-9][0-9]{0,2}|reference_step:[1-9][0-9]{0,2}:(text|reason))$',
);
final _math = RegExp(r'\$([^$]+)\$');

class VerifiedContentReference {
  const VerifiedContentReference({
    required this.blockId,
    required this.text,
    required this.label,
    required this.start,
    required this.end,
  });
  final String blockId, text, label;
  final int start, end;
  String get selection =>
      String.fromCharCodes(text.runes.skip(start).take(end - start));
  bool get touchesMath => _math.allMatches(text).any((m) {
    final a = text.substring(0, m.start).runes.length;
    final b = text.substring(0, m.end).runes.length;
    return start < b && end > a;
  });
}

class ContentReferenceResult {
  const ContentReferenceResult(this.references, {this.unavailable = false});
  final List<VerifiedContentReference> references;
  final bool unavailable;
}

/// Raw JSON entry point also rejects fractional/bool offsets in damaged caches.
/// Identity comes from the actual session, never from a citation's own text.
ContentReferenceResult validateContentReferences(
  Object? raw, {
  required String eventSessionId,
  required String eventQuestionId,
  required int eventVersion,
  required String? sessionId,
  required String? questionId,
  required int? questionVersion,
}) {
  if (raw == null) {
    return const ContentReferenceResult([]);
  }
  if (raw is! List || raw.length > 8) {
    return const ContentReferenceResult([], unavailable: true);
  }
  if (raw.isEmpty) {
    return const ContentReferenceResult([]);
  }
  if (sessionId == null ||
      sessionId.isEmpty ||
      questionId == null ||
      questionId.isEmpty ||
      questionVersion == null ||
      questionVersion < 1 ||
      eventSessionId != sessionId ||
      eventQuestionId != questionId ||
      eventVersion != questionVersion) {
    return const ContentReferenceResult([], unavailable: true);
  }
  final result = <VerifiedContentReference>[], seen = <String>{};
  var unavailable = false;
  for (final value in raw) {
    if (value is! Map ||
        value.length != 6 ||
        !value.keys.every(
          (k) => const [
            'block_id',
            'block_sha256',
            'start',
            'end',
            'block_text',
            'label',
          ].contains(k),
        )) {
      unavailable = true;
      continue;
    }
    final id = value['block_id'],
        digest = value['block_sha256'],
        start = value['start'],
        end = value['end'],
        text = value['block_text'],
        label = value['label'];
    if (id is! String ||
        id.length > 64 ||
        _blockId.firstMatch(id)?.group(0) != id ||
        digest is! String ||
        !RegExp(r'^[a-f0-9]{64}$').hasMatch(digest) ||
        start is! int ||
        end is! int ||
        start < 0 ||
        start > 3999 ||
        end < 1 ||
        end > 4000 ||
        start >= end ||
        text is! String ||
        text.runes.isEmpty ||
        text.runes.length > 4000 ||
        end > text.runes.length ||
        label is! String ||
        label.runes.isEmpty ||
        label.runes.length > 120 ||
        sha256.convert(utf8.encode(text)).toString() != digest) {
      unavailable = true;
      continue;
    }
    final identity = jsonEncode([id, digest, start, end]);
    if (seen.add(identity)) {
      result.add(
        VerifiedContentReference(
          blockId: id,
          text: text,
          label: label,
          start: start,
          end: end,
        ),
      );
    }
  }
  return ContentReferenceResult(
    List.unmodifiable(result),
    unavailable: unavailable,
  );
}

/// Source formulas stay whole. Only ordinary text is split for emphasis.
class ContentReferenceContext extends StatelessWidget {
  const ContentReferenceContext(this.reference, {super.key});
  final VerifiedContentReference reference;
  @override
  Widget build(BuildContext context) {
    final r = reference;
    final emphasis = TextStyle(
      backgroundColor: Theme.of(context).colorScheme.secondaryContainer,
      fontWeight: FontWeight.bold,
    );
    if (r.touchesMath) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          MathText(r.text),
          const SizedBox(height: 12),
          const Text('选区触及公式；完整公式保留，下方显示精确原文选段，未高亮公式子结构。'),
          Text(
            r.selection,
            key: const ValueKey('reference.exactSelection'),
            style: emphasis,
          ),
        ],
      );
    }
    final spans = <InlineSpan>[];
    void plain(String text, int offset) {
      final runes = text.runes.toList();
      var cursor = 0;
      while (cursor < runes.length) {
        final selected = offset + cursor >= r.start && offset + cursor < r.end;
        var end = cursor + 1;
        while (end < runes.length &&
            (offset + end >= r.start && offset + end < r.end) == selected) {
          end++;
        }
        spans.add(
          TextSpan(
            text: String.fromCharCodes(runes.sublist(cursor, end)),
            style: selected ? emphasis : null,
          ),
        );
        cursor = end;
      }
    }

    var cursor = 0;
    for (final match in _math.allMatches(r.text)) {
      plain(
        r.text.substring(cursor, match.start),
        r.text.substring(0, cursor).runes.length,
      );
      spans.add(
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: MathText(match.group(0)!),
        ),
      );
      cursor = match.end;
    }
    plain(r.text.substring(cursor), r.text.substring(0, cursor).runes.length);
    return Text.rich(
      TextSpan(children: spans),
      key: const ValueKey('reference.highlightedContext'),
      semanticsLabel: r.text,
    );
  }
}
