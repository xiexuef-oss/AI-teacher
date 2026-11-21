import 'package:flutter/material.dart';

import 'errors.dart';
import 'math_text.dart';
import 'theme.dart';

class LoadingView extends StatelessWidget {
  const LoadingView({super.key, this.label = '加载中…'});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Semantics(
        label: label,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(),
            const SizedBox(height: kGap),
            Text(label),
          ],
        ),
      ),
    );
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView({
    super.key,
    required this.error,
    this.onRetry,
    this.retryLabel = '重试',
  });

  final Object error;
  final VoidCallback? onRetry;
  final String retryLabel;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(kPad * 2),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                isNetworkError(error)
                    ? Icons.cloud_off_outlined
                    : Icons.error_outline,
                size: 48,
                color: scheme.error,
              ),
              const SizedBox(height: kGap),
              Text(
                describeError(error),
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyLarge,
              ),
              if (onRetry != null) ...[
                const SizedBox(height: kPad),
                FilledButton.icon(
                  onPressed: onRetry,
                  icon: const Icon(Icons.refresh),
                  label: Text(retryLabel),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class EmptyView extends StatelessWidget {
  const EmptyView({
    super.key,
    required this.title,
    this.message,
    this.icon = Icons.inbox_outlined,
    this.action,
  });

  final String title;
  final String? message;
  final IconData icon;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(kPad * 2),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 48, color: theme.colorScheme.outline),
              const SizedBox(height: kGap),
              Text(
                title,
                style: theme.textTheme.titleMedium,
                textAlign: TextAlign.center,
              ),
              if (message != null) ...[
                const SizedBox(height: 8),
                Text(
                  message!,
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium,
                ),
              ],
              if (action != null) ...[const SizedBox(height: kPad), action!],
            ],
          ),
        ),
      ),
    );
  }
}

/// 一块带标题的内容卡片。
class Section extends StatelessWidget {
  const Section({
    super.key,
    this.title,
    required this.child,
    this.trailing,
    this.padding = const EdgeInsets.all(kPad),
  });

  final String? title;
  final Widget child;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: padding,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(title!, style: theme.textTheme.titleMedium),
                    ),
                    ?trailing,
                  ],
                ),
              ),
            child,
          ],
        ),
      ),
    );
  }
}

enum Tone { neutral, info, success, warning, danger }

/// 带图标的小标签。颜色之外一定有文字。
class InfoChip extends StatelessWidget {
  const InfoChip(this.label, {super.key, this.icon, this.tone = Tone.neutral});

  final String label;
  final IconData? icon;
  final Tone tone;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final colors = StatusColors(scheme);
    final (Color fg, Color bg) = switch (tone) {
      Tone.neutral => (scheme.onSurfaceVariant, scheme.surfaceContainerHighest),
      Tone.info => (scheme.onSecondaryContainer, scheme.secondaryContainer),
      Tone.success => (colors.success, colors.success.withValues(alpha: 0.12)),
      Tone.warning => (colors.warning, colors.warning.withValues(alpha: 0.14)),
      Tone.danger => (scheme.onErrorContainer, scheme.errorContainer),
    };
    return DecoratedBox(
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 16, color: fg),
              const SizedBox(width: 4),
            ],
            Flexible(
              // 标签文字里也可能带 $公式$（比如"方法要点"）；没有公式时就是普通 Text
              child: MathText(
                label,
                style: Theme.of(context).textTheme.labelMedium
                    ?.copyWith(color: fg),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 一条带图标的提示框（提示、待确认、降级说明等）。
class Callout extends StatelessWidget {
  const Callout({
    super.key,
    required this.child,
    this.tone = Tone.info,
    this.icon,
    this.announce = false,
  });

  final Widget child;
  final Tone tone;
  final IconData? icon;

  /// 操作之后才出现的反馈（成功、失败）：让读屏软件在它出现时读出来，并且作为单独的一块，
  /// 不被并进旁边输入框的朗读文字里。
  final bool announce;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final colors = StatusColors(scheme);
    final (Color accent, IconData defaultIcon) = switch (tone) {
      Tone.success => (colors.success, Icons.check_circle_outline),
      Tone.warning => (colors.warning, Icons.warning_amber_rounded),
      Tone.danger => (scheme.error, Icons.error_outline),
      Tone.info => (scheme.primary, Icons.info_outline),
      Tone.neutral => (scheme.outline, Icons.info_outline),
    };
    final box = DecoratedBox(
      decoration: BoxDecoration(
        color: accent.withValues(alpha: 0.09),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: accent.withValues(alpha: 0.4)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon ?? defaultIcon, color: accent, size: 22),
            const SizedBox(width: 10),
            Expanded(child: child),
          ],
        ),
      ),
    );
    return announce
        ? Semantics(container: true, liveRegion: true, child: box)
        : box;
  }
}
