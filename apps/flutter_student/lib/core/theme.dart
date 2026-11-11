import 'package:flutter/material.dart';

/// 设计取向：安静、专注、字够大。主色用偏深的青绿，保证白字在主色按钮上的对比度；
/// 深浅色都由同一个种子色生成。触控目标一律不小于 48dp。
/// 中文回退字体（pubspec 里注册的 Noto Sans SC 子集）。Android 与 iOS 有系统中文字体，
/// 但 Web 版渲染中文要联网下载回退字体，网络受限时会显示成方块，所以把字体打进应用。
const List<String> kCjkFontFallback = ['NotoSansSC'];

class AppTheme {
  static const Color seed = Color(0xFF0F766E);
  static const double minTarget = 48;

  static ThemeData light() => _build(Brightness.light);
  static ThemeData dark() => _build(Brightness.dark);

  static ThemeData _build(Brightness brightness) {
    final scheme = ColorScheme.fromSeed(
      seedColor: seed,
      brightness: brightness,
    );
    final base = ThemeData(colorScheme: scheme, useMaterial3: true);
    final text = base.textTheme.apply(fontFamilyFallback: kCjkFontFallback);
    const minSize = Size(minTarget, minTarget);
    final buttonShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(12),
    );
    return base.copyWith(
      scaffoldBackgroundColor: scheme.surface,
      materialTapTargetSize: MaterialTapTargetSize.padded,
      textTheme: text.copyWith(
        bodyLarge: text.bodyLarge?.copyWith(fontSize: 17, height: 1.55),
        bodyMedium: text.bodyMedium?.copyWith(fontSize: 15, height: 1.5),
      ),
      primaryTextTheme: base.primaryTextTheme.apply(
        fontFamilyFallback: kCjkFontFallback,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
        elevation: 0,
        scrolledUnderElevation: 1,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        margin: EdgeInsets.zero,
        color: scheme.surfaceContainerLow,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: scheme.outlineVariant),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(minimumSize: minSize, shape: buttonShape),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: minSize,
          shape: buttonShape,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(minimumSize: minSize, shape: buttonShape),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(minimumSize: minSize),
      ),
      inputDecorationTheme: InputDecorationTheme(
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 14,
        ),
      ),
      chipTheme: base.chipTheme.copyWith(
        labelStyle: base.textTheme.labelLarge,
        padding: const EdgeInsets.symmetric(horizontal: 4),
      ),
      focusColor: scheme.primary.withValues(alpha: 0.18),
    );
  }
}

/// 状态色（不只靠颜色表达：旁边总有图标或文字）。
class StatusColors {
  StatusColors(this.scheme);

  final ColorScheme scheme;

  bool get _dark => scheme.brightness == Brightness.dark;

  Color get success =>
      _dark ? const Color(0xFF6EE7B7) : const Color(0xFF047857);
  Color get warning =>
      _dark ? const Color(0xFFFCD34D) : const Color(0xFF92400E);
  Color get danger => scheme.error;
  Color get info => scheme.primary;
}

const double kGap = 12;
const double kPad = 16;
