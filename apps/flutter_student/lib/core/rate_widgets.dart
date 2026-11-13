import 'package:flutter/material.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import 'format.dart';
import 'theme.dart';
import 'widgets.dart';

/// 学情页和家长周报共用的几张小卡片：比例卡、按维度的对照表。
/// 样本不足时比例是 null，只显示计数和原因，不显示伪精确的百分比。

String rateCount(RateStat stat) => '${stat.numerator}/${stat.denominator}';

class RateCard extends StatelessWidget {
  const RateCard({
    super.key,
    required this.keyName,
    required this.title,
    required this.stat,
    required this.minSamples,
    required this.help,
    this.emphasized = false,
    this.keyPrefix = 'progress',
  });

  final String keyPrefix;
  final String keyName;
  final String title;
  final RateStat stat;
  final int minSamples;
  final String help;
  final bool emphasized;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final value = stat.rate == null ? '信息不足' : percent(stat.rate!);
    final detail = stat.denominator == 0
        ? '还没有数据'
        : (stat.insufficientData
              ? '目前 ${rateCount(stat)}，至少 $minSamples 次有效作答才显示比例'
              : '${rateCount(stat)} 次有效作答');
    return SizedBox(
      width: emphasized ? 304 : 244,
      child: Card(
        key: ValueKey('$keyPrefix.$keyName'),
        color: emphasized ? scheme.primaryContainer : null,
        child: Padding(
          padding: const EdgeInsets.all(kPad),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: theme.textTheme.titleSmall),
              const SizedBox(height: 6),
              Text(
                value,
                style:
                    (stat.rate == null
                            ? theme.textTheme.titleLarge
                            : theme.textTheme.headlineMedium)
                        ?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 2),
              Text(detail, style: theme.textTheme.bodySmall),
              const SizedBox(height: 8),
              Text(
                help,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class RateBuckets extends StatelessWidget {
  const RateBuckets({
    super.key,
    required this.title,
    required this.buckets,
    required this.minSamples,
  });

  final String title;
  final List<ProgressBucket> buckets;
  final int minSamples;

  String _cell(RateStat stat) {
    if (stat.denominator == 0) return '—';
    final rate = stat.rate == null ? '' : '  ${percent(stat.rate!)}';
    return '${rateCount(stat)}$rate';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Section(
      title: title,
      child: Column(
        children: [
          Row(
            children: [
              const Expanded(flex: 2, child: SizedBox.shrink()),
              Expanded(
                flex: 3,
                child: Text('独立（对/总）', style: theme.textTheme.labelMedium),
              ),
              Expanded(
                flex: 3,
                child: Text('辅助（对/总）', style: theme.textTheme.labelMedium),
              ),
            ],
          ),
          const Divider(),
          for (final bucket in buckets)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                children: [
                  Expanded(
                    flex: 2,
                    child: Text(
                      bucket.label,
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                  Expanded(
                    flex: 3,
                    child: Text(
                      _cell(bucket.independent),
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                  Expanded(
                    flex: 3,
                    child: Text(
                      _cell(bucket.assisted),
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
