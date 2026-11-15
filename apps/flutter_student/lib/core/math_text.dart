import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';

class MathSegment {
  const MathSegment(this.text, {required this.isMath});

  final String text;
  final bool isMath;

  @override
  String toString() => isMath ? '\$$text\$' : text;
}

/// 把 `普通文字 $公式$ 普通文字` 拆成片段。没有配对的 `$` 按普通文字保留。
List<MathSegment> splitMath(String text) {
  final segments = <MathSegment>[];
  final pattern = RegExp(r'\$([^$]+)\$');
  var cursor = 0;
  for (final match in pattern.allMatches(text)) {
    if (match.start > cursor) {
      segments.add(
        MathSegment(text.substring(cursor, match.start), isMath: false),
      );
    }
    segments.add(MathSegment(match.group(1)!, isMath: true));
    cursor = match.end;
  }
  if (cursor < text.length) {
    segments.add(MathSegment(text.substring(cursor), isMath: false));
  }
  return segments;
}

/// 公式能否被渲染器解析（用于检查题库里的 LaTeX）。
bool canRenderTex(String tex) => Math.tex(tex).parseError == null;

/// 渲染含 `$...$` 行内公式的文字。公式解析失败时原样显示源码，不会白屏。
class MathText extends StatelessWidget {
  const MathText(this.text, {super.key, this.style, this.textAlign});

  final String text;
  final TextStyle? style;
  final TextAlign? textAlign;

  @override
  Widget build(BuildContext context) {
    final base = style ?? DefaultTextStyle.of(context).style;
    final segments = splitMath(text);
    if (segments.every((s) => !s.isMath)) {
      return Text(text, style: base, textAlign: textAlign);
    }
    // 系统字体放大时，由段落统一放大：普通文字按字号放大，行内的公式部件整体按同样的倍数放大。
    // 所以公式自己不能再乘一次倍数（早先公式自己乘、段落不放大，结果只有公式变大，
    // 旁边的文字原地不动，比例对不上）。
    return Text.rich(
      TextSpan(
        style: base,
        children: [
          for (final segment in segments)
            if (segment.isMath)
              WidgetSpan(
                alignment: PlaceholderAlignment.middle,
                // 公式不能折行：比可用宽度还宽时（窄屏、放大字体）等比缩小，而不是溢出
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Math.tex(
                    segment.text,
                    mathStyle: MathStyle.text,
                    textStyle: base,
                    onErrorFallback: (error) =>
                        Text('\$${segment.text}\$', style: base),
                  ),
                ),
              )
            else
              TextSpan(text: segment.text),
        ],
      ),
      textAlign: textAlign,
      // 屏幕阅读器读到的是源码文字；公式的朗读还没有专门处理
      semanticsLabel: text.replaceAll('\$', ''),
    );
  }
}
